/*
 * XIAO ESP32-S3 Sense: capture -> SD -> SFTP/FTP/HTTP receipt -> PIC shutdown.
 * Per wake: capture 4 JPEG frames (discard first, save up to 3), then connect.
 * Pending archives of every age are retried with a persistent round-robin cursor.
 * Images may be incomplete; edge/cloud finalize partial cycles after a timeout.
 * Only acknowledged archives may be reclaimed when SD free space is low.
 * Logs use monotonic uptime. UTC capture time is estimated from edge time when
 * available during the same boot; historical offline capture times stay unknown.
 */

// =======================================================
// Includes
// =======================================================
#include "esp_bt.h"      // For disabling Bluetooth
#include "esp_camera.h"
#include "freertos/FreeRTOS.h" // For tasks
#include "freertos/task.h"     // For Task Handles
#include "mbedtls/sha256.h"    // For SHA256 hashing
#include <Arduino.h>
#include <ArduinoJson.h> // Though not currently used, kept for potential future use
#include <ESPmDNS.h>     // For mDNS hostname resolution
#include <HTTPClient.h>
#include <SD.h>
#include <SPI.h>
#include <WiFi.h>
#include <algorithm> // C++ STL sort etc.W
#include <cstdarg>   // For variadic functions (LOG_PRINTF)
#include <esp_mac.h> // For MAC address
#include <esp_system.h>
#include <list>   // C++ STL list for managing cycle IDs
#include <string> // C++ STL string for sorting
#include <sys/time.h>
#include <time.h> // For timestamping logs
#include <vector>
#include "transfer_config.h"
#if CAMERA_TRANSFER_MODE == CAMERA_TRANSPORT_SFTP
#include "sftp_transport.h"
// SSH key exchange needs more stack than the default Arduino loop task.
SET_LOOP_TASK_STACK_SIZE(64 * 1024);
#define FILE_TRANSFER_TAG "[SFTP]"
#else
#include "ftp_transport.h"
#define FILE_TRANSFER_TAG "[FTP]"
#endif

// =======================================================
// Hardware Pin Definitions
// =======================================================
#define CAMERA_MODEL_XIAO_ESP32S3
#include "camera_pins.h" // Include the board-specific camera pin definitions

// Forward declarations
static String deviceIdHex();
static bool saveCurrentLogChunkToSD(const char *label);

namespace hw {
constexpr uint8_t SD_CS = 21;      // SD Card Chip Select
constexpr uint8_t SD_MOSI = 9;     // SD Card MOSI
constexpr uint8_t SD_MISO = 8;     // SD Card MISO
constexpr uint8_t SD_SCK = 7;      // SD Card Clock
constexpr uint8_t PIN_SD_PWR = 44; // SD Card Power Control

constexpr uint8_t PIN_DONE = 3;      // PIC microcontroller DONE signal (HIGH = shutdown)
constexpr uint8_t PIN_CDS = 2;       // CDS Light Sensor Input (Analog)
constexpr uint8_t PIN_BATT_SENSE = 4;// 2.1V Battery voltage drop detection
constexpr uint8_t PIN_PIC_IN = 5;    // Input from PIC microcontroller

constexpr uint8_t PIN_FLASH = 6;     // Flash LED (5VA DCDC) Control Output

} // namespace hw

// =======================================================
// Network Configuration
// =======================================================
namespace net {
constexpr char WIFI_SSID[] = "SLAB-g";
constexpr char WIFI_PASS[] = "wakaW1sat0";
constexpr uint32_t WIFI_TIMEOUT =
    30000; // Wi-Fi connection attempt timeout (ms)
constexpr char PI_MDNS_HOST[] =
    "raspberrypi"; // mDNS hostname of your Pi server (e.g., "edge.local")

// These will be populated after mDNS resolution
IPAddress PI_IP;
String PI_HOST;       // Base URL (e.g., "http://192.168.1.10:5000")
String PI_UPLOAD_URL; // Full URL for image uploads
String PI_HEALTHZ;    // Full URL for Pi server health check
String PI_ESPLOG_URL; // Full URL for ESP log chunk uploads

constexpr char HDR_HASH[] =
    "X-Content-SHA256"; // Custom HTTP header for SHA256 content verification
constexpr char API_TOKEN[] = "wild-animals-token-2026"; // Edge Server API Token
} // namespace net

// =======================================================
// Behaviour Parameters
// =======================================================
namespace param {
constexpr uint8_t NUM_SHOTS_TOTAL =
    4; // Total shots to take (1 discard + 3 save)
constexpr uint8_t NUM_SHOTS_SAVE = 3;      // Number of shots to actually save
constexpr uint32_t SHOT_INTERVAL_MS = 500; // Interval between shots (ms)
constexpr int MAX_ARCHIVE_CYCLES =
    100; // Legacy setting; free-space reclamation protects all pending cycles
constexpr uint32_t UPLOAD_BUDGET_MS = 60000; // Bound work per wake cycle
constexpr uint32_t MIN_FREE_SPACE_MB = 30;
} // namespace param

// =======================================================
// Status LED Control (using a dedicated FreeRTOS task)
// =======================================================

// =======================================================
// Global Variables
// =======================================================
static HTTPClient g_http; // Reusable HTTP client instance
String g_cycleId = "";    // ID for the current operation cycle (MAC-Sequence)
uint32_t g_tWake = 0;     // Millis() timestamp when woken up
uint32_t g_tCapStart = 0, g_tCapEnd = 0;       // Capture timings
uint32_t g_tWifiStart = 0, g_tWifiEnd = 0;     // WiFi connection timings
uint32_t g_tUploadStart = 0, g_tUploadEnd = 0; // Upload timings
int32_t g_rssi = 0;                            // SIGNAL STRENGTH (dBm)
uint32_t g_tBegin = 0; // Millis() timestamp when capture/processing started
bool g_uploadBudgetActive = false;
String g_syslogBuf;    // In-memory buffer for logs generated during this cycle
size_t g_syslogStartOff =
    0; // Starting position in syslogBuf for the current cycle's chunk
bool g_sdReady = false; // Flag indicating if SD card is mounted successfully
bool g_piHostResolved =
    false; // Flag indicating if Pi server IP was found via mDNS

std::list<String> g_uploadedCidList; // In-memory list of cycle IDs already
                                     // uploaded successfully
const char *UPLOADED_LIST_PATH =
    "/logs/uploaded_cids.txt"; // Path to store the uploaded list persistently
uint32_t g_currentSeqNum =
    0; // Sequence number of the current cycle (from /seq.txt)

// =======================================================
// Utility Functions
// =======================================================

/**
 * @brief Calculates SHA256 hash of data.
 * @param data Pointer to the data buffer.
 * @param len Length of the data in bytes.
 * @return SHA256 hash as a 64-character lowercase hex String.
 */
