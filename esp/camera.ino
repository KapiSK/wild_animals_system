/* *****************************************************
 * es_cam.ino — Seeed XIAO ESP32-S3 (Final, Readable Version)
 *
 * トレイルカメラの動作:
 * 1. PIRセンサーまたは20分タイマーでDeep Sleepから起床
 * 2. カメラ初期化
 * 3. 4枚連続撮影 (0.5秒間隔):
 * - 1枚目は自動露出/ゲイン安定化のため破棄
 * - 2, 3, 4枚目を img1.jpg, img2.jpg, img3.jpg としてSDカードの
 * `/archive/[サイクルID]/` フォルダに保存
 * 4. Wi-Fi (SSID: "SLAB-g") に接続
 * 5. mDNS ("pi-server.local") でPi推論サーバーのIPアドレスを解決
 * 6. 未送信データのアップロード試行:
 * - SDカードの `/archive/` 内をスキャン
 * - アップロード履歴 (`/logs/uploaded_cids.txt`) になく、
 * - かつ、現在のサイクルから数えて直近5サイクル以内の失敗分で、
 * - かつ、画像3枚とログファイルが全て揃っているサイクルのみ、
 * - Pi推論サーバー (ポート5000) へHTTP POSTで送信
 * - 送信成功したら履歴ファイルにサイクルIDを追記
 * 7. アーカイブ整理:
 * - SDカードの `/archive/` 内のサイクルフォルダ数をカウント
 * - 100個を超えていたら、最も古いサイクルから順にフォルダごと削除
 * 8. 現在サイクルのログ保存:
 * - メモリ上のログバッファを `/archive/[サイクルID]/esp_chunk.log` に保存
 * - `/logs/esp.log` にも追記 (ローテーションあり)
 * 9. 30秒間の待機 (クールダウン)
 * 10. Deep Sleepへ移行
 *
 * ハードウェア接続:
 * - GPIO 1: PIRセンサー出力
 * - GPIO 2: モータードライバ IN1
 * - GPIO 3: モータードライバ IN2
 * - GPIO 4: ステータスLED (点灯:起動/接続済, 遅点滅:接続試行, 速点滅:処理中)
 * - GPIO 5: CDS光センサー入力
 * - GPIO 6: フラッシュLED (または赤外線LED) 制御
 * - SDカード: 標準SPIピン (GPIO 7, 8, 9, 21)
 * - カメラ: XIAO ESP32-S3 Sense ボード上のカメラ
 *****************************************************/

// =======================================================
// Includes
// =======================================================
#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <esp_system.h>
#include <esp_mac.h>       // For MAC address
#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>          // For timestamping logs
#include "esp_camera.h"
#include "esp_sleep.h"
#include <vector>
#include <cstdarg>         // For variadic functions (LOG_PRINTF)
#include <ArduinoJson.h>   // Though not currently used, kept for potential future use
#include "freertos/FreeRTOS.h" // For tasks
#include "freertos/task.h"   // For Task Handles
#include "mbedtls/sha256.h" // For SHA256 hashing
#include "esp_bt.h"         // For disabling Bluetooth
#include "driver/rtc_io.h"  // For deep sleep pin configuration
#include <ESPmDNS.h>       // For mDNS hostname resolution
#include <list>            // C++ STL list for managing cycle IDs
#include <algorithm>       // C++ STL sort etc.W
#include <string>          // C++ STL string for sorting

// =======================================================
// Hardware Pin Definitions
// =======================================================
#define CAMERA_MODEL_XIAO_ESP32S3
#include "camera_pins.h" // Include the board-specific camera pin definitions

namespace hw {
  constexpr uint8_t SD_CS         = 21; // SD Card Chip Select
  constexpr uint8_t SD_MOSI       = 9;  // SD Card MOSI
  constexpr uint8_t SD_MISO       = 8;  // SD Card MISO
  constexpr uint8_t SD_SCK        = 7;  // SD Card Clock
  constexpr uint8_t PIN_MOTION    = 1;  // PIR Sensor Input
  constexpr uint8_t PIN_MOTOR_IN1 = 2;  // Motor Driver Input 1
  constexpr uint8_t PIN_MOTOR_IN2 = 3;  // Motor Driver Input 2 (GPIO 3)
  constexpr uint8_t PIN_CDS       = 5;  // CDS Light Sensor Input (Analog)
  constexpr uint8_t PIN_FLASH     = 6;  // Flash/IR LED Control Output
  constexpr uint8_t PIN_STATUS    = 4;  // Status LED Output (GPIO 4)
  constexpr uint8_t PIN_FLAG      = PIN_MOTION; // Alias for wake pin used in sleep setup
  constexpr uint8_t PIN_MOTOR     = PIN_MOTOR_IN1; // Alias for Motor IN1
}

// =======================================================
// Network Configuration
// =======================================================
namespace net {
  constexpr char WIFI_SSID[]    = "SLAB-g";       // Your Wi-Fi Network Name
  constexpr char WIFI_PASS[]    = "wakaW1sat0";   // Your Wi-Fi Password
  constexpr uint32_t WIFI_TIMEOUT = 15000;        // Wi-Fi connection attempt timeout (ms)
  constexpr char PI_MDNS_HOST[] = "wild-animal";    // mDNS hostname of your Pi server (e.g., "pi-server.local")

  // These will be populated after mDNS resolution
  String PI_HOST;                                 // Base URL (e.g., "http://192.168.1.10:5000")
  String PI_UPLOAD_URL;                           // Full URL for image uploads
  String PI_HEALTHZ;                              // Full URL for Pi server health check
  String PI_ESPLOG_URL;                           // Full URL for ESP log chunk uploads

  constexpr char HDR_HASH[]     = "X-Content-SHA256"; // Custom HTTP header for SHA256 content verification
}

// =======================================================
// Behaviour Parameters
// =======================================================
namespace param {
  constexpr uint8_t  NUM_SHOTS_TOTAL     = 4;      // Total shots to take (1 discard + 3 save)
  constexpr uint8_t  NUM_SHOTS_SAVE      = 3;      // Number of shots to actually save
  constexpr uint32_t SHOT_INTERVAL_MS    = 500;    // Interval between shots (ms)
  constexpr int      MAX_ARCHIVE_CYCLES  = 100;    // Maximum number of cycles to keep in /archive
  constexpr uint8_t  UPLOAD_RETRY_WINDOW = 3;      // How many recent cycles (relative to current) to retry uploading
  constexpr uint32_t SLEEP_COOLDOWN_MS   = 30000;  // Mandatory wait time before entering deep sleep (ms)
  constexpr uint32_t MIN_FREE_SPACE_MB = 30;
}

// =======================================================
// Status LED Control (using a dedicated FreeRTOS task)
// =======================================================
namespace status {
  enum class LedState { OFF, ON, BLINK_FAST, BLINK_SLOW, BLINK_ERROR };
  volatile LedState currentLedState = LedState::OFF; // State variable (volatile for thread safety)
  TaskHandle_t ledTaskHandle = NULL;                 // Handle for the LED task

