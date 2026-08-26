@echo off
REM Doppio clic: elenca le puntate registrate e dice quali file ha ciascuna.
cd /d "%~dp0"
if not exist .venv\Scripts\her.exe ( echo Prima installa: doppio clic su setup.bat & pause & exit /b 1 )
.venv\Scripts\her.exe sessioni
echo.
pause
