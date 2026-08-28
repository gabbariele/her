@echo off
REM Doppio clic per RIPRENDERE l'ultima puntata: l'ospite si ricorda tutto
REM quello che vi siete detti, e l'audio si aggiunge in coda a quello di prima.
cd /d "%~dp0"
if not exist .venv\Scripts\her.exe ( echo Prima installa: doppio clic su setup.bat & pause & exit /b 1 )
echo Riprendo l'ultima puntata registrata.
echo.
echo   Per chiudere premi INVIO. NON usare Ctrl-C.
echo.
.venv\Scripts\her.exe record --continua
echo.
pause