  // FreeRTOS Task function to manage LED patterns
  void ledTask(void *pvParameters) {
    pinMode(hw::PIN_STATUS, OUTPUT);
    LedState taskState = LedState::OFF; // Local copy of the state
    LedState lastState = LedState::OFF; // Store previous state to detect changes
    uint32_t blinkDelay = 1000;         // Delay between state checks or blinks

    for (;;) { // Infinite loop for the task
      taskState = currentLedState; // Safely read the volatile state variable

      // If state changed, ensure LED is off briefly before starting new pattern
      if (taskState != lastState) {
        lastState = taskState;
        digitalWrite(hw::PIN_STATUS, LOW);
        vTaskDelay(pdMS_TO_TICKS(50)); // Short gap prevents visual glitches
      }

      // Set LED state based on current pattern
      switch (taskState) {
        case LedState::ON:         // Solid ON (e.g., Booted, Wi-Fi connected)
          digitalWrite(hw::PIN_STATUS, HIGH);
          blinkDelay = 1000;       // Check state again in 1 second
          break;
        case LedState::BLINK_FAST: // Fast blink (e.g., Capturing, Uploading, Error)
          digitalWrite(hw::PIN_STATUS, !digitalRead(hw::PIN_STATUS)); // Toggle LED
          blinkDelay = 150;        // 150ms interval
          break;
        case LedState::BLINK_SLOW: // Slow blink (e.g., Connecting Wi-Fi, Resolving mDNS)
          digitalWrite(hw::PIN_STATUS, !digitalRead(hw::PIN_STATUS)); // Toggle LED
          blinkDelay = 500;        // 500ms interval
          break;
        case LedState::BLINK_ERROR: // Very fast "panic" blink for fatal errors
          digitalWrite(hw::PIN_STATUS, !digitalRead(hw::PIN_STATUS)); // Toggle LED
          blinkDelay = 75; // 75ms interval (faster than BLINK_FAST)
          break;
        case LedState::OFF:        // Solid OFF (e.g., Sleeping, Wi-Fi failed)
        default:
          digitalWrite(hw::PIN_STATUS, LOW);
          blinkDelay = 1000;       // Check state again in 1 second
          break;
      }
      // Wait for the calculated delay, or until notified by setLed to change state immediately
      ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(blinkDelay));
    }
  }

  // Public function to change the LED state
  void setLed(LedState state) {
    currentLedState = state;
    // Notify the LED task to potentially update its pattern immediately
    if (ledTaskHandle != NULL) {
      xTaskNotifyGive(ledTaskHandle);
    }
  }

  // Initialize and start the LED control task
  void begin() {
    // Create the FreeRTOS task
    BaseType_t result = xTaskCreate(
      ledTask,         // Function to implement the task
      "LedTask",       // Name of the task
      1024,            // Stack size in words
      NULL,            // Task input parameter
      1,               // Priority of the task (lower numbers are lower priority)
      &ledTaskHandle   // Task handle to keep track of the created task
    );
    // Check if task creation was successful
    if (result != pdPASS || ledTaskHandle == NULL) {
      // Use direct Serial print as logging might not be ready
      Serial.println("[ERR] Failed to create LED Task!");
    }
  }
} // namespace status

// =======================================================
// Global Variables
// =======================================================
static HTTPClient g_http;             // Reusable HTTP client instance
String   g_cycleId        = "";       // ID for the current operation cycle (MAC-Sequence)
uint32_t g_tWake          = 0;        // Millis() timestamp when woken up
uint32_t g_tBegin         = 0;        // Millis() timestamp when capture/processing started
String   g_syslogBuf;                 // In-memory buffer for logs generated during this cycle
size_t   g_syslogStartOff = 0;        // Starting position in syslogBuf for the current cycle's chunk
bool     g_sdReady        = false;    // Flag indicating if SD card is mounted successfully
bool     g_piHostResolved = false;    // Flag indicating if Pi server IP was found via mDNS

std::list<String> g_uploadedCidList; // In-memory list of cycle IDs already uploaded successfully
const char* UPLOADED_LIST_PATH = "/logs/uploaded_cids.txt"; // Path to store the uploaded list persistently
uint32_t g_currentSeqNum  = 0;        // Sequence number of the current cycle (from /seq.txt)


// =======================================================
// Utility Functions
// =======================================================

/**
 * @brief Calculates SHA256 hash of data.
 * @param data Pointer to the data buffer.
 * @param len Length of the data in bytes.
 * @return SHA256 hash as a 64-character lowercase hex String.
 */
static String sha256Hex(const uint8_t* data, size_t len) {
    unsigned char mac[32]; // SHA256 output is 32 bytes
    mbedtls_sha256_context ctx;
    mbedtls_sha256_init(&ctx);
    mbedtls_sha256_starts(&ctx, 0); // 0 indicates SHA256 mode
    mbedtls_sha256_update(&ctx, data, len);
    mbedtls_sha256_finish(&ctx, mac);
    mbedtls_sha256_free(&ctx);
    char hex[65]; // Buffer for 64 hex characters + null terminator
    for (int i = 0; i < 32; i++) {
        sprintf(hex + 2 * i, "%02x", mac[i]); // Format each byte as 2 lowercase hex chars
    }
    hex[64] = '\0'; // Null-terminate the string
    return String(hex);
}

/**
 * @brief Gets the current timestamp as a String.
 * @return Timestamp string in "YYYYMMDD_HHMMSS" format.
 */
static String nowTimestamp() {
    time_t now = time(nullptr); // Get current time
    struct tm tm_info;
    localtime_r(&now, &tm_info); // Convert to local time structure
    char buf[20];
    strftime(buf, sizeof(buf), "%Y%m%d_%H%M%S", &tm_info); // Format the time
    return String(buf);
}

// =======================================================
// Logging Functions (Serial + SD Card + Memory Buffer)
// =======================================================
static File g_logFile;             // File handle for the daily SD log
static String g_curLogName = "";   // Name of the currently open daily log file

/**
 * @brief Opens or appends to the daily log file (/log_YYYYMMDD.txt).
 */
static void openNewDailyLogFile() {
    time_t now = time(nullptr);
    struct tm tm_info;
    localtime_r(&now, &tm_info);
    char name[32];
    strftime(name, sizeof(name), "/log_%Y%m%d.txt", &tm_info);
    String newLogName = name; // Use String for comparison
    if (g_curLogName != newLogName) {
        if (g_logFile) {
            g_logFile.close(); // Close previous day's log if open
        }
        g_curLogName = newLogName;
        g_logFile = SD.open(g_curLogName, FILE_APPEND); // Open for appending
        if (!g_logFile) {
            // Log error only to Serial as SD write failed
            Serial.printf("[ERR] Failed to open daily log: %s\n", g_curLogName.c_str());
        }
    }
}

/**
 * @brief Logs raw string to Serial, SD card (if open), and memory buffer.
 * @param s The C-style string to log.
 */
static void LOG_RAW(const char* s) {
    Serial.print(s);
    if (g_logFile) {
        g_logFile.print(s);
        // Consider adding g_logFile.flush(); if immediate SD write is critical
    }
    g_syslogBuf += s; // Append to the in-memory buffer for the current cycle
}

/**
 * @brief Logs a formatted string (like printf) to all destinations.
 * @param fmt Format string.
 * @param ... Variable arguments for the format string.
 * @return Number of characters written (excluding null terminator).
 */
static int LOG_PRINTF(const char *fmt, ...) {
    char tmp[256]; // Static buffer for formatted output
    va_list args;
    va_start(args, fmt);
    // Use vsnprintf for safe formatted output into the buffer
    int n = vsnprintf(tmp, sizeof(tmp), fmt, args);
    va_end(args);

    // Check for encoding errors or truncation
    if (n < 0) {
        Serial.println("[ERR] vsnprintf encoding error in LOG_PRINTF");
        tmp[0] = '\0'; // Make it an empty string
        n = 0;
    } else if (n >= sizeof(tmp)) {
        // Output was truncated, but tmp is still null-terminated safely by vsnprintf
        Serial.println("[WARN] Log message truncated in LOG_PRINTF");
        n = sizeof(tmp) - 1; // n reflects the truncated length
    }
    // tmp is guaranteed to be null-terminated at this point (up to size-1)
    LOG_RAW(tmp); // Log the formatted string
    return n;
}

/**
 * @brief Macro for logging a string followed by a newline.
 */
#define LOG_PRINTLN(s) LOG_PRINTF("%s\n", (s))

/**
 * @brief Namespace for SD card log file management (rotation).
 */
namespace elog {
    const char* DIR = "/logs";             // Directory for logs on SD card
    const char* ESP = "/logs/esp.log";     // Path to the main persistent ESP log file
    constexpr size_t MAX_LINES = 2000;     // Rotate file when this many lines are exceeded

