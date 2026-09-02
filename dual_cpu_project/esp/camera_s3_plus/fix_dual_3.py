import os

file_path = r'c:\Users\kapib\vscodegit\wild_animals\test2\dual_cpu_project\esp\camera\camera.ino'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

out_lines = []
skip = False

for i, line in enumerate(lines):
    # 1. ピンの置換
    if "constexpr uint8_t PIN_MOTION = 5;" in line:
        out_lines.append("constexpr uint8_t PIN_DONE = 4;      // PIC microcontroller DONE signal (HIGH = shutdown)\n")
        continue
    if "constexpr uint8_t PIN_BATT_SENSE = 4;" in line:
        out_lines.append("constexpr uint8_t PIN_BATT_SENSE = 5;// 2.1V Battery voltage drop detection\n")
        continue
    if "constexpr uint8_t PIN_FLAG = PIN_MOTION;" in line:
        continue # 削除

    # 2. SLEEP_COOLDOWN_MS の削除
    if "constexpr uint32_t SLEEP_COOLDOWN_MS =" in line:
        skip = True
        continue
    if skip and "30000; // Mandatory wait time before entering deep sleep (ms)" in line:
        skip = False
        continue

    # 3. 15. Sleep helpers ブロックの削除
    if "15.  Sleep helpers" in line:
        # この行の少し前から削除開始
        # 実際にはアウトプット済みなので、out_linesから数行ポップする
        while len(out_lines) > 0 and "/**" not in out_lines[-1] and "/" not in out_lines[-1] and "*" not in out_lines[-1]:
            pass # pop until we hit the comment block start if needed, but easier to just skip from here
        skip = True
        # out_linesから /*********************************************************** を消す
        if len(out_lines) >= 1 and "****************" in out_lines[-1]:
            out_lines.pop()
        if len(out_lines) >= 1 and "/*" in out_lines[-1]:
            out_lines.pop()
        continue
    
    # Otherwise, continue with normal operation が来たら skip 終了
    if skip and "Otherwise, continue with normal operation" in line:
        # } も来るはずなので次の行でskip終了
        pass
    
    if skip and line.strip() == "}":
        # 次の行が空行だったりするのでチェック
        if i > 0 and "Otherwise, continue with normal operation" in lines[i-1]:
            skip = False
            continue

    # 4. goDeepSleepNow の置換
    if "static void goDeepSleepNow() {" in line:
        out_lines.append('''static void requestShutdownAndWait() {
  LOG_PRINTLN("[SHUTDOWN] Task completed. Requesting PIC to cut power...");
  gpio_hold_en((gpio_num_t)hw::PIN_FLASH);
  powerDownSdCardPins();
  digitalWrite(hw::PIN_DONE, HIGH);
  LOG_PRINTLN("[SHUTDOWN] Waiting for power off...");
  while(1) { delay(1000); }
}
''')
        skip = True
        continue
    
    # goDeepSleepNow の終わり判定
    if skip and line.strip() == "}":
        if i > 0 and "--- Code execution stops here until next wake up ---" in lines[i-1]:
            skip = False
            continue

    # 5. setup() 内の修正
    if "gpio_hold_dis((gpio_num_t)hw::PIN_FLASH);" in line:
        out_lines.append(line)
        out_lines.append("  pinMode(hw::PIN_DONE, OUTPUT);\n")
        out_lines.append("  digitalWrite(hw::PIN_DONE, LOW);\n")
        continue
    if "pinMode(hw::PIN_FLAG, INPUT);" in line:
        continue # 削除
    if "configureWakeAndMaybeSleepEarly();" in line:
        continue # 削除
    if "Check wake reason, sleep immediately if it was a cold boot" in line:
        continue # 削除

    # 6. goDeepSleepNow の呼び出し変更
    if "goDeepSleepNow()" in line:
        line = line.replace("goDeepSleepNow()", "requestShutdownAndWait()")

    # 7. #include "driver/rtc_io.h" / esp_sleep.h 削除
    if '#include "driver/rtc_io.h"' in line or '#include "esp_sleep.h"' in line:
        continue

    if not skip:
        out_lines.append(line)


with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(out_lines)

print("Python refactoring done.")
