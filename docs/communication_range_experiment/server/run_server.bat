@echo off
cd /d %~dp0

echo Setting up Python environment...
if not exist venv (
    python -m venv venv
)

echo Installing dependencies...
venv\Scripts\pip install -r requirements.txt

echo Starting Server...
echo Access at http://localhost:8000/upload
echo Press Ctrl+C to stop.
venv\Scripts\python main.py
pause