    /** @brief Ensures the log directory exists. */
    static void ensure() {
        if (!SD.exists(DIR)) {
            if (!SD.mkdir(DIR)) {
                LOG_PRINTLN("[ERR] Failed to create /logs directory!");
            }
        }
    }
    /** @brief Generates a timestamp string for rotated log filenames. */
    static String tsSuffix() { /* ... (Implementation as before) ... */ }
    /** @brief Counts the number of lines (newlines) in a file. */
    static size_t countLines(const char* path) { /* ... (Implementation as before) ... */ }
    /** @brief Rotates a log file by renaming it (e.g., esp.log -> esp.log.YYYYMMDD_HHMMSS). */
    static void rotate(const char* path) { /* ... (Implementation as before) ... */ }
    /** @brief Appends a string to a log file, performing rotation if necessary. */
    static void appendWithRotate(const char* path, const String& s, size_t max_lines = MAX_LINES) { /* ... (Implementation as before) ... */ }
}

// =======================================================
// Wi-Fi Connection
// =======================================================
/**
 * @brief Connects the ESP32 to the configured Wi-Fi network (STA mode).
 * Updates status LED during the process.
 */
static void initWiFi() {
    status::setLed(status::LedState::BLINK_SLOW); // LED: Indicates connection attempt
    WiFi.mode(WIFI_STA); // Set Wi-Fi mode to Station (client)
    WiFi.begin(net::WIFI_SSID, net::WIFI_PASS); // Start connection attempt
    LOG_PRINTF("[WIFI] Connecting to %s", net::WIFI_SSID);

    uint32_t t0 = millis();
    // Wait for connection or timeout
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - t0 > net::WIFI_TIMEOUT) {
            LOG_PRINTLN("\n[WIFI] Connection Failed (Timeout)!");
            status::setLed(status::LedState::OFF); // LED: Off indicates failure
            return; // Exit if connection timed out
        }
        Serial.print("."); // Visual progress on Serial
        // The LED task handles blinking, just check status periodically
        vTaskDelay(pdMS_TO_TICKS(500));
    }

    // Connected successfully
    LOG_PRINTLN("\n[WIFI] Connected Successfully.");
    LOG_PRINTLN("[WIFI] IP Address: " + WiFi.localIP().toString());
    status::setLed(status::LedState::ON); // LED: Solid ON indicates success
}

// =======================================================
// Camera Functions
// =======================================================
/**
 * @brief Initializes the camera sensor with specified settings.
 * @return True if initialization is successful, False otherwise.
 */
static bool initCamera() {
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_d0 = Y2_GPIO_NUM; config.pin_d1 = Y3_GPIO_NUM; config.pin_d2 = Y4_GPIO_NUM;
    config.pin_d3 = Y5_GPIO_NUM; config.pin_d4 = Y6_GPIO_NUM; config.pin_d5 = Y7_GPIO_NUM;
    config.pin_d6 = Y8_GPIO_NUM; config.pin_d7 = Y9_GPIO_NUM;
    config.pin_xclk = XCLK_GPIO_NUM; config.pin_pclk = PCLK_GPIO_NUM;
    config.pin_vsync = VSYNC_GPIO_NUM; config.pin_href = HREF_GPIO_NUM;
    config.pin_sscb_sda = SIOD_GPIO_NUM; config.pin_sscb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn = PWDN_GPIO_NUM; config.pin_reset = RESET_GPIO_NUM;
    config.xclk_freq_hz = 20000000;      // Camera clock frequency
    config.frame_size = FRAMESIZE_UXGA;  // Resolution (1600x1200)
    config.pixel_format = PIXFORMAT_JPEG; // Output format
    config.jpeg_quality = 10;            // JPEG quality (0-63, lower is higher quality but larger size) - 10 is reasonable
    config.fb_count = 1;                 // Number of frame buffers (1 is usually enough for single shots)
    config.fb_location = CAMERA_FB_IN_PSRAM; // Use PSRAM for frame buffer
    config.grab_mode = CAMERA_GRAB_LATEST; // Grab the latest frame, discard older ones

    // Initialize the camera
    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        LOG_PRINTF("[ERR] Camera initialization failed with error 0x%x\n", err);
        return false;
    }

    // Optional: Get sensor object to configure settings like V-Flip, brightness etc.
    // sensor_t * s = esp_camera_sensor_get();
    // s->set_vflip(s, 1);       // Example: Flip camera image vertically
    // s->set_brightness(s, 0); // Example: Set brightness (-2 to 2)

    return true; // Success
}

/**
 * @brief Captures an image, discards if it's the first, saves otherwise.
 * @param captureIndex The index of this capture in the sequence (1-based).
 * @param saveIndex The index to use for saving the file (1-based, 0 if discard).
 * @return True if capture and save (or discard) were successful, False on error.
 */
static bool shootAndSave(uint8_t captureIndex, uint8_t saveIndex) {
    status::setLed(status::LedState::BLINK_FAST); // LED: Indicate capture activity
    camera_fb_t * fb = esp_camera_fb_get(); // Get frame buffer
    status::setLed(status::LedState::ON); // LED: Back to solid after capture attempt

    // Check if frame buffer acquisition failed
    if (!fb) {
        LOG_PRINTF("[ERR] Camera capture failed for shot #%u\n", captureIndex);
        return false;
    }
    // Check if the format is JPEG (should be, based on config)
    if (fb->format != PIXFORMAT_JPEG) {
        LOG_PRINTLN("[ERR] Captured frame is not in JPEG format!");
        esp_camera_fb_return(fb); // Return buffer even on error
        return false;
    }

    // --- Discard Logic ---
    if (captureIndex == 1) {
        LOG_PRINTF("[CAM] Discarding stabilization shot #%u\n", captureIndex);
        esp_camera_fb_return(fb); // Return the buffer without saving
        return true; // Indicate success for the sequence step
    }

    // --- Save Logic ---
    String cycleDir = "/archive/" + g_cycleId; // Path to cycle directory
    // Create directory only when saving the first *valid* image (saveIndex == 1)
    if (saveIndex == 1) {
        if (!SD.exists("/archive")) {
            if (!SD.mkdir("/archive")) {
                LOG_PRINTLN("[ERR] Failed to create /archive directory!");
                esp_camera_fb_return(fb); return false;
            }
        }
        if (!SD.exists(cycleDir)) {
            if (!SD.mkdir(cycleDir)) {
                LOG_PRINTF("[ERR] Failed to create cycle directory %s\n", cycleDir.c_str());
                esp_camera_fb_return(fb); return false;
            }
        }
    }

    char path[64]; // Buffer for file path
    sprintf(path, "%s/img%u.jpg", cycleDir.c_str(), saveIndex); // Construct filename (img1.jpg, img2.jpg, ...)

    status::setLed(status::LedState::BLINK_FAST); // LED: Indicate saving to SD
    File file = SD.open(path, FILE_WRITE); // Open file for writing
    bool success = false;
    if (file) {
        size_t written = file.write(fb->buf, fb->len); // Write frame buffer content
        file.close(); // Close file immediately
        if (written == fb->len) {
            LOG_PRINTF("[SAVE] %s (%u bytes, Cap #%u)\n", path, fb->len, captureIndex);
            success = true;
        } else {
            // Write failed or incomplete
            LOG_PRINTF("[ERR] Failed to write complete file %s (%u/%u bytes)\n", path, written, fb->len);
            SD.remove(path); // Delete incomplete file
        }
    } else {
        LOG_PRINTF("[ERR] Failed to open file for writing: %s\n", path);
    }
    status::setLed(status::LedState::ON); // LED: Back to solid after save attempt

    esp_camera_fb_return(fb); // IMPORTANT: Always return the frame buffer
    return success;
}

// =======================================================
// Pi Server Interaction (Upload Logic)
// =======================================================

/**
 * @brief Loads the list of successfully uploaded cycle IDs from the SD card file.
 */
static void loadUploadedList() {
    g_uploadedCidList.clear(); // Clear the in-memory list first
    File file = SD.open(UPLOADED_LIST_PATH, FILE_READ);
    if (!file) {
        LOG_PRINTLN("[UPLOAD] Uploaded list file not found. Assuming none uploaded.");
        // Attempt to create the directory if it doesn't exist
        elog::ensure(); // Ensure /logs exists
        return;
    }
    while (file.available()) {
        String cid = file.readStringUntil('\n');
        cid.trim(); // Remove leading/trailing whitespace/newlines
        if (cid.length() > 0) {
            g_uploadedCidList.push_back(cid); // Add to in-memory list
        }
    }
    file.close();
    LOG_PRINTF("[UPLOAD] Loaded %d previously uploaded CIDs from list.\n", g_uploadedCidList.size());
}