static String sha256Hex(const uint8_t *data, size_t len) {
  unsigned char mac[32]; // SHA256 output is 32 bytes
  mbedtls_sha256_context ctx;
  mbedtls_sha256_init(&ctx);
  mbedtls_sha256_starts(&ctx, 0); // 0 indicates SHA256 mode
  mbedtls_sha256_update(&ctx, data, len);
  mbedtls_sha256_finish(&ctx, mac);
  mbedtls_sha256_free(&ctx);
  char hex[65]; // Buffer for 64 hex characters + null terminator
  for (int i = 0; i < 32; i++) {
    sprintf(hex + 2 * i, "%02x",
            mac[i]); // Format each byte as 2 lowercase hex chars
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
static File g_logFile;           // File handle for the daily SD log
static String g_curLogName = ""; // Name of the currently open daily log file

/**
 * @brief Opens the bounded serial log, independent of UTC synchronization.
 */
static void openNewDailyLogFile() {
  time_t now = time(nullptr);
  struct tm tm_info;
  localtime_r(&now, &tm_info);
  char name[32];
  snprintf(name, sizeof(name), "/logs/serial.log");
  String newLogName = name; // Use String for comparison
  if (g_curLogName != newLogName) {
    if (g_logFile) {
      g_logFile.close(); // Close previous day's log if open
    }
    g_curLogName = newLogName;
    File existing = SD.open(g_curLogName, FILE_READ);
    size_t logSize = existing ? existing.size() : 0;
    existing.close();
    if (logSize >= 512 * 1024) {
      SD.remove("/logs/serial.log.1");
      SD.rename(g_curLogName, "/logs/serial.log.1");
    }
    g_logFile = SD.open(g_curLogName, FILE_APPEND); // Open for appending
    if (!g_logFile) {
      // Log error only to Serial as SD write failed
      Serial.printf("[ERR] Failed to open daily log: %s\n",
                    g_curLogName.c_str());
    }
  }
}

/**
 * @brief Logs raw string to Serial, SD card (if open), and memory buffer.
 * @param s The C-style string to log.
 */
static void LOG_RAW(const char *s) {
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
    // Output was truncated, but tmp is still null-terminated safely by
    // vsnprintf
    Serial.println("[WARN] Log message truncated in LOG_PRINTF");
    n = sizeof(tmp) - 1; // n reflects the truncated length
  }
  // tmp is guaranteed to be null-terminated at this point (up to size-1)
  char prefix[32];
  snprintf(prefix, sizeof(prefix), "[uptime=%lu ms] ", (unsigned long)millis());
  LOG_RAW(prefix);
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
const char *DIR = "/logs";         // Directory for logs on SD card
const char *ESP = "/logs/esp.log"; // Path to the main persistent ESP log file
constexpr size_t MAX_LINES =
    2000; // Rotate file when this many lines are exceeded

/** @brief Ensures the log directory exists. */
static void ensure() {
  if (!SD.exists(DIR)) {
    if (!SD.mkdir(DIR)) {
      LOG_PRINTLN("[ERR] Failed to create /logs directory!");
    }
  }
}
/** @brief Counts the number of lines (newlines) in a file. */
static size_t countLines(const char *path) {
  File f = SD.open(path, FILE_READ);
  if (!f)
    return 0;
  size_t lines = 0;
  while (f.available()) {
    if (f.read() == '\n')
      lines++;
  }
  f.close();
  return lines;
}

/** @brief Rotates a log file by renaming it (e.g., esp.log ->
 * esp.log.YYYYMMDD_HHMMSS). */
static void rotate(const char *path) {
  String newPath = String(path) + ".1"; // Bounded retention, independent of wall clock
  LOG_PRINTF("[LOG] Rotating %s -> %s\n", path, newPath.c_str());
  SD.remove(newPath); // Ensure target is clear (unlikely to collide but safe)
  if (!SD.rename(path, newPath)) {
    LOG_PRINTF("[ERR] Failed to rotate log file %s\n", path);
  }
}

/** @brief Appends a string to a log file, performing rotation if necessary. */
static bool appendWithRotate(const char *path, const String &s,
                             size_t max_lines = MAX_LINES) {
  ensure(); // Ensure directory exists

  // Check size and rotate if needed
  if (SD.exists(path)) {
    if (countLines(path) >= max_lines) {
      rotate(path);
    }
  }

  File f = SD.open(path, FILE_APPEND);
  if (f) {
    size_t written = f.print(s);
    f.flush();
    f.close();
    return written == s.length();
  } else {
    // Fallback: try to write to Serial if SD fails
    Serial.printf("[ERR] Failed to append to log %s\n", path);
    return false;
  }
}
} // namespace elog

// =======================================================
// Wi-Fi Connection
// =======================================================
/**
 * @brief Connects the ESP32 to the configured Wi-Fi network (STA mode).
 * Updates status LED during the process.
 */
static void initWiFi() {
  g_tWifiStart = millis(); // Record start of WiFi connection
  LOG_PRINTF("[WIFI] t=%lu ms Connecting to %s (timeout=%lu ms)\n",
             (unsigned long)g_tWifiStart, net::WIFI_SSID,
             (unsigned long)net::WIFI_TIMEOUT);
  WiFi.mode(WIFI_STA);     // Set Wi-Fi mode to Station (client)
  WiFi.begin(net::WIFI_SSID, net::WIFI_PASS); // Start connection attempt

  uint32_t t0 = millis();
  // Wait for connection or timeout
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - t0 > net::WIFI_TIMEOUT) {
      g_tWifiEnd = millis();
      LOG_PRINTF("[WIFI] Connection timeout: status=%d elapsed=%lu ms\n",
                 (int)WiFi.status(),
                 (unsigned long)(g_tWifiEnd - g_tWifiStart));
      return; // Exit if connection timed out
    }
    Serial.print("."); // Visual progress on Serial
    // The LED task handles blinking, just check status periodically
    vTaskDelay(pdMS_TO_TICKS(500));
  }

  // Connected successfully
  LOG_PRINTLN("\n[WIFI] Connected Successfully.");
  LOG_PRINTF("[WIFI] IP Address: %s\n", WiFi.localIP().toString().c_str());
  g_rssi = WiFi.RSSI();
  LOG_PRINTF("[WIFI] Signal Strength (RSSI): %d dBm\n", g_rssi);
  g_tWifiEnd = millis(); // Record end of WiFi connection
  LOG_PRINTF("[WIFI] Connected: BSSID=%s channel=%d elapsed=%lu ms\n",
             WiFi.BSSIDstr().c_str(), WiFi.channel(),
             (unsigned long)(g_tWifiEnd - g_tWifiStart));
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
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 10000000;       // Camera clock frequency
  config.frame_size = FRAMESIZE_UXGA;   // Resolution (1600x1200)
  config.pixel_format = PIXFORMAT_JPEG; // Output format
  config.jpeg_quality = 12; // JPEG quality (0-63, lower is higher quality but
                            // larger size) - 12 is reasonable
  config.fb_count = 2; // Number of frame buffers (Increased to 2 for stability)
  config.fb_location = CAMERA_FB_IN_PSRAM; // Use PSRAM for frame buffer
  config.grab_mode =
      CAMERA_GRAB_LATEST; // Grab the latest frame, discard older ones

  // Initialize the camera
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    LOG_PRINTF("[ERR] Camera initialization failed with error 0x%x\n", err);
    return false;
  }

  // Optional: Get sensor object to configure settings like V-Flip, brightness
  // etc. sensor_t * s = esp_camera_sensor_get(); s->set_vflip(s, 1);       //
  // Example: Flip camera image vertically s->set_brightness(s, 0); // Example:
  // Set brightness (-2 to 2)

  return true; // Success
}

/**
 * @brief Powers down camera pins to reduce leakage during deep sleep/light
 * sleep.
 */
