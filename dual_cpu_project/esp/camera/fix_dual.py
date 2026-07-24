import re

file_path = r'c:\Users\kapib\vscodegit\wild_animals\test2\dual_cpu_project\esp\camera\camera.ino'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. ピン定義の変更
content = re.sub(
    r'constexpr uint8_t PIN_MOTION = 5;.*?constexpr uint8_t PIN_FLAG = PIN_MOTION; // Alias for wake pin used in sleep setup',
    '''constexpr uint8_t PIN_DONE = 4;      // PIC microcontroller DONE signal (HIGH = shutdown)
constexpr uint8_t PIN_CDS = 2;       // CDS Light Sensor Input (Analog)
constexpr uint8_t PIN_BATT_SENSE = 5;// 2.1V Battery voltage drop detection
constexpr uint8_t PIN_FLASH = 6;     // Flash LED (5VA DCDC) Control Output''',
    content,
    flags=re.DOTALL
)

# 2. SLEEP_COOLDOWN_MS の削除
content = re.sub(
    r'constexpr uint32_t SLEEP_COOLDOWN_MS =.*?30000; // Mandatory wait time before entering deep sleep \(ms\)\n',
    '',
    content,
    flags=re.DOTALL
)

# 3. sleepcfg と configureWakeAndMaybeSleepEarly を削除
content = re.sub(
    r'/[\*]+[\r\n\s\*]+15\.  Sleep helpers[\r\n\s\*]+/.+?namespace sleepcfg \{.*?\} // namespace sleepcfg[\r\n\s]+/\*\*[^\*]+\*/[\r\n\s]+static void configureWakeAndMaybeSleepEarly\(\) \{.*?\}[\r\n\s]+',
    '',
    content,
    flags=re.DOTALL
)

# 4. goDeepSleepNow() の書き換え
old_shutdown = r'static void goDeepSleepNow\(\) \{.*?\} // Enter Deep Sleep\n  // --- Code execution stops here until next wake up ---\n\}'
new_shutdown = '''static void requestShutdownAndWait() {
  LOG_PRINTLN("[SHUTDOWN] Task completed. Requesting PIC to cut power...");

  // Ensure flash is off
  gpio_hold_en((gpio_num_t)hw::PIN_FLASH);

  // Power down SD card pins
  powerDownSdCardPins();

  // Send DONE signal to PIC (GPIO4 HIGH)
  digitalWrite(hw::PIN_DONE, HIGH);

  LOG_PRINTLN("[SHUTDOWN] Waiting for power off...");
  
  // Infinite loop waiting for power cut
  while(1) {
    delay(1000);
  }
}'''
content = re.sub(old_shutdown, new_shutdown, content, flags=re.DOTALL)

# もし置換に失敗していたら強引に正規表現を調整する（関数の中身が最後までマッチするように）
if 'requestShutdownAndWait()' not in content:
    content = re.sub(r'static void goDeepSleepNow\(\) \{.*?// --- Code execution stops here until next wake up ---\n\}', new_shutdown, content, flags=re.DOTALL)


# 5. setup() 内の呼び出し修正
content = re.sub(
    r'gpio_hold_dis\(\(gpio_num_t\)hw::PIN_FLASH\); // Release hold from deep sleep\n  pinMode\(hw::PIN_FLAG, INPUT\);',
    '''gpio_hold_dis((gpio_num_t)hw::PIN_FLASH); // Release hold from deep sleep
  pinMode(hw::PIN_DONE, OUTPUT);
  digitalWrite(hw::PIN_DONE, LOW);''',
    content,
    flags=re.DOTALL
)

content = re.sub(r'  // Check wake reason.*?configureWakeAndMaybeSleepEarly\(\);\n', '', content, flags=re.DOTALL)

# goDeepSleepNow() の呼び出しを requestShutdownAndWait() に変更
content = content.replace('goDeepSleepNow()', 'requestShutdownAndWait()')

# #include "driver/rtc_io.h" と #include "esp_sleep.h" の削除
content = re.sub(r'#include "driver/rtc_io\.h".*?\n', '', content)
content = re.sub(r'#include "esp_sleep\.h".*?\n', '', content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Modification complete.")
