@echo off
REM Doppio clic per (ri)montare una puntata: te la fa scegliere dall'elenco.
REM Serve dopo un aggiornamento, o se il montaggio non era stato scritto.
cd /d "%~dp0"
if not exist .venv\Scripts\her.exe ( echo Prima installa: doppio clic su setup.bat & pause & exit /b 1 )
.venv\Scripts\her.exe render --scegli %*
echo.
pause
