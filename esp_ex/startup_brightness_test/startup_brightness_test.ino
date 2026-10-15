#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include "esp_camera.h"

// =======================================================
// Hardware Pin Definitions
// =======================================================
#define CAMERA_MODEL_XIAO_ESP32S3
#include "camera_pins.h"

// XIAO ESP32-S3 Sense 外部SDカードコネクタ配線
constexpr uint8_t SD_SCK  = 7; // CLK
constexpr uint8_t SD_MISO = 8; // DAT0
constexpr uint8_t SD_MOSI = 9; // CMD
constexpr uint8_t SD_CS   = 21; // DAT3

// SD電源制御用ピン
constexpr uint8_t PIN_SD_POWER = 44;

// =======================================================
// Settings
// =======================================================
// 撮影する合計フレーム数。20枚程度撮影すれば、最初の数秒間の輝度変化を網羅できます。
constexpr int NUM_FRAMES = 20; 

bool initCamera() {
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
  config.xclk_freq_hz = 10000000;
  
  // SDカードへの保存速度を考慮し、確認用としてVGA(640x480)を設定
  // より高解像度が必要な場合は FRAMESIZE_UXGA などに変更してください
  config.frame_size = FRAMESIZE_VGA;  
  config.pixel_format = PIXFORMAT_JPEG;
  config.jpeg_quality = 10;
  if (psramFound()) {
    Serial.println("PSRAM found! Using PSRAM for frame buffer.");
    config.fb_location = CAMERA_FB_IN_PSRAM;
    config.fb_count = 2;
  } else {
    Serial.println("WARNING: PSRAM not found. Falling back to DRAM.");
    Serial.println("Please enable PSRAM in Arduino IDE (Tools -> PSRAM -> OPI PSRAM) for better performance.");
    config.fb_location = CAMERA_FB_IN_DRAM;
    config.fb_count = 1; // DRAMには余裕がないため1枚に変更
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera initialization failed with error 0x%x\n", err);
    return false;
  }
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(1000); // シリアルモニタ起動待ち
  Serial.println("\n--- Edge Camera (ESP32) Brightness Startup Test ---");

  // 1. SDカードの電源ON・SPI初期化
  pinMode(PIN_SD_POWER, OUTPUT);
  digitalWrite(PIN_SD_POWER, HIGH);
  delay(100);

  SPI.begin(SD_SCK, SD_MISO, SD_MOSI, -1);
  if (!SD.begin(SD_CS, SPI, 1000000)) { // 安定性重視の1MHz
    Serial.println("SD Card Mount Failed! Check connections.");
    return;
  }
  Serial.println("SD Card Mount Succeeded.");

  // 2. カメラの初期化
  if (!initCamera()) {
    Serial.println("Camera Init Failed! Halting.");
    return;
  }
  Serial.println("Camera Initialized.");
  
  // センサーの各種設定（自動露出と自動ゲインがONになっていることを確認）
  sensor_t * s = esp_camera_sensor_get();
  if (s != NULL) {
    s->set_gain_ctrl(s, 1);      // オートゲインON
    s->set_exposure_ctrl(s, 1);  // オート露出ON
    s->set_bpc(s, 1);            // 黒点補正ON
    s->set_wpc(s, 1);            // 白点補正ON
  }

  Serial.println("Starting continuous capture for 5 seconds...");
  unsigned long startTime = millis();
  int frameCount = 0;

  // 3. 起動直後から5秒間連続撮影し、SDカードに連番で保存する
  while (millis() - startTime < 5000) {
    camera_fb_t * fb = esp_camera_fb_get();
    
    if (!fb) {
      Serial.println("Camera capture failed on frame " + String(frameCount));
      continue;
    }

    // ファイル名生成 (例: /frame_000.jpg)
    char filename[32];
    sprintf(filename, "/frame_%03d.jpg", frameCount);

    // SDカードへJPEG書き込み
    File file = SD.open(filename, FILE_WRITE);
    if (!file) {
      Serial.printf("Failed to open %s for writing\n", filename);
    } else {
      file.write(fb->buf, fb->len);
      file.close();
      unsigned long elapsed = millis() - startTime;
      Serial.printf("Saved %s (Elapsed Time: %lu ms)\n", filename, elapsed);
    }
    
    // バッファを解放
    esp_camera_fb_return(fb);
    
    frameCount++;
    
    // SDカードの書き込み速度次第ですが、少しインターバルを挟んで次を撮影します
    // 連続で撮るなら delay を短くするか、0 にします。
    // delay(10); // コメントアウト、または短くしてフレームレートを稼ぐ
  }

  unsigned long totalTime = millis() - startTime;
  float fps = (float)frameCount / (totalTime / 1000.0);
  Serial.printf("Capture complete! Total %d frames in %lu ms (Approx %.2f fps).\n", frameCount, totalTime, fps);
  Serial.println("Please check the SD card.");
}

void loop() {
  // 撮影完了後は何もしない
  delay(10000);
}
