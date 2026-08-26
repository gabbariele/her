@echo off
REM Doppio clic: apre gli appunti della puntata e poi mostra cosa ne ricava l'ospite.
cd /d "%~dp0"
if not exist .venv\Scripts\her.exe ( echo Prima installa: doppio clic su setup.bat & pause & exit /b 1 )
if not exist contesto.md .venv\Scripts\her.exe contesto
echo Si apre il Blocco note: scrivi il contesto della puntata, salva (Ctrl+S) e chiudilo.
echo.
notepad contesto.md
echo.
echo Preparo il materiale (scarico e riassumo i link)...
echo.
.venv\Scripts\her.exe contesto
echo.
pause
