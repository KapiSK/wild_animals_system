#include "esp_camera.h"
#include <Arduino.h>
#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <SD.h>
#include <SPI.h>
#include <WiFi.h>

// =======================================================
// Hardware Pin Definitions
// =======================================================
#define CAMERA_MODEL_XIAO_ESP32S3
#include "camera_pins.h" // 既存のカメラプロジェクトのピン定義をコピーして使用

namespace hw {
constexpr uint8_t SD_CS = 21;      // SD Card Chip Select
constexpr uint8_t SD_MOSI = 9;     // SD Card MOSI
constexpr uint8_t SD_MISO = 8;     // SD Card MISO
constexpr uint8_t SD_SCK = 7;      // SD Card Clock
constexpr uint8_t PIN_SD_PWR = 44; // SD Card Power Control

constexpr uint8_t PIN_FLASH = 6; // Flash LED Control Output
} // namespace hw

// =======================================================
// Network Configuration
// =======================================================
namespace net {
constexpr char WIFI_SSID[] = "SLAB_KD01";
constexpr char WIFI_PASS[] = "wakaW1sat0";
} // namespace net

// =======================================================
// Config Parameters
// =======================================================
constexpr int RSSI_CHANGE_THRESHOLD = 3;  // 何dBm変化したら記録するか
constexpr int MEASURE_INTERVAL_MS = 1000; // 測定間隔

// Global Variables
int g_previous_rssi = 0;
bool g_is_first_measure = true;

// =======================================================
// BLE Configuration
// =======================================================
#define SERVICE_UUID "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define CHARACTERISTIC_UUID "beb5483e-36e1-4688-b7f5-ea07361b26a8"

BLEServer *pServer = NULL;
BLECharacteristic *pCharacteristic = NULL;
bool deviceConnected = false;

class MyServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *pServer) { deviceConnected = true; };

  void onDisconnect(BLEServer *pServer) {
    deviceConnected = false;
    pServer->getAdvertising()->start(); // 再接続できるようにアドバタイズ再開
  }
};

void notifyBLE(const char *msg) {
  if (deviceConnected && pCharacteristic) {
    pCharacteristic->setValue(msg);
    pCharacteristic->notify();
  }
}

// =======================================================
// LED Error Indicator
// =======================================================
void fatalErrorBlink() {
  pinMode(hw::PIN_FLASH, OUTPUT);
  while (true) {
    digitalWrite(hw::PIN_FLASH, HIGH);
    delay(100);
    digitalWrite(hw::PIN_FLASH, LOW);
    delay(100);
  }
}

void successBlink() {
  pinMode(hw::PIN_FLASH, OUTPUT);
  digitalWrite(hw::PIN_FLASH, HIGH);
  delay(200);
  digitalWrite(hw::PIN_FLASH, LOW);
}

// =======================================================
// Initialization
// =======================================================
bool initCamera() {
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
  config.xclk_freq_hz = 10000000;
  config.frame_size = FRAMESIZE_UXGA;
  config.pixel_format = PIXFORMAT_JPEG;
  config.jpeg_quality = 12;
  config.fb_count = 2;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x\n", err);
    return false;
  }
  return true;
}

void initWiFi() {
  Serial.print("Connecting to WiFi: ");
  Serial.println(net::WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(net::WIFI_SSID, net::WIFI_PASS);

  int retry = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    retry++;
    if (retry > 60) {
      Serial.println("\nWiFi connection timeout.");
      // fatalErrorBlink(); //
      // 接続できない場合は単独で動けないので止めるのもありだが、再試行させる手もある
    }
  }
  Serial.println("\nWiFi Connected.");
}

