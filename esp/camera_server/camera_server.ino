/* *****************************************************
 * camera_server.ino — Seeed XIAO ESP32-S3 (Server Mode)
 *
 * トレイルカメラのサーバ化実験用コード:
 * - Wi-FiにSTAモードで接続し、Webサーバー(ポート80)を起動します。
 * - 以下のAPI (HTTP GET) を提供します:
 *   - `/` : 操作用コントローラー画面 (HTML) を表示
 *   - `/capture` : 現在のカメラフレームをJPEG形式で取得
 *   - `/nightmode?state=on|off` : ナイトモード(IRカットフィルター)の切替
 *
 * ハードウェア構成（現行デバイス踏襲）:
 * - GPIO 2: モータードライバ IN1
 * - GPIO 3: モータードライバ IN2
 * - GPIO 4: ステータスLED
 * - GPIO 6: フラッシュLED (または赤外線LED) 制御
 * - カメラ: XIAO ESP32-S3 Sense ボード上のカメラ
 * *****************************************************/

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include "esp_camera.h"

// =======================================================
// Hardware Pin Definitions
// =======================================================
#define CAMERA_MODEL_XIAO_ESP32S3
#include "camera_pins.h" 

namespace hw {
  constexpr uint8_t PIN_MOTOR_IN1 = 2;  // Motor Driver Input 1
  constexpr uint8_t PIN_MOTOR_IN2 = 3;  // Motor Driver Input 2
  constexpr uint8_t PIN_STATUS    = 4;  // Status LED Output
  constexpr uint8_t PIN_FLASH     = 6;  // Flash/IR LED Control Output
  constexpr uint8_t PIN_MOTOR     = PIN_MOTOR_IN1; // Alias for Motor IN1
}

// =======================================================
// Network & Server Configuration
// =======================================================
// ESP32自身が発信するWi-Fiネットワークの設定 (SoftAPモード)
const char* AP_SSID = "EdgeCamera_AP";    // 接続先となるネットワーク名
const char* AP_PASS = "camera1234";       // パスワード(最低8文字)

IPAddress local_ip(192, 168, 4, 1);       // ESP32のIPアドレス
IPAddress gateway(192, 168, 4, 1);
IPAddress subnet(255, 255, 255, 0);

WebServer server(80);

// =======================================================
// State Variables
// =======================================================
bool isNightModeOn = false; // 現在のナイトモード状態

// =======================================================
// Motor Control Functions
// =======================================================
static inline void motorReverse() { 
  digitalWrite(hw::PIN_MOTOR, HIGH); 
  digitalWrite(hw::PIN_MOTOR_IN2, LOW); 
  Serial.println("[MOTOR] Reverse (IR Filter OFF / Night)"); 
}

static inline void motorForward() { 
  digitalWrite(hw::PIN_MOTOR, LOW); 
  digitalWrite(hw::PIN_MOTOR_IN2, HIGH); 
  Serial.println("[MOTOR] Forward (IR Filter ON / Day)"); 
}

static inline void motorStop() { 
  digitalWrite(hw::PIN_MOTOR, LOW); 
  digitalWrite(hw::PIN_MOTOR_IN2, LOW); 
  Serial.println("[MOTOR] Stop"); 
}

// IRカットフィルターの切り替え (一定時間モーター駆動してから停止)
void switchNightMode(bool enable) {
  if (enable) {
    motorReverse(); // フィルターを外す（Night / 回転方向を逆転）
  } else {
    motorForward(); // フィルターを付ける（Day / 回転方向を逆転）
  }
  delay(500); // 0.5秒駆動
  motorStop();
  isNightModeOn = enable;

  // OV5640等の暗所タイムアウト対策:
  // ナイトモードの時だけAEC2（長秒露光/Night Mode AEC）をOFFにする
  sensor_t * s = esp_camera_sensor_get();
  if (s != NULL) {
    s->set_aec2(s, enable ? 0 : 1);
  }
}

// =======================================================
// Camera Initialization
// =======================================================
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
  config.frame_size = FRAMESIZE_UXGA;  // 1600x1200 (さらに高解像度にしてサイズアップ)
  config.pixel_format = PIXFORMAT_JPEG;
  config.jpeg_quality = 8;             // 画質(小さいほど高画質・ファイルサイズ大. より高品質に)
  config.fb_count = 2;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera initialization failed with error 0x%x\n", err);
    return false;
  }
  // 初期撮影(ゴミ捨て)
  camera_fb_t * fb = esp_camera_fb_get();
  if (fb) esp_camera_fb_return(fb);
  
  // ベースのセンサー設定 (ナイトモード特有のAEC2制御は switchNightMode で実施)
  sensor_t * s = esp_camera_sensor_get();
  if (s != NULL) {
    s->set_gain_ctrl(s, 1);      // オートゲインON
    s->set_exposure_ctrl(s, 1);  // オート露出ON
    s->set_bpc(s, 1);            // 黒点補正ON
    s->set_wpc(s, 1);            // 白点補正ON
  }
  
  return true;
}

// =======================================================
// Web Server Handlers
// =======================================================