/**
 * @brief Checks if a given cycle ID is present in the in-memory uploaded list.
 * @param cid The cycle ID String to check.
 * @return True if the ID exists in the list, False otherwise.
 */
static bool isCidUploaded(const String& cid) {
    // Iterate through the list to find a match
    for (const String& uploadedCid : g_uploadedCidList) {
        if (uploadedCid == cid) {
            return true;
        }
    }
    return false; // Not found
}

/**
 * @brief Marks a cycle ID as successfully uploaded by adding it to the list (memory and file).
 * @param cid The cycle ID String to mark.
 */
static void markAsUploaded(const String& cid) {
    if (isCidUploaded(cid)) {
        return; // Already marked, do nothing
    }
    g_uploadedCidList.push_back(cid); // Add to the in-memory list

    // Append the new CID to the file on the SD card
    File file = SD.open(UPLOADED_LIST_PATH, FILE_APPEND);
    if (!file) {
        LOG_PRINTLN("[ERR] Failed to open upload list file for appending!");
        // Potential issue: list in memory and file are now out of sync
        return;
    }
    file.println(cid); // Add the ID followed by a newline
    file.close();
    LOG_PRINTF("[UPLOAD] Marked cycle %s as uploaded.\n", cid.c_str());
}

/**
 * @brief Resolves the Pi server's IP address using mDNS.
 * Updates global network strings if successful.
 * @return True if resolution is successful, False otherwise.
 */
static bool resolvePiHost() {
    if (WiFi.status() != WL_CONNECTED) {
        LOG_PRINTLN("[mDNS] Wi-Fi not connected, cannot resolve host.");
        return false;
    }
    status::setLed(status::LedState::BLINK_SLOW); // LED: Indicate mDNS resolution attempt
    LOG_PRINTF("[mDNS] Resolving host: %s.local ...\n", net::PI_MDNS_HOST);

    // Start mDNS (use a unique hostname for the ESP itself if needed)
    if (!MDNS.begin("esp32-cam")) { // Hostname for this ESP device
        LOG_PRINTLN("[ERR] Failed to start mDNS responder.");
        status::setLed(status::LedState::ON); // Back to solid ON (Wi-Fi state)
        return false;
    }

    // Query for the Pi server's hostname with a timeout
    IPAddress piIP = MDNS.queryHost(net::PI_MDNS_HOST, 5000); // 5-second timeout

    MDNS.end(); // Stop mDNS service after query

    // Check if a valid IP address was returned
    if (piIP == INADDR_NONE || piIP[0] == 0) { // Check for 0.0.0.0 as well
        LOG_PRINTLN("[mDNS] Host not found.");
        g_piHostResolved = false;
        status::setLed(status::LedState::ON); // Back to solid ON (Wi-Fi state)
        return false;
    }

    // Success! Store the resolved IP and construct full URLs
    LOG_PRINTF("[mDNS] Host found! IP Address: %s\n", piIP.toString().c_str());
    String hostBase = "http://" + piIP.toString() + ":5000"; // Assuming Pi server runs on port 5000
    net::PI_HOST       = hostBase;
    net::PI_UPLOAD_URL = hostBase + "/upload";
    net::PI_HEALTHZ    = hostBase + "/healthz";
    net::PI_ESPLOG_URL = hostBase + "/esp_log";
    g_piHostResolved = true;
    status::setLed(status::LedState::ON); // Back to solid ON (resolution successful)
    return true;
}

/**
 * @brief Uploads a single file to the Pi server via HTTP POST.
 * @param url The full URL endpoint on the Pi server.
 * @param path The path to the file on the ESP32's SD card.
 * @param ctype The Content-Type header value (e.g., "image/jpeg").
 * @param cycleId The cycle ID associated with this file.
 * @param imgIdx The image index (1, 2, or 3) if applicable, 0 otherwise (for log file).
 * @return True if the upload returns HTTP 200 OK, False otherwise.
 */
static bool uploadFile(const String& url, const String& path, const char* ctype, const String& cycleId, int imgIdx) {
    status::setLed(status::LedState::BLINK_FAST); // LED: Indicate file transfer
    File file = SD.open(path, FILE_READ);

    // Check if file opened successfully
    if (!file) {
        LOG_PRINTF("[ERR] Upload: File not found %s\n", path.c_str());
        status::setLed(status::LedState::ON); // Back to solid ON
        return false;
    }
    // Check if file is empty
    size_t fileSize = file.size();
    if (fileSize == 0) {
        LOG_PRINTF("[WARN] Upload: Skipping empty file %s\n", path.c_str());
        file.close();
        status::setLed(status::LedState::ON);
        return true; // Treat empty file upload as success? Or should it be false? Let's say true.
    }

    bool success = false;
    HTTPClient httpClient; // Use local instance for thread safety if tasks change

    // Use WiFiClientSecure for HTTPS if needed in the future
    if (httpClient.begin(url)) { // Use String URL object
        // Set headers
        httpClient.addHeader("Content-Type", ctype);
        httpClient.addHeader("X-Cycle-Id", cycleId);
        if (imgIdx > 0) {
            httpClient.addHeader("X-Img-Index", String(imgIdx));
        }

        // Calculate SHA256 Hash for content verification
        mbedtls_sha256_context ctx;
        mbedtls_sha256_init(&ctx);
        mbedtls_sha256_starts(&ctx, 0);
        uint8_t buf[2048]; // Buffer for reading file chunks
        int bytesRead;
        while ((bytesRead = file.read(buf, sizeof(buf))) > 0) {
            mbedtls_sha256_update(&ctx, buf, bytesRead);
        }
        unsigned char hashResult[32];
        mbedtls_sha256_finish(&ctx, hashResult);
        mbedtls_sha256_free(&ctx);
        char hexHash[65];
        for (int i = 0; i < 32; i++) sprintf(hexHash + 2 * i, "%02x", hashResult[i]);
        hexHash[64] = '\0';

        file.seek(0); // Rewind file pointer to the beginning for sending
        httpClient.addHeader(net::HDR_HASH, String(hexHash)); // Add hash header
        httpClient.setTimeout(15000); // Set timeout for the request (ms)

        // Send the POST request with the file stream and size
        int httpCode = httpClient.sendRequest("POST", &file, fileSize);

        // Check response code
        if (httpCode == HTTP_CODE_OK) {
            success = true;
            LOG_PRINTF("[UPLOAD] OK: %s -> %d\n", path.c_str(), httpCode);
        } else {
            // Log error with HTTP code and potentially response body
            LOG_PRINTF("[ERR] Upload Failed: %s -> %d (%s)\n", path.c_str(), httpCode, httpClient.errorToString(httpCode).c_str());
            // String responseBody = httpClient.getString(); // Uncomment to see server response
            // LOG_PRINTF("Response: %s\n", responseBody.c_str());
        }
        httpClient.end(); // End the connection
    } else {
        LOG_PRINTF("[ERR] HTTPClient begin failed for URL: %s\n", url.c_str());
    }

    file.close(); // Ensure file is closed
    status::setLed(status::LedState::ON); // LED: Back to solid after attempt
    return success;
}

/**
 * @brief Extracts the sequence number from a cycle ID string (e.g., "MAC-00000005" -> 5).
 * @param cid The cycle ID String.
 * @return The sequence number as a long, or -1 if parsing fails.
 */
