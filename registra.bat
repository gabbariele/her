@echo off
REM Doppio clic per iniziare a registrare una puntata.
REM Ospite, attesa e modelli si scelgono nel file .env.
cd /d "%~dp0"
if not exist .venv\Scripts\her.exe ( echo Prima installa: doppio clic su setup.bat & pause & exit /b 1 )
echo Parti pure quando vuoi.
echo.
echo   Per chiudere la puntata premi INVIO.
echo   NON usare Ctrl-C: chiude la finestra prima che il montaggio sia salvato.
echo.
.venv\Scripts\her.exe record
echo.
pause