static void powerDownCameraPins() {
  LOG_PRINTLN("[PWR ] Powering down camera pins...");

// 1. If PWDN pin is available, assert it (High usually powers down)
#if defined(PWDN_GPIO_NUM) && PWDN_GPIO_NUM != -1
  pinMode(PWDN_GPIO_NUM, OUTPUT);
  digitalWrite(PWDN_GPIO_NUM, HIGH);
#endif

  // 2. Set data and control pins to INPUT_PULLDOWN to prevent floating/leakage
  // Array of pins to disable
  int camPins[] = {Y2_GPIO_NUM,   Y3_GPIO_NUM,   Y4_GPIO_NUM,    Y5_GPIO_NUM,
                   Y6_GPIO_NUM,   Y7_GPIO_NUM,   Y8_GPIO_NUM,    Y9_GPIO_NUM,
                   XCLK_GPIO_NUM, PCLK_GPIO_NUM, VSYNC_GPIO_NUM, HREF_GPIO_NUM,
                   SIOD_GPIO_NUM, SIOC_GPIO_NUM};

  for (int pin : camPins) {
    if (pin != -1) {
      pinMode(pin, INPUT_PULLDOWN);
    }
  }

// RESET pin - usually active low, so keeping it low might hold it in reset?
// Or just set to input to float/weak pull.
// For now, let's treat it like others.
#if defined(RESET_GPIO_NUM) && RESET_GPIO_NUM != -1
  pinMode(RESET_GPIO_NUM, INPUT_PULLDOWN);
#endif

  LOG_PRINTLN("[PWR ] Camera pins powered down.");
}

/**
 * @brief Powers down SD card pins to reduce leakage.
 */
static void powerDownSdCardPins() {
  LOG_PRINTLN("[PWR ] Powering down SD card pins...");
  if (g_sdReady) {
    saveCurrentLogChunkToSD("shutdown");
    if (g_logFile) {
      g_logFile.flush();
      g_logFile.close();
    }
    SD.end();
    g_sdReady = false;
  }
  pinMode(hw::PIN_SD_PWR, OUTPUT);
  digitalWrite(hw::PIN_SD_PWR, LOW);
  // CSピン（Chip
  // Select）はLOWに引っ張るとSDカードがアクティブになり電力を消費するため、PULLUPにします
  pinMode(hw::SD_CS, INPUT_PULLUP);
  int otherSdPins[] = {hw::SD_MOSI, hw::SD_MISO, hw::SD_SCK};
  for (int pin : otherSdPins) {
    pinMode(pin, INPUT_PULLDOWN);
  }
  LOG_PRINTLN("[PWR ] SD card pins powered down.");
}

/**
 * @brief Captures an image, discards if it's the first, saves otherwise.
 * @param captureIndex The index of this capture in the sequence (1-based).
 * @param saveIndex The index to use for saving the file (1-based, 0 if
 * discard).
 * @param night True if it is night mode, False for day.
 * @return True if capture and save (or discard) were successful, False on
 * error.
 */
static bool shootAndSave(uint8_t captureIndex, uint8_t saveIndex, bool night) {
  camera_fb_t *fb = esp_camera_fb_get(); // Get frame buffer

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
    return true;              // Indicate success for the sequence step
  }

  // --- Save Logic ---
  String cycleDir = "/archive/" + g_cycleId; // Path to cycle directory
  // Create directory only when saving the first *valid* image (saveIndex == 1)
  if (saveIndex == 1) {
    if (!SD.exists("/archive")) {
      if (!SD.mkdir("/archive")) {
        LOG_PRINTLN("[ERR] Failed to create /archive directory!");
        esp_camera_fb_return(fb);
        return false;
      }
    }
    if (!SD.exists(cycleDir)) {
      if (!SD.mkdir(cycleDir)) {
        LOG_PRINTF("[ERR] Failed to create cycle directory %s\n",
                   cycleDir.c_str());
        esp_camera_fb_return(fb);
        return false;
      }
    }
  }

  char path[128]; // Buffer for file path
  char suffix = night ? 'n' : 'd';
  // New naming: {CycleID}-{Index}{n/d}.jpg
  sprintf(path, "%s/%s-%u%c.jpg", cycleDir.c_str(), g_cycleId.c_str(),
          saveIndex, suffix);

  File file = SD.open(path, FILE_WRITE); // Open file for writing
  bool success = false;
  if (file) {
    size_t written = file.write(fb->buf, fb->len); // Write frame buffer content
    file.close();                                  // Close file immediately
    if (written == fb->len) {
      LOG_PRINTF("[SAVE] %s (%u bytes, Cap #%u)\n", path, fb->len,
                 captureIndex);
      success = true;
    } else {
      // Write failed or incomplete
      LOG_PRINTF("[ERR] Failed to write complete file %s (%u/%u bytes)\n", path,
                 written, fb->len);
      SD.remove(path); // Delete incomplete file
    }
  } else {
    LOG_PRINTF("[ERR] Failed to open file for writing: %s\n", path);
  }

  esp_camera_fb_return(fb); // IMPORTANT: Always return the frame buffer
  return success;
}

// =======================================================
// Pi Server Interaction (Upload Logic)
// =======================================================

/**
 * @brief Loads the list of successfully uploaded cycle IDs from the SD card
 * file.
 */
