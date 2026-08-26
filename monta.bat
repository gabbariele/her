@echo off
REM Doppio clic per (ri)montare una puntata: senza argomenti prende l'ultima.
REM Serve se la finestra si e' chiusa prima che il montaggio fosse pronto.
cd /d "%~dp0"
if not exist .venv\Scripts\her.exe ( echo Prima installa: doppio clic su setup.bat & pause & exit /b 1 )
.venv\Scripts\her.exe render %*
echo.
pause