long getSeqNumFromCid(const String& cid) {
    int dashPos = cid.lastIndexOf('-');
    // Check if dash exists and is not the last character
    if (dashPos == -1 || dashPos + 1 >= cid.length()) {
        return -1;
    }
    // Extract the substring after the dash
    String seqStr = cid.substring(dashPos + 1);
    // Convert to long using C++ std::stol for better error handling
    try {
        // Need to convert Arduino String to std::string first
        std::string s = seqStr.c_str();
        return std::stol(s);
    } catch (const std::invalid_argument& ia) {
        LOG_PRINTF("[ERR] Invalid sequence number string: %s\n", seqStr.c_str());
        return -1;
    } catch (const std::out_of_range& oor) {
        LOG_PRINTLN("[ERR] Sequence number out of range.");
        return -1;
    }
    // Fallback using Arduino String toInt() if std::stol fails compilation (less safe)
    // long seqNum = seqStr.toInt();
    // return (seqNum == 0 && seqStr != "0") ? -1 : seqNum; // Basic check if toInt failed
}

// --- Archive Cleanup Helpers ---
/** @brief Comparator struct for sorting cycle ID strings numerically by sequence number. */
struct CidComparator {
    bool operator()(const String& a, const String& b) const {
        long seqA = getSeqNumFromCid(a);
        long seqB = getSeqNumFromCid(b);
        // If sequence numbers are valid, compare them
        if (seqA != -1 && seqB != -1) {
            return seqA < seqB; // Sort ascending by sequence number
        }
        // Fallback to string comparison if parsing fails for either ID
        return a < b;
    }
};
/** @brief Lists directories inside a given path, sorted by cycle ID sequence number. */
static std::list<String> listCycleDirs(const char* dirPath) {
    std::list<String> dirs;
    File root = SD.open(dirPath);
    if (!root) { LOG_PRINTF("[ERR] Cannot open directory: %s\n", dirPath); return dirs; }
    if (!root.isDirectory()) { LOG_PRINTF("[ERR] Not a directory: %s\n", dirPath); root.close(); return dirs; }

    File file;
    while (file = root.openNextFile()) {
        if (file.isDirectory()) {
            String dirName = file.name();
            // Extract just the directory name from full path if needed
            int lastSlash = dirName.lastIndexOf('/');
            if (lastSlash != -1) dirName = dirName.substring(lastSlash + 1);
            // Add to list only if it looks like a valid Cycle ID
            if (getSeqNumFromCid(dirName) != -1) {
                dirs.push_back(dirName);
            } else {
                 LOG_PRINTF("[WARN] listCycleDirs: Skipping non-CID directory: %s\n", dirName.c_str());
            }
        }
        file.close(); // Important: close file handle
    }
    root.close(); // Close directory handle
    dirs.sort(CidComparator()); // Sort the list using the custom comparator
    return dirs;
}

/**
 * @brief 最新のサイクルから順にスキャンし、未送信のものを最大3件までアップロードする。
 */
static void uploadPendingData() {
    if (!g_piHostResolved) { LOG_PRINTLN("[UPLOAD] Pi host not resolved, skip."); return; }
    status::setLed(status::LedState::ON); // LED: Solid before check

    // 1. サーバーのヘルスチェック
    HTTPClient healthCheckClient;
    healthCheckClient.setTimeout(3000);
    bool piOk = false;
    // ※仮IP対応を入れている場合はURLが正しいか注意してください
    if (healthCheckClient.begin(net::PI_HEALTHZ)) {
        int httpCode = healthCheckClient.GET();
        healthCheckClient.end();
        if (httpCode == HTTP_CODE_OK) {
            piOk = true;
        } else {
             LOG_PRINTF("[UPLOAD] Pi health check failed (HTTP %d). Skipping uploads.\n", httpCode);
        }
    } else {
        LOG_PRINTLN("[ERR] HTTPClient begin failed for health check.");
    }
    if (!piOk) return;

    LOG_PRINTLN("[UPLOAD] Pi server OK. Scanning archive (Newest -> Oldest)...");

    // 2. サイクル一覧を取得 (この関数は内部で昇順ソートしています)
    // ※フォルダ数が多いとここで少し時間がかかりますが、タイムアウト前にリスト化します
    std::list<String> cycleDirs = listCycleDirs("/archive");
    
    // 3. リストを逆順 (降順) にする -> 最新のものが先頭に来る
    cycleDirs.reverse();

    long currentSeq = g_currentSeqNum;
    // 再試行範囲の計算 (現在 - 3)
    long minSeqToRetry = max(0L, (currentSeq > param::UPLOAD_RETRY_WINDOW) ? (currentSeq - param::UPLOAD_RETRY_WINDOW) : 0L);
    
    LOG_PRINTF("[UPLOAD] Current seq: %ld. Retry window: >= %ld. Found %d total cycles.\n", currentSeq, minSeqToRetry, cycleDirs.size());

    int uploadCount = 0;
    const int MAX_UPLOADS_LIMIT = 3; // ★ユーザー要望: 最大3件まで

    // 4. リストの上から順 (最新順) にチェック
    for (const String& cid : cycleDirs) {
        
        // 既に3件アップロードしたら終了
        if (uploadCount >= MAX_UPLOADS_LIMIT) {
            LOG_PRINTLN("[UPLOAD] Reached limit of 3 uploads per cycle.");
            break;
        }

        // --- フィルタリング ---
        
        // A. 既にアップロード済みならスキップ
        if (isCidUploaded(cid)) { continue; }

        // B. 再試行ウィンドウより古いならスキップ (ただし最新サイクル=currentSeqは除外せず通す)
        long cycleSeq = getSeqNumFromCid(cid);
        if (cycleSeq == -1) continue; // 無効なID
        
        if (cycleSeq < minSeqToRetry && cycleSeq != currentSeq) {
            LOG_PRINTF("[UPLOAD] Reached old data (seq %ld). Stop scanning.\n", cycleSeq);
            break; // これを入れるとさらに高速化されます
        }

        // C. ファイルが揃っているかチェック
        String p1 = "/archive/" + cid + "/img1.jpg";
        String p2 = "/archive/" + cid + "/img2.jpg";
        String p3 = "/archive/" + cid + "/img3.jpg";
        String pLog = "/archive/" + cid + "/esp_chunk.log";
        
        if (!SD.exists(p1) || !SD.exists(p2) || !SD.exists(p3) || !SD.exists(pLog)) {
            LOG_PRINTF("[UPLOAD] Skipping incomplete cycle: %s\n", cid.c_str());
            continue;
        }

        // --- アップロード実行 ---
        LOG_PRINTF("[UPLOAD] Uploading %s (seq %ld)...\n", cid.c_str(), cycleSeq);
        status::setLed(status::LedState::BLINK_FAST);

        bool ok1 = uploadFile(net::PI_UPLOAD_URL, p1, "image/jpeg", cid, 1);
        bool ok2 = uploadFile(net::PI_UPLOAD_URL, p2, "image/jpeg", cid, 2);
        bool ok3 = uploadFile(net::PI_UPLOAD_URL, p3, "image/jpeg", cid, 3);
        bool okLog = uploadFile(net::PI_ESPLOG_URL, pLog, "text/plain", cid, 0);

        status::setLed(status::LedState::ON);

        if (ok1 && ok2 && ok3 && okLog) {
            markAsUploaded(cid);
            uploadCount++; // カウントアップ
            LOG_PRINTF("[UPLOAD] Success! (%d/%d)\n", uploadCount, MAX_UPLOADS_LIMIT);
        } else {
            LOG_PRINTLN("[UPLOAD] Failed to upload all parts.");
        }
    }
    
    if (cycleDirs.empty()) {
        LOG_PRINTLN("[UPLOAD] No cycles found in archive.");
    }
}


/***********************************************************
 * 12.  Cycle / Logging chunks
 ***********************************************************/
/**
 * @brief Extracts the log messages generated during the current cycle from the memory buffer.
 * @return String containing the log chunk for the current cycle, or empty String if none.
 */
static String makeEspLogChunkForCurrentCycle() {
    String slice = "";
    if (g_syslogBuf.length() > g_syslogStartOff) {
        slice = g_syslogBuf.substring(g_syslogStartOff);
    }
    if (slice.length() == 0) return ""; // No new logs

    // Add header and ensure trailing newline
    String header = "[CYCLE] cid=" + g_cycleId + "\n";
    if (!slice.endsWith("\n")) slice += "\n";
    return header + slice;
}
/**
 * @brief Appends a chunk of log data to the main persistent log file (/logs/esp.log) with rotation.
 * @param chunk The log chunk String to append.
 */
