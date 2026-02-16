@echo off
cd /d %~dp0
echo Compiling firmware for XIAO ESP32S3 (PSRAM OPI)...
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi esp\experiment\experiment.ino
if %ERRORLEVEL% == 0 (
    echo Compilation Successful!
    echo You can upload using: arduino-cli upload -p COMx --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi esp\experiment\experiment.ino
) else (
    echo Compilation Failed!
)
pause
