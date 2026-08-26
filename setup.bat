@echo off
REM Installazione automatica di her (Windows). Doppio clic su questo file.
cd /d "%~dp0"
echo.
echo === Installazione di her ===
echo Ci vogliono un paio di minuti.
echo.

echo [1/4] Cerco Python...
py -3 --version >nul 2>&1
if errorlevel 1 (
  python --version >nul 2>&1
  if errorlevel 1 (
    echo    Python non trovato.
    echo    Scaricalo da https://www.python.org/downloads/
    echo    IMPORTANTE: durante l'installazione spunta "Add Python to PATH".
    echo    Poi richiudi tutto e rilancia questo file.
    pause
    exit /b 1
  )
  set "PY=python"
) else (
  set "PY=py -3"
)
%PY% --version

echo.
echo [2/4] Preparo l'ambiente...
if not exist .venv (
  %PY% -m venv .venv
  if errorlevel 1 ( echo    Creazione ambiente fallita. & pause & exit /b 1 )
)

echo.
echo [3/4] Scarico i componenti necessari...
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.venv\Scripts\python.exe -m pip install -e ".[audio]" --quiet
if errorlevel 1 ( echo    Installazione fallita (connessione?). & pause & exit /b 1 )

echo.
echo [4/4] File delle chiavi...
if not exist .env copy .env.example .env >nul

echo.
echo === Installazione completata ===
echo.
echo Adesso:
echo   1. apri il file .env in questa cartella e incolla le tue chiavi API
echo   2. doppio clic su verifica.bat
echo.
echo Tutto spiegato in INSTALLA.md
pause