static void updateEspLogAppendRotate(const String& chunk) {
    if (chunk.length() == 0) return;
    elog::appendWithRotate(elog::ESP, chunk, elog::MAX_LINES);
}

/***********************************************************
 * 14.  Light (CDS) & Motor Control
 ***********************************************************/
namespace lux { constexpr int THRESH = 2800; } // Light threshold (adjust based on environment)

/** @brief Reads CDS sensor and determines if it's currently night. */
static bool isNight() {
    int v = analogRead(hw::PIN_CDS); // Read analog value (0-4095)
    bool night = (v < lux::THRESH);
    LOG_PRINTF("[LUX ] CDS Pin=%u, Value=%d, Threshold=%d -> %s\n", hw::PIN_CDS, v, lux::THRESH, night ? "NIGHT" : "DAY");
    return night;
}

// Configuration for Day/Night actions
namespace daynight {
    constexpr bool LED_ON_AT_NIGHT = true; // Turn flash ON at night
    constexpr bool LED_ON_AT_DAY   = false; // Turn flash OFF during day
    enum class Dir { FWD, REV, STOP };     // Motor direction states
    constexpr Dir MOTOR_DIR_NIGHT = Dir::FWD; // Motor direction at night
    constexpr Dir MOTOR_DIR_DAY   = Dir::REV; // Motor direction during day
}

// --- Motor Control Functions ---
static inline void motorReverse() { digitalWrite(hw::PIN_MOTOR, HIGH); digitalWrite(hw::PIN_MOTOR_IN2, LOW); LOG_PRINTLN("[MOTOR] Forward"); }
static inline void motorForward() { digitalWrite(hw::PIN_MOTOR, LOW); digitalWrite(hw::PIN_MOTOR_IN2, HIGH); LOG_PRINTLN("[MOTOR] Reverse"); }
static inline void motorStop()    { digitalWrite(hw::PIN_MOTOR, LOW); digitalWrite(hw::PIN_MOTOR_IN2, LOW); LOG_PRINTLN("[MOTOR] Stop"); }

/** @brief Activates LED and Motor based on the isNight() status. */
static void applyDayNightActions(bool night) {
    // Control Flash LED
    bool ledOn = night ? daynight::LED_ON_AT_NIGHT : daynight::LED_ON_AT_DAY;
    digitalWrite(hw::PIN_FLASH, ledOn ? HIGH : LOW);
    LOG_PRINTF("[LED ] Flash %s\n", ledOn ? "ON" : "OFF");

    // Control Motor Direction
    daynight::Dir direction = night ? daynight::MOTOR_DIR_NIGHT : daynight::MOTOR_DIR_DAY;
    switch (direction) {
        case daynight::Dir::FWD: motorForward(); break;
        case daynight::Dir::REV: motorReverse(); break;
        case daynight::Dir::STOP:
        default:                 motorStop();    break;
    }
}

/***********************************************************
 * 15.  Sleep helpers
 ***********************************************************/
namespace sleepcfg {
    constexpr int      WAKE_PIN  = hw::PIN_FLAG;   // GPIO pin for PIR wake-up
    constexpr bool     WAKE_HIGH = true;         // Wake up on HIGH signal from PIR
    constexpr uint32_t PREP_MS   = 200;          // Short delay before entering sleep
    constexpr uint64_t TIMER_US  = uint64_t(20) * 60 * 1000000ULL; // 20 minute timer wake-up
}

/**
 * @brief Configures wake-up sources (PIR pin, Timer) and logs the wake-up reason.
 * If wake reason is COLD BOOT (power on reset), enters deep sleep immediately.
 */
static void configureWakeAndMaybeSleepEarly() {
    // Configure PIR wake-up pin (EXT1)
    rtc_gpio_isolate(GPIO_NUM_1);
    pinMode(sleepcfg::WAKE_PIN, sleepcfg::WAKE_HIGH ? INPUT_PULLDOWN : INPUT_PULLUP);
    esp_sleep_enable_ext1_wakeup(1ULL << sleepcfg::WAKE_PIN,
                                 sleepcfg::WAKE_HIGH ? ESP_EXT1_WAKEUP_ANY_HIGH : ESP_EXT1_WAKEUP_ALL_LOW);

    // Enable timer wake-up
    esp_sleep_enable_timer_wakeup(sleepcfg::TIMER_US);

    // Get and log the reason for waking up
    esp_sleep_wakeup_cause_t wakeup_reason = esp_sleep_get_wakeup_cause();
    switch (wakeup_reason) {
        case ESP_SLEEP_WAKEUP_EXT1:     LOG_PRINTLN("[SLEEP] Wake reason: PIR Sensor (EXT1)"); break;
        case ESP_SLEEP_WAKEUP_TIMER:    LOG_PRINTLN("[SLEEP] Wake reason: Timer (20 min)"); break;
        case ESP_SLEEP_WAKEUP_UNDEFINED:LOG_PRINTLN("[SLEEP] Wake reason: Power On / Cold Boot"); break;
        default:                        LOG_PRINTF("[SLEEP] Wake reason: Other (%d)\n", (int)wakeup_reason); break;
    }

    // If it was a cold boot (not PIR or Timer), go back to sleep immediately to save power
    if (wakeup_reason != ESP_SLEEP_WAKEUP_EXT1 && wakeup_reason != ESP_SLEEP_WAKEUP_TIMER) {
        LOG_PRINTLN("[SLEEP] Cold boot detected, entering sleep immediately.");
        status::setLed(status::LedState::OFF); // Turn off LED
        delay(sleepcfg::PREP_MS);              // Short delay
        esp_deep_sleep_start();                // Enter deep sleep
    }
    // Otherwise, continue with normal operation
}


