@echo off
REM Doppio clic (o trascina qui sopra il file musicale) per costruire la sigla.
cd /d "%~dp0"
if not exist .venv\Scripts\her.exe ( echo Prima installa: doppio clic su setup.bat & pause & exit /b 1 )
set "MUSICA=%~1"
if "%MUSICA%"=="" set /p MUSICA=Trascina qui il file musicale e premi Invio: 
if "%MUSICA%"=="" ( echo Nessun file indicato. & pause & exit /b 1 )
set /p FRASE=Frase che dice Nova sopra la musica (Invio per nessuna): 
if "%FRASE%"=="" (
  .venv\Scripts\her.exe sigla "%MUSICA%"
) else (
  .venv\Scripts\her.exe sigla "%MUSICA%" --voce "%FRASE%"
)
echo.
pause