// 1. ルートエンドポイント (操作画面HTML)
void handleRoot() {
  String html = "<html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'>";
  html += "<title>Edge Camera Server</title>";
  html += "<style>body{text-align:center;font-family:sans-serif;margin-top:20px;} img{max-width:100%;height:auto;border:1px solid #ccc;margin-bottom:10px;}";
  html += "button{padding:10px 20px;font-size:16px;margin:5px;cursor:pointer;}";
  html += "</style></head><body>";
  html += "<h1>Edge Camera</h1>";
  html += "<div><img id='cam' src='/capture?t=" + String(millis()) + "' alt='Camera View'></div>";
  html += "<div>";
  html += "<button onclick=\"document.getElementById('cam').src='/capture?t=' + new Date().getTime()\">[📷] 画像更新</button><br><br>";
  html += "<button onclick=\"fetch('/nightmode?state=on').then(r=>r.json()).then(d=>alert('Night Mode: ' + d.state))\">🌙 Night Mode ON</button>";
  html += "<button onclick=\"fetch('/nightmode?state=off').then(r=>r.json()).then(d=>alert('Night Mode: ' + d.state))\">☀️ Night Mode OFF</button>";
  html += "</div>";
  html += "</body></html>";
  
  server.send(200, "text/html", html);
}

// 2. 画像取得エンドポイント
void handleCapture() {
  Serial.println("[API] /capture requested");

  // ナイトモードがONの場合は撮影直前にLEDを点灯
  if (isNightModeOn) {
    digitalWrite(hw::PIN_FLASH, HIGH);
    // フラッシュの光でカメラの自動露出(AE)が適正な明るさまで下がるのを待つ。
    // そのため、複数枚のフレームを空撮りして捨て、AEの完了（白飛びの解消）を促す。
    for (int i = 0; i < 4; i++) {
      camera_fb_t * dummy_fb = esp_camera_fb_get();
      if (dummy_fb) esp_camera_fb_return(dummy_fb);
      delay(50); 
    }
  }

  // 実際の撮影（本番用）
  camera_fb_t * fb = esp_camera_fb_get();

  // 撮影直後にLEDを消灯
  if (isNightModeOn) {
    digitalWrite(hw::PIN_FLASH, LOW);
  }

  if (!fb) {
    Serial.println("Camera capture failed");
    server.send(500, "text/plain", "Camera capture failed");
    return;
  }

  // クライアントへ送信
  server.sendHeader("Cache-Control", "no-cache, no-store, must-revalidate");
  server.sendHeader("Pragma", "no-cache");
  server.sendHeader("Expires", "-1");
  server.setContentLength(fb->len);
  server.send(200, "image/jpeg", "");
  
  WiFiClient client = server.client();
  client.write(fb->buf, fb->len);

  esp_camera_fb_return(fb);
  Serial.println("[API] /capture send complete");
}

// 3. ナイトモード切替エンドポイント
void handleNightMode() {
  if (!server.hasArg("state")) {
    server.send(400, "application/json", "{\"error\":\"Missing 'state' parameter (on|off)\"}");
    return;
  }

  String state = server.arg("state");
  Serial.printf("[API] /nightmode requested: %s\n", state.c_str());

  if (state == "on") {
    switchNightMode(true);
    server.send(200, "application/json", "{\"status\":\"ok\", \"state\":\"on\"}");
  } 
  else if (state == "off") {
    switchNightMode(false);
    server.send(200, "application/json", "{\"status\":\"ok\", \"state\":\"off\"}");
  } 
  else {
    server.send(400, "application/json", "{\"error\":\"Invalid state. Use 'on' or 'off'\"}");
  }
}

// =======================================================
// Setup & Loop
// =======================================================
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n--- Edge Camera Server ---");

  // ピン設定
  pinMode(hw::PIN_MOTOR_IN1, OUTPUT);
  pinMode(hw::PIN_MOTOR_IN2, OUTPUT);
  pinMode(hw::PIN_FLASH, OUTPUT);
  pinMode(hw::PIN_STATUS, OUTPUT);

  digitalWrite(hw::PIN_MOTOR_IN1, LOW);
  digitalWrite(hw::PIN_MOTOR_IN2, LOW);
  digitalWrite(hw::PIN_FLASH, LOW);

  // カメラ初期化
  if (!initCamera()) {
    Serial.println("Camera Init Failed. Halting.");
    while(1) {
      digitalWrite(hw::PIN_STATUS, !digitalRead(hw::PIN_STATUS));
      delay(100);
    }
  }
  Serial.println("Camera Initialized.");

  // 初期はDayモード(IRフィルターON)にしておく
  switchNightMode(false);

  // Wi-Fi接続 (SoftAPモードへ変更)
  Serial.println("\nConfiguring Access Point...");
  WiFi.mode(WIFI_AP);
  WiFi.softAPConfig(local_ip, gateway, subnet);
  WiFi.softAP(AP_SSID, AP_PASS);
  
  digitalWrite(hw::PIN_STATUS, HIGH); // AP起動完了で点灯
  Serial.println("Access Point Started.");
  Serial.print("SSID: ");
  Serial.println(AP_SSID);
  Serial.print("IP Address: ");
  Serial.println(WiFi.softAPIP());

  // Webサーバーのルーティング設定
  server.on("/", HTTP_GET, handleRoot);
  server.on("/capture", HTTP_GET, handleCapture);
  server.on("/nightmode", HTTP_GET, handleNightMode);
  
  // サーバー起動
  server.begin();
  Serial.println("HTTP Server Started.");
}

void loop() {
  server.handleClient();
  delay(1);
}
