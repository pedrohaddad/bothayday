@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Ambiente nao instalado. Executando install.bat ...
  call install.bat
)
start "" .venv\Scripts\pythonw.exe main.py
