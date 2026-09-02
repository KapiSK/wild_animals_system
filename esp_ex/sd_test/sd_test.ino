#include <Arduino.h>
#include <SPI.h>
#include <SD.h>

// XIAO ESP32-S3 Sense 外部SDカードコネクタ配線
constexpr uint8_t SD_SCK  = 7; // CLK
constexpr uint8_t SD_MISO = 8; // DAT0
constexpr uint8_t SD_MOSI = 9; // CMD
constexpr uint8_t SD_CS   = 3; // DAT3

// SD電源制御用ピン (HIGHで電源ONを想定)
constexpr uint8_t PIN_SD_POWER = 44;

void setup() {
  Serial.begin(115200);
  
  // シリアルモニタが開くまで待機（最大3秒）
  while (!Serial && millis() < 3000);

  Serial.println("\n===========================");
  Serial.println("    SD Card Test Script    ");
  Serial.println("===========================");

  // 0. SDモジュールの電源をONにする
  Serial.println("0. Turning ON SD Power (GPIO 44)...");
  pinMode(PIN_SD_POWER, OUTPUT);
  digitalWrite(PIN_SD_POWER, HIGH);
  
  // 電源やプルアップ抵抗の電圧が安定するまで少し待機します
  delay(100);

  // 1. SPIバスの初期化
  // CS制御はSD.begin側に任せるため、SPI.beginの第4引数は-1を指定します
  Serial.println("1. Initializing SPI bus...");
  SPI.begin(SD_SCK, SD_MISO, SD_MOSI, -1);

  // 2. SDカードのマウント
  // ジャンパ配線でのノイズを考慮し、通信速度を安定志向の1MHzに落としています
  Serial.println("2. Mounting SD Card...");
  if (!SD.begin(SD_CS, SPI, 1000000)) {
    Serial.println("\n[ERROR] SD Card initialization failed!");
    Serial.println("▼考えられる原因:");
    Serial.println("・DAT1(#8) と DAT2(#1) が 3.3V にプルアップされていない");
    Serial.println("・ジャンパワイヤやブレッドボードの接触不良");
    Serial.println("・電源（3.3V）が不安定");
    return; // エラーの場合はここで処理を完全に停止します
  }
  Serial.println("[SUCCESS] SD Card initialized successfully.");

  // 3. ファイル書き込みテスト
  const char* testFile = "/test_xiao.txt";
  Serial.printf("\n3. Writing to file: %s\n", testFile);
  File file = SD.open(testFile, FILE_WRITE);
  
  // ファイルが開けたかどうかの確実なエラーチェック
  if (!file) {
    Serial.println("[ERROR] Failed to open file for writing.");
    return;
  }
  
  if (file.println("Hello from XIAO ESP32-S3! SD Card is working!")) {
    Serial.println("[SUCCESS] Write test passed.");
  } else {
    Serial.println("[ERROR] Write failed.");
  }
  file.close();

  // 4. ファイル読み込みテスト
  Serial.printf("\n4. Reading from file: %s\n", testFile);
  file = SD.open(testFile, FILE_READ);
  if (!file) {
    Serial.println("[ERROR] Failed to open file for reading.");
    return;
  }
  
  Serial.print("File content: \"");
  while (file.available()) {
    Serial.write(file.read());
  }
  Serial.println("\"");
  file.close();

  Serial.println("\n===========================");
  Serial.println("    All Tests Completed!   ");
  Serial.println("===========================");
}

void loop() {
  // テスト用なのでループ内は何もしません
  delay(10000);
}