/** @brief Recursively removes a directory and all its contents. Use with caution! */
static bool removeDirRecursive(const String& path) {
    File dir = SD.open(path);
    if (!dir) { LOG_PRINTF("[ERR] GC: Cannot open directory to remove: %s\n", path.c_str()); return false; }
    if (!dir.isDirectory()) { // If it's a file, just remove it
        dir.close();
        return SD.remove(path);
    }

    File file;
    bool success = true;
    // Iterate through directory contents
    while (file = dir.openNextFile()) {
        String filePath = path + "/" + file.name(); // Construct full path of item
        if (file.isDirectory()) {
            success &= removeDirRecursive(filePath); // Recurse into subdirectory
        } else {
            // It's a file, remove it
            if (!SD.remove(filePath)) {
                 LOG_PRINTF("[ERR] GC: Failed to remove file: %s\n", filePath.c_str());
                 success = false; // Mark failure but continue trying others
            }
        }
        file.close(); // Close item handle
    }
    dir.close(); // Close directory handle

    // If all contents were removed successfully, remove the now-empty directory
    if (success) {
        if (!SD.rmdir(path)) {
            LOG_PRINTF("[ERR] GC: Failed to remove directory itself: %s\n", path.c_str());
            success = false;
        }
    }
    return success;
}
/** @brief Cleans up oldest archive directories if count exceeds MAX_ARCHIVE_CYCLES. */
static void cleanupOldArchives() {
    LOG_PRINTLN("[GC] Checking free space...");

    // 1. しきい値をバイト単位に変換
    const uint64_t MIN_FREE_BYTES = (uint64_t)param::MIN_FREE_SPACE_MB * 1024 * 1024;
    
    // 2. SDカードの現在の空き容量を計算
    // (SD.totalBytes() や SD.usedBytes() は時間がかかる場合があります)
    uint64_t totalBytes = SD.totalBytes();
    uint64_t usedBytes = SD.usedBytes();
    
    // オーバーフロー防止 (あり得ないが念のため)
    if (usedBytes > totalBytes) { usedBytes = totalBytes; }
    
    uint64_t freeBytes = totalBytes - usedBytes;
    uint64_t freeMB = freeBytes / (1024 * 1024);
    
    // 3. 空き容量がしきい値を上回っているかチェック
    if (freeBytes >= MIN_FREE_BYTES) {
        LOG_PRINTF("[GC] Free space OK (%llu MB free, Threshold: %u MB). No cleanup needed.\n", freeMB, param::MIN_FREE_SPACE_MB);
        return; // 十分な空きがあるので何もしない
    }

    // 4. 空き容量が不足しているため、クリーンアップを開始
    LOG_PRINTF("[GC] Free space LOW (%llu MB free, Threshold: %u MB). Starting cleanup...\n", freeMB, param::MIN_FREE_SPACE_MB);

    std::list<String> cycleDirs = listCycleDirs("/archive"); // 
    if (cycleDirs.empty()) {
        LOG_PRINTLN("[GC] Archive is empty, but free space is still low. Cannot cleanup.");
        return; // 削除対象がない
    }

    int removedCount = 0;
    bool spaceFreed = false; // 容量が確保できたか
    
    // 5. 古いもの (リストの先頭) から順に削除するループ
    for (const String& oldestCid : cycleDirs) {
        String dirPath = "/archive/" + oldestCid;
        LOG_PRINTF("[GC] Removing old cycle: %s\n", dirPath.c_str());

        if (removeDirRecursive(dirPath)) { // [cite: 328]
            // ディレクトリ削除成功
            removedCount++;
            g_uploadedCidList.remove(oldestCid); // [cite: 349] メモリ上のアップロード履歴からも削除
            
            // 6. 削除後に再度、空き容量をチェック
            // (注: 毎回 usedBytes を呼ぶのは高コストですが確実です)
            freeBytes = SD.totalBytes() - SD.usedBytes();
            
            if (freeBytes >= MIN_FREE_BYTES) {
                // しきい値を超える空き容量を確保できた
                spaceFreed = true;
                LOG_PRINTF("[GC] Successfully freed space. New free space: %llu MB.\n", freeBytes / (1024*1024));
                break; // 削除ループを終了
            }
            // まだ足りないのでループを続行
            
        } else {
             LOG_PRINTLN("[GC] Failed to remove directory. It might remain in uploaded list.");
             // 削除に失敗した場合、次のアイテムに進む
        }
    } // End of for loop

    if (!spaceFreed && removedCount > 0) {
        LOG_PRINTLN("[WARN] Removed all possible cycles, but free space might still be below threshold.");
    }
    
    LOG_PRINTF("[GC] Total cycles removed this run: %d\n", removedCount);

    // 7. 削除処理が完了した後、アップロード履歴ファイルを更新する
    if (removedCount > 0) {
        // メモリリストの変更をSDカードファイルに反映する
        File file = SD.open(UPLOADED_LIST_PATH, FILE_WRITE); // [cite: 352]
        if (file) {
            for (const String& cid : g_uploadedCidList) {
                file.println(cid); // [cite: 353]
            }
            file.close(); // [cite: 354]
            LOG_PRINTLN("[GC] Rewrote uploaded CIDs list file.");
        } else {
            LOG_PRINTLN("[ERR] Failed to open uploaded list file for rewriting after GC!"); // [cite: 355]
        }
    }
}

static void goDeepSleepNow() {
    status::setLed(status::LedState::OFF); // Turn LED off during final prep

    // --- Cleanup and Resource Release ---
    cleanupOldArchives(); // Remove old cycles if > MAX_ARCHIVE_CYCLES
    esp_camera_deinit();  // Deinitialize camera
    if (WiFi.getMode() != WIFI_OFF) {
        WiFi.disconnect(true, true); // Disconnect Wi-Fi
        delay(100);                  // Short delay for disconnect process
        WiFi.mode(WIFI_OFF);         // Turn off Wi-Fi module
    }
    btStop(); // Turn off Bluetooth module (saves power)
    delay(100);

    // --- Cooldown Period & Final Pin State ---
    LOG_PRINTF("[SLEEP] Entering %u ms cooldown...\n", param::SLEEP_COOLDOWN_MS);
    
    const uint32_t ledWarningTime = 5000; // 5秒間の警告灯
    uint32_t initialWaitTime = 0;
    
    // 30秒から5秒を引いた、最初の待機時間
    if (param::SLEEP_COOLDOWN_MS > ledWarningTime) {
        initialWaitTime = param::SLEEP_COOLDOWN_MS - ledWarningTime;
    }

    // 1. 最初の待機 (LEDはローパワー状態)
    if (initialWaitTime > 0) {
        digitalWrite(hw::PIN_STATUS, LOW);
        pinMode(hw::PIN_STATUS, INPUT_PULLDOWN);
        delay(initialWaitTime);
    }

    // 2. 5秒間のスリープ前警告 (LED点灯)
    LOG_PRINTLN("[SLEEP] 5 sec warning LED ON before sleep.");
    pinMode(hw::PIN_STATUS, OUTPUT);  // ピンをOUTPUTに設定
    digitalWrite(hw::PIN_STATUS, HIGH); // LED点灯
    delay(ledWarningTime);
    digitalWrite(hw::PIN_STATUS, LOW);   // LED消灯

    // 3. スリープのためにピンをローパワー状態(INPUT_PULLDOWN)に設定
    pinMode(hw::PIN_STATUS, INPUT_PULLDOWN);


    // --- Configure Wake Up Sources ---
    // PIR Sensor (EXT1)
    rtc_gpio_isolate(GPIO_NUM_1);
    pinMode(sleepcfg::WAKE_PIN, sleepcfg::WAKE_HIGH ? INPUT_PULLDOWN : INPUT_PULLUP);
    esp_sleep_enable_ext1_wakeup(1ULL << sleepcfg::WAKE_PIN,
                                 sleepcfg::WAKE_HIGH ? ESP_EXT1_WAKEUP_ANY_HIGH : ESP_EXT1_WAKEUP_ALL_LOW);
    // Timer
    esp_sleep_enable_timer_wakeup(sleepcfg::TIMER_US);

    LOG_PRINTLN("[SLEEP] Cooldown finished. Entering Deep Sleep NOW.");
    esp_deep_sleep_start(); // Enter Deep Sleep
    // --- Code execution stops here until next wake up ---
}

/***********************************************************
 * 16.  Cycle Logic
 ***********************************************************/
/** @brief Gets the device's unique MAC address as a hex String. */
static String deviceIdHex() { uint8_t mac[6]; esp_read_mac(mac, ESP_MAC_WIFI_STA); char buf[13]; for (int i=0; i<6; i++) sprintf(buf + 2*i, "%02X", mac[i]); buf[12]='\0'; return String(buf); }
/** @brief Manages the persistent sequence number stored on SD card (/seq.txt). */
namespace seq {
    const char* PATH = "/seq.txt"; // File path for sequence number
    /** @brief Reads the last sequence number from the file. */
    static uint32_t read() {
        File f = SD.open(PATH, FILE_READ);
        if (!f) return 0; // Start from 0 if file doesn't exist
        String s = f.readStringUntil('\n');
        f.close();
        uint32_t v = 0;
        // Basic string to integer conversion
        for (size_t i = 0; i < s.length(); ++i) {
            if (s[i] < '0' || s[i] > '9') break; // Stop at non-digit
            v = v * 10 + (s[i] - '0');
        }
        return v;
    }
    /** @brief Writes the new sequence number safely using a temporary file. */
    static void write(uint32_t v) {
        // Write to temporary file first
        File tmp = SD.open("/seq.tmp", FILE_WRITE);
        if (!tmp) { LOG_PRINTLN("[ERR] Failed open /seq.tmp"); return; }
        tmp.printf("%u\n", (unsigned)v);
        tmp.flush();
        tmp.close();
        // Replace original file with temporary file
        SD.remove(PATH);
        if (!SD.rename("/seq.tmp", PATH)) {
             LOG_PRINTLN("[ERR] Failed rename /seq.tmp");
        }
    }
    /** @brief Reads the last sequence number, increments it, writes back, and returns the new number. */
    static uint32_t next() {
        uint32_t v = read() + 1; // Increment
        write(v);               // Save new value
        g_currentSeqNum = v;    // Update global variable
        return v;
    }
}
/**
 * @brief Generates a unique cycle ID based on MAC address and sequence number.
 * @return Cycle ID String (e.g., "AABBCCDDEEFF-00000001").
 */
