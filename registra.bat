@echo off
REM Doppio clic per iniziare a registrare una puntata. Ctrl-C per chiudere.
cd /d "%~dp0"
if not exist .venv\Scripts\her.exe ( echo Prima installa: doppio clic su setup.bat & pause & exit /b 1 )
if "%HER_PRESET%"=="" set HER_PRESET=intervista
echo Parti pure quando vuoi. Per chiudere la puntata: Ctrl-C
echo.
.venv\Scripts\her.exe record --preset %HER_PRESET%
echo.
pause
