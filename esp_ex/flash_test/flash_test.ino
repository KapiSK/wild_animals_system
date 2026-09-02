#include <Arduino.h>

// 赤外線フラッシュ (LED) のピン定義
// camera.inoの定義に合わせています (GPIO 6)
#define PIN_FLASH 6

void setup() {
    Serial.begin(115200);
    while (!Serial) { delay(10); } // Wait for Serial
    delay(1000);
    Serial.println("=== ESP32 Flash Blink Test ===");

    // フラッシュピンを出力モードに設定
    pinMode(PIN_FLASH, OUTPUT);
    
    // 初期状態はOFF
    digitalWrite(PIN_FLASH, LOW);
}

void loop() {
    Serial.println("Flash ON");
    digitalWrite(PIN_FLASH, HIGH); // 点灯
    delay(1000); // 1秒待機

    Serial.println("Flash OFF");
    digitalWrite(PIN_FLASH, LOW);  // 消灯
    delay(1000); // 1秒待機
}
