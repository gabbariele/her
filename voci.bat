@echo off
REM Doppio clic: elenca le voci ElevenLabs con il loro id.
cd /d "%~dp0"
if not exist .venv\Scripts\her.exe ( echo Prima installa: doppio clic su setup.bat & pause & exit /b 1 )
.venv\Scripts\her.exe voices
echo.
echo Copia l'id della voce che ti piace e incollalo nel file .env, alla riga HER_VOICE_ID=
echo.
pause
