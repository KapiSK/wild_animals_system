#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include "camera_pins.h"

// ===========================
// Configuration
// ===========================
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// Edge Server URL (Replace 192.168.1.100 with your Raspberry Pi's IP)
const char* serverUrl = "http://192.168.1.100:8000/upload"; 

// Deep Sleep time (in seconds)
#define TIME_TO_SLEEP  60

// ===========================

#define uS_TO_S_FACTOR 1000000ULL 

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println();

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
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  
  if(psramFound()){
    config.frame_size = FRAMESIZE_UXGA;
    config.jpeg_quality = 10;
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_SVGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }

  // Camera init
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x", err);
    return;
  }

  // Wi-Fi connection
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");
  Serial.println("WiFi connected");

  // Take Picture
  camera_fb_t * fb = NULL;
  fb = esp_camera_fb_get();
  if(!fb) {
    Serial.println("Camera capture failed");
    return;
  }

  // Upload
  if(WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverUrl);
    
    // Construct simplified multipart/form-data manually to avoid external libraries if possible
    // Or just send raw bytes if server handled it. But main.py expects Login.
    // Here we use a standard boundary approach.
    String boundary = "------------------------esp32camera";
    String head = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"capture.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n";
    String tail = "\r\n--" + boundary + "--\r\n";

    uint32_t imageLen = fb->len;
    uint32_t extraLen = head.length() + tail.length();
    uint32_t totalLen = imageLen + extraLen;

    http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);
    
    uint8_t *buffer = (uint8_t *)ps_malloc(totalLen);
    if(buffer) {
      memcpy(buffer, head.c_str(), head.length());
      memcpy(buffer + head.length(), fb->buf, imageLen);
      memcpy(buffer + head.length() + imageLen, tail.c_str(), tail.length());
      
      int httpResponseCode = http.POST(buffer, totalLen);
      Serial.print("HTTP Response code: ");
      Serial.println(httpResponseCode);
      free(buffer);
    } else {
      Serial.println("Malloc failed");
    }
    http.end();
  }

  esp_camera_fb_return(fb);

  // Deep Sleep
  esp_sleep_enable_timer_wakeup(TIME_TO_SLEEP * uS_TO_S_FACTOR);
  Serial.println("Going to sleep now");
  Serial.flush(); 
  esp_deep_sleep_start();
}

void loop() {
  // empty
}