static void loadUploadedList() {
  g_uploadedCidList.clear(); // Clear the in-memory list first
  File file = SD.open(UPLOADED_LIST_PATH, FILE_READ);
  if (!file) {
    LOG_PRINTLN(
        "[UPLOAD] Uploaded list file not found. Assuming none uploaded.");
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
  LOG_PRINTF("[UPLOAD] Loaded %d previously uploaded CIDs from list.\n",
             g_uploadedCidList.size());
}

/**
 * @brief Checks if a given cycle ID is present in the in-memory uploaded list.
 * @param cid The cycle ID String to check.
 * @return True if the ID exists in the list, False otherwise.
 */
static bool isCidUploaded(const String &cid) {
  // Iterate through the list to find a match
  for (const String &uploadedCid : g_uploadedCidList) {
    if (uploadedCid == cid) {
      return true;
    }
  }
  return false; // Not found
}

/**
 * @brief Marks a cycle ID as successfully uploaded by adding it to the list
 * (memory and file).
 * @param cid The cycle ID String to mark.
 */
static void markAsUploaded(const String &cid) {
  if (isCidUploaded(cid)) {
    return; // Already marked, do nothing
  }

  // Append the new CID to the file on the SD card
  File file = SD.open(UPLOADED_LIST_PATH, FILE_APPEND);
  if (!file) {
    LOG_PRINTLN("[ERR] Failed to open upload list file for appending!");
    // Potential issue: list in memory and file are now out of sync
    return;
  }
  size_t written = file.println(cid);
  file.flush();
  file.close();
  if (written != cid.length() + 2) {
    LOG_PRINTLN("[ERR] Upload history write failed; will retry next boot.");
    return;
  }
  g_uploadedCidList.push_back(cid);
  LOG_PRINTF("[UPLOAD] Marked cycle %s as uploaded.\n", cid.c_str());
}

/**
 * @brief Resolves the Pi server's IP address using mDNS.
 * Updates global network strings if successful.
 * @return True if resolution is successful, False otherwise.
 */
static bool resolvePiHost() {
  const uint32_t started = millis();
  if (WiFi.status() != WL_CONNECTED) {
    LOG_PRINTLN("[mDNS] Wi-Fi not connected, cannot resolve host.");
    return false;
  }
  LOG_PRINTF("[mDNS] t=%lu ms Resolving host: %s.local (timeout=5000 ms)\n",
             (unsigned long)started, net::PI_MDNS_HOST);

  // Start mDNS (use a unique hostname for the ESP itself if needed)
  String myHostname = "esp32-cam-" + deviceIdHex();
  if (!MDNS.begin(myHostname.c_str())) { // Hostname for this ESP device
    LOG_PRINTLN("[ERR] Failed to start mDNS responder.");
    return false;
  }
  LOG_PRINTF("[mDNS] My hostname: %s.local\n", myHostname.c_str());

  // Query for the Pi server's hostname with a timeout
  IPAddress piIP = MDNS.queryHost(net::PI_MDNS_HOST, 5000); // 5-second timeout

  MDNS.end(); // Stop mDNS service after query

  // Check if a valid IP address was returned
  if (piIP == IPAddress(255, 255, 255, 255) || piIP[0] == 0) {
    LOG_PRINTF("[mDNS] Host not found: elapsed=%lu ms wifi_status=%d\n",
               (unsigned long)(millis() - started), (int)WiFi.status());
    g_piHostResolved = false;
    return false;
  }

  // Success! Store the resolved IP and construct full URLs
  LOG_PRINTF("[mDNS] Host found: IP=%s elapsed=%lu ms\n",
             piIP.toString().c_str(), (unsigned long)(millis() - started));
  String hostBase = "http://" + piIP.toString() +
                    ":8000"; // Assuming Pi server runs on port 8000
  net::PI_IP = piIP;
  net::PI_HOST = hostBase;
  net::PI_UPLOAD_URL = hostBase + "/upload";
  net::PI_HEALTHZ = hostBase + "/healthz";
  net::PI_ESPLOG_URL = hostBase + "/esp_log";
  g_piHostResolved = true;
  return true;
}

#if CAMERA_TRANSFER_MODE == CAMERA_TRANSPORT_SFTP
static CameraSftpClient g_fileTransfer;
#else
static CameraFtpClient g_fileTransfer;
#endif

static void syncCaptureClock(time_t epoch) {
  if (epoch <= 1700000000) return;
  timeval tv = {epoch, 0};
  settimeofday(&tv, nullptr);
  if (g_cycleId.length()) {
    File stamp = SD.open("/archive/" + g_cycleId + "/captured_at.txt", FILE_WRITE);
    if (stamp) {
      stamp.printf("%lld\n", (long long)(epoch-(millis()-g_tCapStart)/1000));
      stamp.close();
    }
  }
  LOG_PRINTF("[TIME] Edge UTC=%lld; capture UTC estimated from uptime.\n", (long long)epoch);
}

static bool connectFileTransfer() {
  if (g_fileTransfer.connected()) return true;
#if CAMERA_TRANSFER_MODE == CAMERA_TRANSPORT_SFTP
  bool ok = g_fileTransfer.begin(net::PI_IP, CAMERA_SFTP_PORT, CAMERA_SFTP_USER,
                        CAMERA_SFTP_HOST_FINGERPRINT, CAMERA_SFTP_KEY_PATH,
                        CAMERA_SFTP_KEY_PASSPHRASE, CAMERA_SFTP_REMOTE_ROOT,
                        g_tUploadStart, param::UPLOAD_BUDGET_MS);
  LOG_PRINTF("[SFTP] Connection/auth %s (port=%u free_heap=%u detail=%s)\n",
             ok ? "OK" : "FAILED", CAMERA_SFTP_PORT, ESP.getFreeHeap(), g_fileTransfer.error());
#else
  bool ok = g_fileTransfer.begin(net::PI_IP, CAMERA_FTP_PORT, CAMERA_FTP_USER,
                        CAMERA_FTP_PASSWORD, g_tUploadStart, param::UPLOAD_BUDGET_MS);
  LOG_PRINTF("[FTP] Connection/login %s (port=%u)\n", ok ? "OK" : "FAILED", CAMERA_FTP_PORT);
#endif
  return ok;
}

static bool uploadTransferFile(const String &path, const String &cycleId, int imgIdx) {
  if (!connectFileTransfer()) return false;
  const uint32_t started = millis();
  File file = SD.open(path, FILE_READ);
  if (!file || !file.size()) { file.close(); return false; }
  size_t size = file.size(), hashed = 0;
  uint8_t buffer[2048], hash[32];
  mbedtls_sha256_context ctx;
  mbedtls_sha256_init(&ctx);
  mbedtls_sha256_starts(&ctx, 0);
  while (hashed < size && millis()-g_tUploadStart < param::UPLOAD_BUDGET_MS) {
    int count = file.read(buffer, sizeof(buffer));
    if (count <= 0) break;
    mbedtls_sha256_update(&ctx, buffer, count);
    hashed += count;
  }
  mbedtls_sha256_finish(&ctx, hash);
  mbedtls_sha256_free(&ctx);
  if (hashed != size || !file.seek(0)) { file.close(); return false; }
  char hex[65], token[33];
  for (int i = 0; i < 32; i++) sprintf(hex+2*i, "%02x", hash[i]);
  hex[64] = '\0';
  snprintf(token, sizeof(token), "%08lx%08lx%08lx%08lx",
           (unsigned long)esp_random(), (unsigned long)esp_random(),
           (unsigned long)esp_random(), (unsigned long)esp_random());
  String base = String("incoming/") + token;
  JsonDocument manifest;
  manifest["version"] = 1;
  manifest["kind"] = imgIdx > 0 ? "image" : "log";
  manifest["filename"] = path.substring(path.lastIndexOf('/')+1);
  manifest["cycle_id"] = cycleId;
  manifest["image_index"] = imgIdx;
  manifest["size"] = size;
  manifest["sha256"] = hex;
  File captured = SD.open("/archive/" + cycleId + "/captured_at.txt", FILE_READ);
  if (captured) {
    String epoch = captured.readStringUntil('\n');
    epoch.trim();
    if (epoch.length()) manifest["captured_at"] = epoch;
    captured.close();
  }
  String body;
  serializeJson(manifest, body);
  LOG_PRINTF(FILE_TRANSFER_TAG " Sending cid=%s image=%d bytes=%lu\n", cycleId.c_str(), imgIdx, (unsigned long)size);
  bool sent = g_fileTransfer.putFile(base+".data.part", file);
  file.close();
  sent = sent && g_fileTransfer.renameFile(base+".data.part", base+".data") &&
         g_fileTransfer.putText(base+".json.part", body) && g_fileTransfer.renameFile(base+".json.part", base+".ready");
  if (!sent) { g_fileTransfer.close(); LOG_PRINTLN(FILE_TRANSFER_TAG " Transfer failed; retained on SD."); return false; }
  uint32_t pollStart = millis();
  while (g_fileTransfer.connected() && millis()-pollStart < 15000) {
    String response;
    if (g_fileTransfer.getText(String("receipts/")+token+".json", response)) {
      JsonDocument receipt;
      bool ok = !deserializeJson(receipt, response) && String(receipt["status"] | "") == "ok" &&
                String(receipt["sha256"] | "") == hex;
      String expected = imgIdx > 0 ? cycleId+":"+String(imgIdx) : String("log:")+hex;
      ok = ok && String(receipt["receipt_id"] | "") == expected;
      LOG_PRINTF(FILE_TRANSFER_TAG " Receipt %s cid=%s image=%d elapsed=%lu ms\n", ok ? "OK" : "REJECTED",
                 cycleId.c_str(), imgIdx, (unsigned long)(millis()-started));
      return ok;
    }
    delay(250);
  }
  LOG_PRINTLN(FILE_TRANSFER_TAG " Application receipt timed out; retained on SD.");
  return false;
}

/**
 * @brief Uploads a single file using the configured SFTP, FTP or HTTP transport.
 * @param url The full URL endpoint on the Pi server.
 * @param path The path to the file on the ESP32's SD card.
 * @param ctype The Content-Type header value (e.g., "image/jpeg").
 * @param cycleId The cycle ID associated with this file.
 * @param imgIdx The image index (1, 2, or 3) if applicable, 0 otherwise (for
 * log file).
 * @return True only after receiving a matching application receipt.
 */
static bool uploadFile(const String &url, const String &path, const char *ctype,
                       const String &cycleId, int imgIdx) {
  if (CAMERA_TRANSFER_MODE != CAMERA_TRANSPORT_HTTP) return uploadTransferFile(path, cycleId, imgIdx);
  if (g_uploadBudgetActive && millis() - g_tUploadStart >= param::UPLOAD_BUDGET_MS) {
    LOG_PRINTLN("[UPLOAD] Wake-cycle transfer budget exhausted.");
    return false;
  }
  File file = SD.open(path, FILE_READ);

  // Check if file opened successfully
  if (!file) {
    LOG_PRINTF("[ERR] Upload: File not found %s\n", path.c_str());
    return false;
  }
  // Check if file is empty
  size_t fileSize = file.size();
  if (fileSize == 0) {
    LOG_PRINTF("[WARN] Upload: Skipping empty file %s\n", path.c_str());
    file.close();
    return false; // Empty files are not durable image receipts.
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
    // Extract filename from path for X-File-Name header
    int lastSlash = path.lastIndexOf('/');
    String fname = (lastSlash != -1) ? path.substring(lastSlash + 1) : path;
    httpClient.addHeader("X-File-Name", fname);

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
    for (int i = 0; i < 32; i++)
      sprintf(hexHash + 2 * i, "%02x", hashResult[i]);
    hexHash[64] = '\0';

    if (!file.seek(0)) {
      file.close();
      httpClient.end();
      return false;
    }
    File captured = SD.open("/archive/" + cycleId + "/captured_at.txt", FILE_READ);
    if (captured) {
      String epoch = captured.readStringUntil('\n');
      epoch.trim();
      if (epoch.length() > 0) httpClient.addHeader("X-Captured-At", epoch);
      captured.close();
    }
    httpClient.addHeader(net::HDR_HASH, String(hexHash)); // Add hash header
    httpClient.addHeader("X-API-KEY", net::API_TOKEN);    // Add API Auth Header
    uint32_t elapsed = millis() - g_tUploadStart;
    if (g_uploadBudgetActive && elapsed >= param::UPLOAD_BUDGET_MS) {
      file.close();
      httpClient.end();
      return false;
    }
    uint32_t remaining = g_uploadBudgetActive ? param::UPLOAD_BUDGET_MS - elapsed : 15000;
    uint32_t timeout = remaining < 15000 ? remaining : 15000;
    httpClient.setTimeout(timeout);
    httpClient.setConnectTimeout(timeout < 5000 ? timeout : 5000);

    // Send the POST request with the file stream and size
    const uint32_t started = millis();
    LOG_PRINTF("[HTTP] t=%lu ms POST %s cid=%s image=%d bytes=%lu\n",
               (unsigned long)started, url.c_str(), cycleId.c_str(), imgIdx,
               (unsigned long)fileSize);
    int httpCode = httpClient.sendRequest("POST", &file, fileSize);
    LOG_PRINTF("[HTTP] POST result=%d elapsed=%lu ms wifi_status=%d rssi=%d dBm\n",
               httpCode, (unsigned long)(millis() - started),
               (int)WiFi.status(), (int)WiFi.RSSI());

    // Check response code
    if (httpCode == HTTP_CODE_OK) {
      JsonDocument receipt;
      DeserializationError error = deserializeJson(receipt, httpClient.getString());
      success = !error && String(receipt["status"] | "") == "ok" &&
                String(receipt["sha256"] | "") == hexHash;
      if (imgIdx > 0) {
        success = success && String(receipt["receipt_id"] | "") == cycleId + ":" + String(imgIdx);
      }
      LOG_PRINTF("[UPLOAD] Receipt %s: %s -> %d\n",
                 success ? "confirmed" : "INVALID", path.c_str(), httpCode);
    } else {
      // Log error with HTTP code and potentially response body
      LOG_PRINTF("[ERR] Upload Failed: %s -> %d (%s)\n", path.c_str(), httpCode,
                 httpClient.errorToString(httpCode).c_str());
      // String responseBody = httpClient.getString(); // Uncomment to see
      // server response LOG_PRINTF("Response: %s\n", responseBody.c_str());
    }
    httpClient.end(); // End the connection
  } else {
    LOG_PRINTF("[ERR] HTTPClient begin failed for URL: %s\n", url.c_str());
  }

  file.close(); // Ensure file is closed
  return success;
}

/**
 * @brief Extracts the sequence number from a cycle ID string (e.g.,
 * "MAC-00000005" -> 5).
 * @param cid The cycle ID String.
 * @return The sequence number as a long, or -1 if parsing fails.
 */
long getSeqNumFromCid(const String &cid) {
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
  } catch (const std::invalid_argument &ia) {
    LOG_PRINTF("[ERR] Invalid sequence number string: %s\n", seqStr.c_str());
    return -1;
  } catch (const std::out_of_range &oor) {
    LOG_PRINTLN("[ERR] Sequence number out of range.");
    return -1;
  }
  // Fallback using Arduino String toInt() if std::stol fails compilation (less
  // safe) long seqNum = seqStr.toInt(); return (seqNum == 0 && seqStr != "0") ?
  // -1 : seqNum; // Basic check if toInt failed
}

