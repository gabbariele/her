@echo off
REM Doppio clic per iniziare a registrare una puntata. Ctrl-C per chiudere.
REM Ospite, modelli e attesa si scelgono nel file .env (righe HER_PRESET e HER_PAUSA).
cd /d "%~dp0"
if not exist .venv\Scripts\her.exe ( echo Prima installa: doppio clic su setup.bat & pause & exit /b 1 )
echo Parti pure quando vuoi. Per chiudere la puntata: Ctrl-C
echo.
.venv\Scripts\her.exe record
echo.
pause
