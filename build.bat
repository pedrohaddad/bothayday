@echo off
setlocal
cd /d "%~dp0"
echo === HayDayBot - gerando dist\HayDayBot.exe ===
if not exist .venv\Scripts\python.exe call install.bat
call .venv\Scripts\activate.bat
python -m pip install "pyinstaller>=6.0" || (echo Falha ao instalar o PyInstaller & pause & exit /b 1)

pyinstaller --noconfirm --clean --onefile --windowed --name HayDayBot ^
  --hidden-import PIL._tkinter_finder ^
  --collect-submodules keyboard ^
  main.py || (echo Falha no PyInstaller & pause & exit /b 1)

rem Pastas e arquivos que ficam AO LADO do .exe (editaveis pelo usuario)
xcopy /E /I /Y templates dist\templates >nul
if not exist dist\config.json copy /Y config.json dist\config.json >nul
if not exist dist\screenshots\errors mkdir dist\screenshots\errors
if not exist dist\logs mkdir dist\logs
copy /Y README.md dist\README.md >nul

echo.
echo Pronto: dist\HayDayBot.exe
echo Distribua a pasta dist\ inteira (exe + templates + config.json).
pause
