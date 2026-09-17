import sys
import re

with open('camera.ino', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
in_status_namespace = False
in_motor_funcs = False

hw_ns = '''namespace hw {
constexpr uint8_t SD_CS = 3;         // SD Card Chip Select
constexpr uint8_t SD_MOSI = 9;       // SD Card MOSI
constexpr uint8_t SD_MISO = 8;       // SD Card MISO
constexpr uint8_t SD_SCK = 7;        // SD Card Clock
constexpr uint8_t PIN_SD_PWR = 44;   // SD Card Power Control

constexpr uint8_t PIN_MOTION = 5;    // PIR Sensor Input / Wake-up
constexpr uint8_t PIN_CDS = 2;       // CDS Light Sensor Input (Analog)
constexpr uint8_t PIN_BATT_SENSE = 4;// 2.1V Battery voltage drop detection

constexpr uint8_t PIN_FLASH = 6;     // Flash LED (5VA DCDC) Control Output

constexpr uint8_t PIN_FLAG = PIN_MOTION; // Alias for wake pin used in sleep setup
} // namespace hw
'''

in_hw_ns = False

for i, line in enumerate(lines):
    if '// --- Motor Control Functions ---' in line:
        in_motor_funcs = True
        continue
    if in_motor_funcs and '/** @brief Activates LED and Motor based on the isNight() status. */' in line:
        in_motor_funcs = False
    if in_motor_funcs:
        continue

    if 'namespace status {' in line:
        in_status_namespace = True
        continue
    if in_status_namespace and line.startswith('} // namespace status'):
        in_status_namespace = False
        continue
    if in_status_namespace:
        continue

    if 'namespace hw {' in line:
        in_hw_ns = True
        new_lines.append(hw_ns)
        continue
    if in_hw_ns and line.startswith('} // namespace hw'):
        in_hw_ns = False
        continue
    if in_hw_ns:
        continue

    if re.search(r'^\s*status::setLed\(', line) or re.search(r'^\s*status::begin\(', line):
        continue
    if 'status::LedState' in line:
        continue
    if re.search(r'^\s*motorStop\(', line) or re.search(r'^\s*motorForward\(', line) or re.search(r'^\s*motorReverse\(', line):
        continue
    if 'pinMode(hw::PIN_MOTOR' in line or 'digitalWrite(hw::PIN_MOTOR' in line:
        continue
    if 'pinMode(hw::PIN_STATUS' in line or 'digitalWrite(hw::PIN_STATUS' in line:
        continue
    if 'enum class Dir { FWD, REV, STOP };' in line or 'constexpr Dir MOTOR_DIR_' in line:
        continue

    if 'daynight::Dir direction =' in line or 'night ? daynight::MOTOR_DIR_NIGHT : daynight::MOTOR_DIR_DAY' in line:
        continue
    if 'switch (direction) {' in line or 'case daynight::Dir::' in line or (line.strip() == 'break;' and 'daynight::Dir' in lines[i-1]):
        continue
    if line.strip() == '}' and i > 0 and 'break;' in lines[i-1] and 'daynight::Dir' in lines[i-2]:
        continue

    if 'SPI.begin(hw::SD_SCK, hw::SD_MISO, hw::SD_MOSI, hw::SD_CS);' in line:
        new_lines.append('  // Power on SD module\n  pinMode(hw::PIN_SD_PWR, OUTPUT);\n  digitalWrite(hw::PIN_SD_PWR, HIGH);\n  delay(100);\n\n')
        new_lines.append(line)
        continue

    if 'LOG_PRINTLN("[PWR ] Powering down SD card pins...");' in line:
        new_lines.append(line)
        new_lines.append('  pinMode(hw::PIN_SD_PWR, OUTPUT);\n  digitalWrite(hw::PIN_SD_PWR, LOW);\n')
        continue

    new_lines.append(line)

res = ''.join(new_lines)
with open('camera.ino', 'w', encoding='utf-8') as f:
    f.write(res)
