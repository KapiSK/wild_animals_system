/*
 * Communication Range Experiment Firmware for ESP32-S3 (XIAO)
 * 
 * Function:
 * - Connects to WiFi
 * - Generates 500KB dummy data in PSRAM
 * - Sends data to Edge Server continuously
 * - Visualizes success/failure via LED
 * 
 * Hardware:
 * - Seeed XIAO ESP32-S3 Sense
 * - LED on GPIO 21 (User LED) or GPIO 4 (Camera Board LED)?
 *   - Original camera.ino uses GPIO 4 for Status LED.
 * 
 * Usage:
 * - Update PI_HOST to your server's IP.
 * - Compile and upload.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <esp_heap_caps.h>

#include <ESPmDNS.h>

// ==========================================
// Configurations
// ==========================================
// WiFi Credentials
//const char* WIFI_SSID = "aterm-e1ab3a";
//const char* WIFI_PASS = "7cac2cfd46f83";
const char* WIFI_SSID = "SLAB-g";
const char* WIFI_PASS = "wakaW1sat0";

// Server Configuration
// Hostname to resolve (e.g., "edge" for edge.local)
const char* PI_HOSTNAME = "edge-ex"; 
int PI_PORT = 8000;

String UPLOAD_URL = ""; // Will be set after mDNS resolution

// Data Configuration
const size_t DATA_SIZE = 500 * 1024; // 500KB
uint8_t* g_dataBuffer = nullptr;

// Pin Definitions (XIAO ESP32-S3 Sense)
const int PIN_LED = 21; // Onboard LED
const int PIN_LED_STATUS = 4; // Expansion board LED

// Global Variables
uint32_t g_seqNum = 0;

void setup() {
  Serial.begin(115200);
  delay(1000); // Wait for Serial
  Serial.println("\n=== Communication Range Experiment ===");

  // Init LEDs
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_LED_STATUS, OUTPUT);
  digitalWrite(PIN_LED, HIGH); // Off
  digitalWrite(PIN_LED_STATUS, LOW);

  // Allocate PSRAM Buffer
  Serial.printf("Allocating %d bytes in PSRAM... ", DATA_SIZE);
  g_dataBuffer = (uint8_t*)heap_caps_malloc(DATA_SIZE, MALLOC_CAP_SPIRAM);
  
  if (g_dataBuffer == nullptr) {
    Serial.println("FAILED! PSRAM not available?");
    while(1) { blinkError(); }
  }
  memset(g_dataBuffer, 0xA5, DATA_SIZE);
  Serial.println("Done.");

  // Connect to WiFi
  Serial.printf("Connecting to %s ", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    digitalWrite(PIN_LED, !digitalRead(PIN_LED));
  }
  Serial.println("\nConnected!");
  Serial.print("IP: "); Serial.println(WiFi.localIP());
  digitalWrite(PIN_LED, HIGH);

  // Initialize mDNS
  if (!MDNS.begin("esp32-tester")) {
    Serial.println("Error setting up mDNS responder!");
  }
  
  // Resolve Host
  Serial.printf("Resolving host '%s.local'...", PI_HOSTNAME);
  IPAddress serverIp = MDNS.queryHost(PI_HOSTNAME);
  
  // Retry loop if not found immediately
  while (serverIp == IPAddress()) {
    Serial.print(".");
    delay(1000);
    serverIp = MDNS.queryHost(PI_HOSTNAME);
    digitalWrite(PIN_LED, !digitalRead(PIN_LED)); // Blink while searching
  }
  
  Serial.println("\nHost found!");
  Serial.print("Server IP: "); Serial.println(serverIp);
  
  UPLOAD_URL = "http://" + serverIp.toString() + ":" + String(PI_PORT) + "/upload";
  Serial.println("URL: " + UPLOAD_URL);
  
  digitalWrite(PIN_LED, HIGH); // Off
}

void loop() {
  g_seqNum++;
  long rssi = WiFi.RSSI();
  
  Serial.printf("Seq: %d, RSSI: %ld dBm... ", g_seqNum, rssi);

  // Prepare HTTP Request
  HTTPClient http;
  
  // Connect
  if (http.begin(UPLOAD_URL)) {
    http.addHeader("Content-Type", "application/octet-stream");
    http.addHeader("X-Seq-Num", String(g_seqNum));
    http.addHeader("X-Rssi", String(rssi));
    
    // Measure time
    uint32_t tStart = millis();
    
    // Send POST
    int httpCode = http.POST(g_dataBuffer, DATA_SIZE);
    
    uint32_t duration = millis() - tStart;
    
    if (httpCode == HTTP_CODE_OK) {
      Serial.printf("Success! (%d ms)\n", duration);
      blinkSuccess();
    } else {
      Serial.printf("Failed! Code: %d (%s)\n", httpCode, http.errorToString(httpCode).c_str());
      blinkFail();
    }
    http.end();
  } else {
    Serial.println("Connection failed!");
    blinkFail();
  }

  // Interval
  delay(2000);
}

// ==========================================
// Helper Functions
// ==========================================
void blinkSuccess() {
  // Short blink (100ms)
  // Check which LED is visible. Toggle both.
  digitalWrite(PIN_LED, LOW); // On
  digitalWrite(PIN_LED_STATUS, HIGH); // On
  delay(100);
  digitalWrite(PIN_LED, HIGH); // Off
  digitalWrite(PIN_LED_STATUS, LOW); // Off
}

void blinkFail() {
  // 3 Short blinks (or 1 long) - Let's do 3 quick blinks
  for (int i=0; i<3; i++) {
    digitalWrite(PIN_LED, LOW);
    digitalWrite(PIN_LED_STATUS, HIGH);
    delay(100);
    digitalWrite(PIN_LED, HIGH);
    digitalWrite(PIN_LED_STATUS, LOW);
    delay(100);
  }
}

void blinkError() {
  // Continuous fast blink
  digitalWrite(PIN_LED, !digitalRead(PIN_LED));
  delay(50);
}
