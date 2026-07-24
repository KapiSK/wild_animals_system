#include <Arduino.h>

// マイクロ秒を秒に変換するための係数
#define uS_TO_S_FACTOR 1000000ULL
// スリープする時間（秒）
#define TIME_TO_SLEEP  7
// 起動（アクティブ）を維持する時間（秒）
#define TIME_TO_AWAKE  7

// ディープスリープ中も保持されるRTCメモリ上の変数
RTC_DATA_ATTR int bootCount = 0;

// ウェイクアップ（起動）の理由を出力する関数
void print_wakeup_reason() {
  esp_sleep_wakeup_cause_t wakeup_reason = esp_sleep_get_wakeup_cause();

  switch(wakeup_reason) {
    case ESP_SLEEP_WAKEUP_TIMER:
      Serial.println("タイマーによってウェイクアップしました");
      break;
    default:
      Serial.printf("通常の起動、またはその他の理由による起動です。理由コード: %d\n", wakeup_reason);
      break;
  }
}

void setup() {
  Serial.begin(115200);
  
  // シリアル通信が安定するまで少し待機
  delay(1000);

  // 起動回数をカウントアップ
  bootCount++;
  Serial.println("=== 起動回数: " + String(bootCount) + " ===");

  // 起動理由の確認
  print_wakeup_reason();

  // 何らかの処理（例：センサー読み取りや画像送信など）をここに記述します
  // ...

  // 指定した時間（7秒間）起動（アクティブ）状態を維持する
  Serial.println(String(TIME_TO_AWAKE) + " 秒間起動状態を維持します...");
  delay(TIME_TO_AWAKE * 1000);

  // タイマーウェイクアップの設定（7秒）
  esp_sleep_enable_timer_wakeup(TIME_TO_SLEEP * uS_TO_S_FACTOR);
  Serial.println(String(TIME_TO_SLEEP) + " 秒間のディープスリープに入ります...");
  
  // シリアル出力が完了するのを待つ
  Serial.flush();
  delay(100);

  // ディープスリープを開始
  esp_deep_sleep_start();

  // ※ ここから下のコードは実行されません
}

void loop() {
  // ディープスリープ運用の場合、復帰時はsetup()から始まるため、
  // loop() 内の処理は基本的に実行されません。
}
