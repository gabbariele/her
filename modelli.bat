@echo off
REM Doppio clic: elenca i modelli che la tua chiave puo' usare.
cd /d "%~dp0"
if not exist .venv\Scripts\her.exe ( echo Prima installa: doppio clic su setup.bat & pause & exit /b 1 )
.venv\Scripts\her.exe models
echo.
echo Per usarne uno diverso, incolla il nome nel preset (cartella presets), alla riga model:
echo.
pause
