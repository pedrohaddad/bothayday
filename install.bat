@echo off
setlocal
cd /d "%~dp0"
echo === HayDayBot - instalacao ===
where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale o Python 3.10+ de https://www.python.org/downloads/
  echo Marque "Add python.exe to PATH" durante a instalacao.
  pause
  exit /b 1
)
if not exist .venv (
  echo Criando ambiente virtual .venv ...
  %PY% -m venv .venv || (echo Falha ao criar o venv & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || (echo Falha ao instalar dependencias & pause & exit /b 1)
echo.
echo Instalacao concluida. Execute run.bat para abrir o HayDayBot.
pause
