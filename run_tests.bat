@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe call install.bat
call .venv\Scripts\activate.bat
python -m pip install pytest >nul
python -m pytest -q tests
pause
