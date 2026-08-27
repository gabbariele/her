@echo off
REM Doppio clic: dice cosa c'e' dentro l'ultima puntata e cosa farebbe il montaggio.
REM Utile da incollare quando qualcosa non torna.
cd /d "%~dp0"
if not exist .venv\Scripts\her.exe ( echo Prima installa: doppio clic su setup.bat & pause & exit /b 1 )
.venv\Scripts\her.exe analizza %*
echo.
pause