// =======================================================
// Record Logic
// =======================================================
void captureAndRecord(int current_rssi) {
  uint32_t timestamp = millis();
  char imgFilename[64];
  sprintf(imgFilename, "/rssi_map/img_%lu_R%d.jpg", (unsigned long)timestamp,
          current_rssi);

  // 1. Capture Image
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Camera capture failed");
    return;
  }

  // 2. Save Image to SD
  File file = SD.open(imgFilename, FILE_WRITE);
  bool saveSuccess = false;
  if (file) {
    size_t written = file.write(fb->buf, fb->len);
    file.close();
    if (written == fb->len) {
      Serial.printf("Saved image: %s\n", imgFilename);
      saveSuccess = true;
    } else {
      Serial.println("File write failed or incomplete");
      SD.remove(imgFilename);
    }
  } else {
    Serial.printf("Failed to open file for writing: %s\n", imgFilename);
  }
  esp_camera_fb_return(fb);

  // 3. Log to CSV
  if (saveSuccess) {
    File logFile = SD.open("/rssi_map/rssi_log.csv", FILE_APPEND);
    if (logFile) {
      logFile.printf("%lu,%d,%s\n", (unsigned long)timestamp, current_rssi,
                     imgFilename);
      logFile.close();
    } else {
      Serial.println("Failed to open CSV log file");
    }
    // LED blink on success
    successBlink();
    char msg[64];
    sprintf(msg, "REC:%ddBm", current_rssi);
    notifyBLE(msg);
  }
}

// =======================================================
// Setup
// =======================================================
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("--- RSSI Mapper Starting ---");

  pinMode(hw::PIN_FLASH, OUTPUT);
  digitalWrite(hw::PIN_FLASH, LOW);

  // SD Card Power
  pinMode(hw::PIN_SD_PWR, OUTPUT);
  digitalWrite(hw::PIN_SD_PWR, HIGH);
  delay(100);

  // Init SD
  SPI.begin(hw::SD_SCK, hw::SD_MISO, hw::SD_MOSI, hw::SD_CS);
  if (!SD.begin(hw::SD_CS)) {
    Serial.println("SD Card Mount Failed!");
    fatalErrorBlink();
  }

  // Create Directory & Log file header
  if (!SD.exists("/rssi_map")) {
    SD.mkdir("/rssi_map");
  }
  if (!SD.exists("/rssi_map/rssi_log.csv")) {
    File logFile = SD.open("/rssi_map/rssi_log.csv", FILE_WRITE);
    if (logFile) {
      logFile.println("millis,rssi,filename");
      logFile.close();
    }
  }

  // Init Camera
  if (!initCamera()) {
    Serial.println("Camera Init Failed!");
    fatalErrorBlink();
  }

  // Init BLE
  BLEDevice::init("ESP-RSSI");
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());
  BLEService *pService = pServer->createService(SERVICE_UUID);
  pCharacteristic = pService->createCharacteristic(
      CHARACTERISTIC_UUID,
      BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  pCharacteristic->addDescriptor(new BLE2902());
  pService->start();
  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setScanResponse(false);
  pAdvertising->setMinPreferred(0x0);
  BLEDevice::startAdvertising();
  Serial.println("BLE started. Waiting for connections...");

  // First stabilization shots (discard)
  for (int i = 0; i < 3; i++) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb)
      esp_camera_fb_return(fb);
    delay(200);
  }

  initWiFi();
  Serial.println("Setup complete. Starting measurement loop.");
}

// =======================================================
// Loop
// =======================================================
void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    static uint32_t last_reconnect_attempt = 0;
    if (millis() - last_reconnect_attempt > 5000) {
      Serial.println("WiFi disconnected. Attempting to reconnect...");
      notifyBLE("ERR:No WiFi");
      WiFi.disconnect();
      WiFi.begin(net::WIFI_SSID, net::WIFI_PASS);
      last_reconnect_attempt = millis();
    }
    delay(100);
    return;
  }

  int current_rssi = WiFi.RSSI();
  Serial.printf("Current RSSI: %d dBm\n", current_rssi);

  char rssiMsg[32];
  sprintf(rssiMsg, "OK:%ddBm", current_rssi);
  notifyBLE(rssiMsg);

  if (g_is_first_measure) {
    g_previous_rssi = current_rssi;
    g_is_first_measure = false;
    Serial.println("First measurement. Saving baseline.");
    captureAndRecord(current_rssi);
  } else {
    if (abs(current_rssi - g_previous_rssi) >= RSSI_CHANGE_THRESHOLD) {
      Serial.printf("RSSI changed! Previous: %d, Current: %d\n",
                    g_previous_rssi, current_rssi);
      captureAndRecord(current_rssi);
      g_previous_rssi = current_rssi;
    }
  }

  delay(MEASURE_INTERVAL_MS);
}
