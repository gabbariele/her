@echo off
REM Doppio clic per aggiornare her all'ultima versione.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe ( echo Prima installa: doppio clic su setup.bat & pause & exit /b 1 )
.venv\Scripts\python.exe aggiorna.py
echo.
pause