// --- Archive Cleanup Helpers ---
/** @brief Comparator struct for sorting cycle ID strings numerically by
 * sequence number. */
struct CidComparator {
  bool operator()(const String &a, const String &b) const {
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
/** @brief Lists directories inside a given path, sorted by cycle ID sequence
 * number. */
static std::list<String> listCycleDirs(const char *dirPath) {
  std::list<String> dirs;
  File root = SD.open(dirPath);
  if (!root) {
    LOG_PRINTF("[ERR] Cannot open directory: %s\n", dirPath);
    return dirs;
  }
  if (!root.isDirectory()) {
    LOG_PRINTF("[ERR] Not a directory: %s\n", dirPath);
    root.close();
    return dirs;
  }

  File file;
  while (file = root.openNextFile()) {
    if (file.isDirectory()) {
      String dirName = file.name();
      // Extract just the directory name from full path if needed
      int lastSlash = dirName.lastIndexOf('/');
      if (lastSlash != -1)
        dirName = dirName.substring(lastSlash + 1);
      // Add to list only if it looks like a valid Cycle ID
      if (getSeqNumFromCid(dirName) != -1) {
        dirs.push_back(dirName);
      } else {
        LOG_PRINTF("[WARN] listCycleDirs: Skipping non-CID directory: %s\n",
                   dirName.c_str());
      }
    }
    file.close(); // Important: close file handle
  }
  root.close();               // Close directory handle
  dirs.sort(CidComparator()); // Sort the list using the custom comparator
  return dirs;
}

/**
 * @brief
 * 最新のサイクルから順にスキャンし、未送信のものを最大3件までアップロードする。
 */
static void uploadPendingData() {
  g_tUploadStart = millis(); // Record start of upload
  if (!g_piHostResolved) {
    LOG_PRINTLN("[UPLOAD] Pi host not resolved, skip.");
    return;
  }

  bool piOk = false;
  if (CAMERA_TRANSFER_MODE != CAMERA_TRANSPORT_HTTP) {
    piOk = connectFileTransfer();
    if (piOk) {
      String response;
      if (g_fileTransfer.getText("status.json", response)) {
        JsonDocument status;
        if (!deserializeJson(status, response)) {
          piOk = String(status["status"] | "") == "ok";
          if (piOk) syncCaptureClock(status["utc_epoch"] | 0L);
        }
      }
      // If status.json is not published yet, each file still requires a durable receipt.
    }
  } else {
    HTTPClient health;
    health.setTimeout(3000);
    health.setConnectTimeout(3000);
    if (health.begin(net::PI_HEALTHZ)) {
      int code = health.GET();
      LOG_PRINTF("[HTTP] Health result=%d\n", code);
      if (code == HTTP_CODE_OK) {
        JsonDocument status;
        if (!deserializeJson(status, health.getString()) && String(status["status"] | "") == "ok") {
          piOk = true;
          syncCaptureClock(status["utc_epoch"] | 0L);
        }
      }
      health.end();
    }
  }
  if (!piOk) { g_fileTransfer.close(); return; }
  g_uploadBudgetActive = true;

  LOG_PRINTLN("[UPLOAD] Pi server OK. Resuming round-robin scan of all pending archives.");
  std::list<String> cycleDirs = listCycleDirs("/archive");
  File cursorFile = SD.open("/logs/retry_cursor.txt", FILE_READ);
  if (cursorFile && !cycleDirs.empty()) {
    String cursor = cursorFile.readStringUntil('\n');
    cursor.trim();
    long cursorSeq = getSeqNumFromCid(cursor);
    auto next = cycleDirs.begin();
    while (next != cycleDirs.end() && getSeqNumFromCid(*next) <= cursorSeq) ++next;
    if (next != cycleDirs.end()) cycleDirs.splice(cycleDirs.end(), cycleDirs, cycleDirs.begin(), next);
  }
  cursorFile.close();
  int uploadCount = 0;
  int attemptedCount = 0;
  const int MAX_UPLOADS_LIMIT = 3;
  for (const String &cid : cycleDirs) {
    if (attemptedCount >= MAX_UPLOADS_LIMIT || millis()-g_tUploadStart >= param::UPLOAD_BUDGET_MS)
      break;
    if (isCidUploaded(cid)) continue;
    long cycleSeq = getSeqNumFromCid(cid);
    if (cycleSeq == -1) continue;

    // C. ファイルが揃っているかチェック
    // Naming: {CID}-{1~3}{n|d}.jpg
    // We check for both 'n' and 'd' variants.
    String p1 = "", p2 = "", p3 = "";

    String p1n = "/archive/" + cid + "/" + cid + "-1n.jpg";
    String p1d = "/archive/" + cid + "/" + cid + "-1d.jpg";
    if (SD.exists(p1n))
      p1 = p1n;
    else if (SD.exists(p1d))
      p1 = p1d;

    String p2n = "/archive/" + cid + "/" + cid + "-2n.jpg";
    String p2d = "/archive/" + cid + "/" + cid + "-2d.jpg";
    if (SD.exists(p2n))
      p2 = p2n;
    else if (SD.exists(p2d))
      p2 = p2d;

    String p3n = "/archive/" + cid + "/" + cid + "-3n.jpg";
    String p3d = "/archive/" + cid + "/" + cid + "-3d.jpg";
    if (SD.exists(p3n))
      p3 = p3n;
    else if (SD.exists(p3d))
      p3 = p3d;

    String pLog = "/archive/" + cid + "/esp_chunk.log";

    if ((p1 == "" && p2 == "" && p3 == "") || !SD.exists(pLog)) {
      LOG_PRINTF("[UPLOAD] No sendable images/log in cycle: %s\n", cid.c_str());
      continue;
    }
    attemptedCount++;
    File nextCursor = SD.open("/logs/retry_cursor.txt", FILE_WRITE);
    if (nextCursor) { nextCursor.println(cid); nextCursor.close(); }

    // --- アップロード実行 ---
    LOG_PRINTF("[UPLOAD] Uploading %s (seq %ld)...\n", cid.c_str(), cycleSeq);

    bool ok1 = p1 == "" || uploadFile(net::PI_UPLOAD_URL, p1, "image/jpeg", cid, 1);
    bool ok2 = p2 == "" || uploadFile(net::PI_UPLOAD_URL, p2, "image/jpeg", cid, 2);
    bool ok3 = p3 == "" || uploadFile(net::PI_UPLOAD_URL, p3, "image/jpeg", cid, 3);
    // Include Wi-Fi, mDNS, health check and image transfer results in the
    // current cycle's uploaded log. Close the writer before hashing/sending.
    // The log upload's own result is saved locally by the final checkpoint.
    bool logReady = cid != g_cycleId || saveCurrentLogChunkToSD("before_log_upload");
    bool okLog = logReady && uploadFile(net::PI_ESPLOG_URL, pLog, "text/plain", cid, 0);

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
  g_fileTransfer.close();
  g_uploadBudgetActive = false;
  g_tUploadEnd = millis(); // Record end of upload
}

/***********************************************************
 * 12.  Cycle / Logging chunks
 ***********************************************************/
/**
 * @brief Extracts the log messages generated during the current cycle from the
 * memory buffer.
 * @return String containing the log chunk for the current cycle, or empty
 * String if none.
 */
static String makeEspLogChunkForCurrentCycle() {
  String slice = "";
  if (g_syslogBuf.length() > g_syslogStartOff) {
    slice = g_syslogBuf.substring(g_syslogStartOff);
  }
  if (slice.length() == 0)
    return ""; // No new logs

  // Add header and ensure trailing newline
  String header = "[CYCLE] cid=" + g_cycleId + "\n";
  if (!slice.endsWith("\n"))
    slice += "\n";
  return header + slice;
}
/**
 * @brief Appends a chunk of log data to the main persistent log file
 * (/logs/esp.log) with rotation.
 * @param chunk The log chunk String to append.
 */
static bool updateEspLogAppendRotate(const String &chunk) {
  if (chunk.length() == 0) return true;
  return elog::appendWithRotate(elog::ESP, chunk, elog::MAX_LINES);
}

/**
 * @brief Saves the current log chunk to SD card and clears the memory buffer.
 * @param label A label indicating when the log was saved (e.g., "early", "final").
 */
static bool saveCurrentLogChunkToSD(const char* label) {
  if (!g_sdReady) return false;
  size_t checkpoint = g_syslogBuf.length();
  String chunk = makeEspLogChunkForCurrentCycle();
  if (!chunk.length()) return true;
  bool saved = updateEspLogAppendRotate(chunk);
  if (g_cycleId.length()) {
    File file = SD.open("/archive/" + g_cycleId + "/esp_chunk.log", FILE_APPEND);
    if (file) {
      size_t written = file.print(chunk);
      file.flush();
      file.close();
      saved = saved && written == chunk.length();
    } else {
      saved = false;
    }
  }
  if (saved) {
    // Preserve messages emitted by the logging/rotation code after the snapshot.
    g_syslogBuf.remove(0, checkpoint);
    g_syslogStartOff = 0;
  }
  LOG_PRINTF("[SAVE] Log checkpoint %s: %s\n", label, saved ? "saved" : "FAILED, retaining buffer");
  return saved;
}

/***********************************************************
 * 14.  Light (CDS) & Motor Control
 ***********************************************************/
namespace lux {
constexpr int THRESH = 2800;
} // namespace lux

/** @brief Reads CDS sensor and determines if it's currently night. */
static bool isNight() {
  int v = analogRead(hw::PIN_CDS); // Read analog value (0-4095)
  bool night = (v < lux::THRESH);
  LOG_PRINTF("[LUX ] CDS Pin=%u, Value=%d, Threshold=%d -> %s\n", hw::PIN_CDS,
             v, lux::THRESH, night ? "NIGHT" : "DAY");
  return night;
}

// Configuration for Day/Night actions
namespace daynight {
constexpr bool LED_ON_AT_NIGHT = true; // Turn flash ON at night
constexpr bool LED_ON_AT_DAY = false;  // Turn flash OFF during day
} // namespace daynight

/** @brief Activates LED based on the isNight() status. */
static void applyDayNightActions(bool night) {
  // Control Flash LED
  bool ledOn = night ? daynight::LED_ON_AT_NIGHT : daynight::LED_ON_AT_DAY;
  digitalWrite(hw::PIN_FLASH, ledOn ? HIGH : LOW);
  LOG_PRINTF("[LED ] Flash %s\n", ledOn ? "ON" : "OFF");
}

/** @brief Recursively removes a directory and all its contents. Use with
 * caution! */
static bool removeDirRecursive(const String &path) {
  File dir = SD.open(path);
  if (!dir) {
    LOG_PRINTF("[ERR] GC: Cannot open directory to remove: %s\n", path.c_str());
    return false;
  }
  if (!dir.isDirectory()) { // If it's a file, just remove it
    dir.close();
    return SD.remove(path);
  }

  File file;
  bool success = true;
  // Iterate through directory contents
  while (file = dir.openNextFile()) {
    String name = file.name();
    int slash = name.lastIndexOf('/');
    if (slash >= 0) name = name.substring(slash + 1);
    String filePath = path + "/" + name;
    bool isDirectory = file.isDirectory();
    file.close();
    if (isDirectory) {
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
      LOG_PRINTF("[ERR] GC: Failed to remove directory itself: %s\n",
                 path.c_str());
      success = false;
    }
  }
  return success;
}
/** @brief Cleans up oldest archive directories if count exceeds
 * MAX_ARCHIVE_CYCLES. */
static void cleanupOldArchives() {
  LOG_PRINTLN("[GC] Checking free space...");

  // 1. しきい値をバイト単位に変換
  const uint64_t MIN_FREE_BYTES =
      (uint64_t)param::MIN_FREE_SPACE_MB * 1024 * 1024;

  // 2. SDカードの現在の空き容量を計算
  // (SD.totalBytes() や SD.usedBytes() は時間がかかる場合があります)
  uint64_t totalBytes = SD.totalBytes();
  uint64_t usedBytes = SD.usedBytes();

  // オーバーフロー防止 (あり得ないが念のため)
  if (usedBytes > totalBytes) {
    usedBytes = totalBytes;
  }

  uint64_t freeBytes = totalBytes - usedBytes;
  uint64_t freeMB = freeBytes / (1024 * 1024);

  // 3. 空き容量がしきい値を上回っているかチェック
  if (freeBytes >= MIN_FREE_BYTES) {
    LOG_PRINTF("[GC] Free space OK (%llu MB free, Threshold: %u MB). No "
               "cleanup needed.\n",
               freeMB, param::MIN_FREE_SPACE_MB);
    return; // 十分な空きがあるので何もしない
  }

  // 4. 空き容量が不足しているため、クリーンアップを開始
  LOG_PRINTF("[GC] Free space LOW (%llu MB free, Threshold: %u MB). Starting "
             "cleanup...\n",
             freeMB, param::MIN_FREE_SPACE_MB);

  std::list<String> cycleDirs = listCycleDirs("/archive"); //
  if (cycleDirs.empty()) {
    LOG_PRINTLN(
        "[GC] Archive is empty, but free space is still low. Cannot cleanup.");
    return; // 削除対象がない
  }

  int removedCount = 0;
  bool spaceFreed = false; // 容量が確保できたか

  // 5. 古いもの (リストの先頭) から順に削除するループ
  for (const String &oldestCid : cycleDirs) {
    if (!isCidUploaded(oldestCid) || oldestCid == g_cycleId) continue;
    String dirPath = "/archive/" + oldestCid;
    LOG_PRINTF("[GC] Removing old cycle: %s\n", dirPath.c_str());

    if (removeDirRecursive(dirPath)) { // [cite: 328]
      // ディレクトリ削除成功
      removedCount++;
      g_uploadedCidList.remove(
          oldestCid); // [cite: 349] メモリ上のアップロード履歴からも削除

      // 6. 削除後に再度、空き容量をチェック
      // (注: 毎回 usedBytes を呼ぶのは高コストですが確実です)
      freeBytes = SD.totalBytes() - SD.usedBytes();

      if (freeBytes >= MIN_FREE_BYTES) {
        // しきい値を超える空き容量を確保できた
        spaceFreed = true;
        LOG_PRINTF("[GC] Successfully freed space. New free space: %llu MB.\n",
                   freeBytes / (1024 * 1024));
        break; // 削除ループを終了
      }
      // まだ足りないのでループを続行

    } else {
      LOG_PRINTLN(
          "[GC] Failed to remove directory. It might remain in uploaded list.");
      // 削除に失敗した場合、次のアイテムに進む
    }
  } // End of for loop

  if (!spaceFreed && removedCount > 0) {
    LOG_PRINTLN("[WARN] Removed all possible cycles, but free space might "
                "still be below threshold.");
  }

  LOG_PRINTF("[GC] Total cycles removed this run: %d\n", removedCount);

  // 7. 削除処理が完了した後、アップロード履歴ファイルを更新する
  if (removedCount > 0) {
    // メモリリストの変更をSDカードファイルに反映する
    File file = SD.open(UPLOADED_LIST_PATH, FILE_WRITE); // [cite: 352]
    if (file) {
      for (const String &cid : g_uploadedCidList) {
        file.println(cid); // [cite: 353]
      }
      file.close(); // [cite: 354]
      LOG_PRINTLN("[GC] Rewrote uploaded CIDs list file.");
    } else {
      LOG_PRINTLN("[ERR] Failed to open uploaded list file for rewriting after "
                  "GC!"); // [cite: 355]
    }
  }
}

static void requestShutdownAndWait() {
  LOG_PRINTLN("[SHUTDOWN] Task completed. Requesting PIC to cut power...");
  
  powerDownSdCardPins();
  
  // デバッグ用：本当にこの行まで到達しているか確認するためLEDを点灯
  pinMode(hw::PIN_FLASH, OUTPUT);
  digitalWrite(hw::PIN_FLASH, HIGH);
  
  digitalWrite(hw::PIN_DONE, HIGH);
  LOG_PRINTLN("[SHUTDOWN] Waiting for power off...");
  while (1) {
    delay(1000);
  }
}

/***********************************************************
 * 16.  Cycle Logic
 ***********************************************************/
/** @brief Gets the device's unique MAC address as a hex String. */
static String deviceIdHex() {
  uint8_t mac[6];
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  char buf[13];
  for (int i = 0; i < 6; i++)
    sprintf(buf + 2 * i, "%02X", mac[i]);
  buf[12] = '\0';
  return String(buf);
}
/** @brief Manages the persistent sequence number stored on SD card (/seq.txt).
 */
namespace seq {
const char *PATH = "/seq.txt"; // File path for sequence number
/** @brief Reads the last sequence number from the file. */
static uint32_t read() {
  File f = SD.open(PATH, FILE_READ);
  if (!f)
    return 0; // Start from 0 if file doesn't exist
  String s = f.readStringUntil('\n');
  f.close();
  uint32_t v = 0;
  // Basic string to integer conversion
  for (size_t i = 0; i < s.length(); ++i) {
    if (s[i] < '0' || s[i] > '9')
      break; // Stop at non-digit
    v = v * 10 + (s[i] - '0');
  }
  return v;
}
/** @brief Writes the new sequence number safely using a temporary file. */
static void write(uint32_t v) {
  // Write to temporary file first
  File tmp = SD.open("/seq.tmp", FILE_WRITE);
  if (!tmp) {
    LOG_PRINTLN("[ERR] Failed open /seq.tmp");
    return;
  }
  tmp.printf("%u\n", (unsigned)v);
  tmp.flush();
  tmp.close();
  // Replace original file with temporary file
  SD.remove(PATH);
  if (!SD.rename("/seq.tmp", PATH)) {
    LOG_PRINTLN("[ERR] Failed rename /seq.tmp");
  }
}
/** @brief Reads the last sequence number, increments it, writes back, and
 * returns the new number. */
static uint32_t next() {
  uint32_t v = read() + 1; // Increment
  write(v);                // Save new value
  g_currentSeqNum = v;     // Update global variable
  return v;
}
} // namespace seq
/**
 * @brief Generates a unique cycle ID based on MAC address and sequence number.
 * @return Cycle ID String (e.g., "AABBCCDDEEFF-00000001").
 */
static String makeCycleIdNoTime() {
  String devId = deviceIdHex();
  uint32_t seqNum = seq::next(); // Gets the *new* sequence number
  char buf[32];
  sprintf(buf, "%s-%08u", devId.c_str(),
          (unsigned)seqNum); // Format as MAC-00000000
  return String(buf);
}

/**
 * @brief Main function for the capture sequence. Called once per wake cycle.
 * Applies day/night actions, takes 4 shots (discards 1st), saves 3.
 */
static void beginCapture() {
  LOG_PRINTLN("[STEP] Cycle Start: Capture Sequence");
  g_tCapStart = millis();          // Record start of capture
  g_cycleId = makeCycleIdNoTime(); // Generate the unique ID for this cycle
  g_tBegin = millis();             // Record start time
  g_syslogStartOff = 0; // Include boot/storage diagnostics in the first checkpoint

  // Apply LED/Motor actions based on current light level
  bool night = isNight();
  applyDayNightActions(night);

  // --- Capture Loop ---
  // Takes NUM_SHOTS_TOTAL (4), saves NUM_SHOTS_SAVE (3)
  uint8_t savedCount = 0;
  bool captureOk = true;
  for (uint8_t i = 1; i <= param::NUM_SHOTS_TOTAL; ++i) {
    // Determine save index (0 for discard, 1, 2, 3 for saving)
    uint8_t saveIdx = (i == 1) ? 0 : savedCount + 1;
    bool success = shootAndSave(i, saveIdx, night); // Attempt capture/save

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

  // Explicitly power down camera interface to save power during WiFi/Upload
  esp_camera_deinit();
  powerDownCameraPins();

  // Log final status of the capture sequence
  if (captureOk && savedCount == param::NUM_SHOTS_SAVE) {
    LOG_PRINTLN("[STEP] Capture sequence completed successfully.");
  } else {
    LOG_PRINTF("[WARN] Capture sequence incomplete or failed. Saved %d out of "
               "%d required shots.\n",
               savedCount, param::NUM_SHOTS_SAVE);
    // Incomplete cycles will be skipped by the upload logic later
  }
  g_tCapEnd = millis(); // Record end of capture
  File metadata = SD.open("/archive/" + g_cycleId + "/capture_meta.json", FILE_WRITE);
  if (metadata) {
    metadata.printf("{\"capture_uptime_ms\":%lu,\"capture_duration_ms\":%lu,\"utc_known_at_capture\":false}\n",
                    (unsigned long)g_tCapStart, (unsigned long)(g_tCapEnd-g_tCapStart));
    metadata.close();
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

  // Start the status LED task
  // Solid LED indicates booting
  LOG_PRINTLN("\n=== ESP-CAM Boot: UTC unknown until edge synchronization ===");
  g_tWake = millis();
  // Record wake-up time

  // If code reaches here, wake reason was PIR or Timer

  // --- Initialize Hardware ---
  // Pin Modes

  pinMode(hw::PIN_DONE, OUTPUT);
  digitalWrite(hw::PIN_DONE, LOW);
  // Wake pin
  pinMode(hw::PIN_FLASH, OUTPUT); // Flash LED
  // Motor IN1
  pinMode(hw::PIN_CDS, INPUT);
  analogSetAttenuation(
      ADC_11db); // Use 11dB attenuation for full-range (0-3.3V) analog reading
  // Status LED (GPIO 4) pin mode is set within its task

  // Initial Pin States
  digitalWrite(hw::PIN_FLASH, LOW);

  // SD Card Initialization
  // Power on SD module
  pinMode(hw::PIN_SD_PWR, OUTPUT);
  digitalWrite(hw::PIN_SD_PWR, HIGH);
  delay(100);

  SPI.begin(hw::SD_SCK, hw::SD_MISO, hw::SD_MOSI, hw::SD_CS);
  g_sdReady = SD.begin(hw::SD_CS); // Attempt to mount SD card
  if (!g_sdReady) {
    LOG_PRINTLN("[FAIL] SD Card Mount Failed! -> Sleeping");
    delay(3000);
    // Show error blink for 3 seconds
    requestShutdownAndWait();
    // Enter sleep (will skip cooldown)
  }
  elog::ensure();
  // Ensure /logs directory exists
  openNewDailyLogFile(); // Prepare the bounded serial log
  loadUploadedList();
  cleanupOldArchives();

  // --- Main Operations ---
  // 1. Initialize Camera
  if (!initCamera()) {
    LOG_PRINTLN("[FAIL] Camera Initialization Failed! -> Sleeping");
    delay(3000);
    requestShutdownAndWait();
  }

  // 2. Perform Capture Sequence (Takes priority)
  // Fast blink indicates capturing
  beginCapture(); // Takes 4 shots, saves 3 to /archive/[cycleId]
  // Solid ON indicates capture finished

  // ▼▼▼ ★★★ 修正箇所 (ここから) ★★★ ▼▼▼
  // (goDeepSleepNow から移動)
  // --- Save current cycle log chunk (Moved BEFORE upload attempt) ---
  saveCurrentLogChunkToSD("early");
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
  LOG_PRINTLN("[STEP] All tasks complete. Saving logs before PIC shutdown.");
  // Save remaining logs generated during Wi-Fi and Upload phases
  saveCurrentLogChunkToSD("final");
  cleanupOldArchives();
  requestShutdownAndWait(); // Saves logs, cleans archive, waits 30s, sets pins,
                            // sleeps
}

void loop() {
  // If execution unexpectedly reaches here, log an error and force sleep
  LOG_PRINTLN("[FATAL] Execution reached main loop! This should not happen. "
              "Forcing sleep.");
  delay(2000); // Show error blink
  requestShutdownAndWait();
}