static String makeCycleIdNoTime() {
    String devId = deviceIdHex();
    uint32_t seqNum = seq::next(); // Gets the *new* sequence number
    char buf[32];
    sprintf(buf, "%s-%08u", devId.c_str(), (unsigned)seqNum); // Format as MAC-00000000
    return String(buf);
}

/**
 * @brief Main function for the capture sequence. Called once per wake cycle.
 * Applies day/night actions, takes 4 shots (discards 1st), saves 3.
 */
static void beginCapture() {
    LOG_PRINTLN("[STEP] Cycle Start: Capture Sequence");
    g_cycleId = makeCycleIdNoTime(); // Generate the unique ID for this cycle
    g_tBegin = millis();             // Record start time
    g_syslogStartOff = g_syslogBuf.length(); // Mark start of logs for this cycle

    // Apply LED/Motor actions based on current light level
    applyDayNightActions(isNight());

    // --- Capture Loop ---
    // Takes NUM_SHOTS_TOTAL (4), saves NUM_SHOTS_SAVE (3)
    uint8_t savedCount = 0;
    bool captureOk = true;
    for (uint8_t i = 1; i <= param::NUM_SHOTS_TOTAL; ++i) {
        // Determine save index (0 for discard, 1, 2, 3 for saving)
        uint8_t saveIdx = (i == 1) ? 0 : savedCount + 1;
        bool success = shootAndSave(i, saveIdx); // Attempt capture/save

        // Track success only for shots meant to be saved
        if (i > 1) { // If it wasn't the discarded shot
            if (success) {
                savedCount++;
            } else {
                captureOk = false; // Mark the sequence as potentially incomplete
                LOG_PRINTF("[WARN] Failed to save shot for index %u\n", saveIdx);
                // Continue trying remaining shots
            }
        }

        // Delay between shots (except after the last one)
        if (i < param::NUM_SHOTS_TOTAL) {
            delay(param::SHOT_INTERVAL_MS);
        }
    }

    // --- Cleanup after capture ---
    digitalWrite(hw::PIN_FLASH, LOW); // Turn off flash LED
    motorStop();                      // Stop motor

    // Log final status of the capture sequence
    if (captureOk && savedCount == param::NUM_SHOTS_SAVE) {
        LOG_PRINTLN("[STEP] Capture sequence completed successfully.");
    } else {
        LOG_PRINTF("[WARN] Capture sequence incomplete or failed. Saved %d out of %d required shots.\n", savedCount, param::NUM_SHOTS_SAVE);
        // Incomplete cycles will be skipped by the upload logic later
    }
}


/***********************************************************
 * 17.  Setup / Loop
 ***********************************************************/
/**
 * @brief Main setup function, runs once after boot or wake-up.
 */
void setup() {
    Serial.begin(115200);
    delay(500); // Allow Serial Monitor time to connect

    status::begin();
// Start the status LED task
    status::setLed(status::LedState::ON);
// Solid LED indicates booting
    LOG_PRINTLN("\n=== ESP-CAM Boot (Cooldown Version) ===");
    g_tWake = millis();
// Record wake-up time

    // Check wake reason, sleep immediately if it was a cold boot
    configureWakeAndMaybeSleepEarly();
// If code reaches here, wake reason was PIR or Timer

    // --- Initialize Hardware ---
    // Pin Modes
    pinMode(hw::PIN_FLAG, INPUT);
// Wake pin
    pinMode(hw::PIN_FLASH, OUTPUT);    // Flash LED
    pinMode(hw::PIN_MOTOR, OUTPUT);
// Motor IN1
    pinMode(hw::PIN_MOTOR_IN2, OUTPUT); // Motor IN2 (GPIO 3)
    pinMode(hw::PIN_CDS, INPUT);
// CDS Sensor
    // Status LED (GPIO 4) pin mode is set within its task

    // Initial Pin States
    digitalWrite(hw::PIN_FLASH, LOW);
    digitalWrite(hw::PIN_MOTOR, LOW);
    digitalWrite(hw::PIN_MOTOR_IN2, LOW); // Ensure motor is stopped

    // SD Card Initialization
    SPI.begin(hw::SD_SCK, hw::SD_MISO, hw::SD_MOSI, hw::SD_CS);
    g_sdReady = SD.begin(hw::SD_CS); // Attempt to mount SD card
    if (!g_sdReady) {
        LOG_PRINTLN("[FAIL] SD Card Mount Failed! -> Sleeping");
        status::setLed(status::LedState::BLINK_ERROR); // Fast blink indicates error
        delay(3000);
// Show error blink for 3 seconds
        goDeepSleepNow();
// Enter sleep (will skip cooldown)
    }
    elog::ensure();
// Ensure /logs directory exists
    openNewDailyLogFile(); // Prepare the daily log file

    // --- Main Operations ---
    // 1. Initialize Camera
    if (!initCamera()) {
        LOG_PRINTLN("[FAIL] Camera Initialization Failed! -> Sleeping");
        status::setLed(status::LedState::BLINK_ERROR); // Fast blink indicates error
        delay(3000);
        goDeepSleepNow();
    }

    // 2. Perform Capture Sequence (Takes priority)
    status::setLed(status::LedState::BLINK_FAST);
// Fast blink indicates capturing
    beginCapture(); // Takes 4 shots, saves 3 to /archive/[cycleId]
    status::setLed(status::LedState::ON);
// Solid ON indicates capture finished

    // ▼▼▼ ★★★ 修正箇所 (ここから) ★★★ ▼▼▼
    // (goDeepSleepNow から移動)
    // --- Save current cycle log chunk (Moved BEFORE upload attempt) ---
    String logChunk = makeEspLogChunkForCurrentCycle();
    if (logChunk.length() > 0) {
        // Append to the main persistent log (/logs/esp.log)
        updateEspLogAppendRotate(logChunk);
        // Save chunk specifically for this cycle in its archive folder
        if (g_cycleId.length() > 0) { // Only if a capture cycle ran
            String logChunkPath = "/archive/" + g_cycleId + "/esp_chunk.log";
            File file = SD.open(logChunkPath, FILE_WRITE);
            if (file) {
                file.print(logChunk);
                file.close();
                LOG_PRINTF("[SAVE] Saved log chunk (early): %s\n", logChunkPath.c_str());
            } else {
                LOG_PRINTF("[ERR] Failed to save log chunk (early): %s\n", logChunkPath.c_str());
            }
        }
        // Clear memory buffer for next cycle
        g_syslogBuf = "";
        g_syslogStartOff = 0;
    }
    // ▲▲▲ ★★★ 修正箇所 (ここまで) ★★★ ▲▲▲

    // 3. Network Operations (Attempt after capture)
    initWiFi();
// Tries to connect (LED: BLINK_SLOW -> ON or OFF)
    if (WiFi.status() == WL_CONNECTED) {
        loadUploadedList();
// Load upload history from SD
        if (resolvePiHost()) { // Find Pi Server (LED: BLINK_SLOW -> ON)
            uploadPendingData();
// Attempt upload (LED: BLINK_FAST during transfers)
        } else {
             LOG_PRINTLN("[ERR] Failed to resolve Pi host via mDNS.");
// LED remains ON from successful WiFi connection
        }
    } else {
        LOG_PRINTLN("[WIFI] Not connected, skipping mDNS and uploads.");
// LED should be OFF due to initWiFi failure
    }

    // 4. Enter Sleep (includes cooldown)
    LOG_PRINTLN("[STEP] All tasks complete. Entering cooldown then sleep.");
    goDeepSleepNow(); // Saves logs, cleans archive, waits 30s, sets pins, sleeps
}

void loop() {
    // If execution unexpectedly reaches here, log an error and force sleep
    LOG_PRINTLN("[FATAL] Execution reached main loop! This should not happen. Forcing sleep.");
    status::setLed(status::LedState::BLINK_ERROR); // Fast blink indicates error state
    delay(2000); // Show error blink
    goDeepSleepNow();
}