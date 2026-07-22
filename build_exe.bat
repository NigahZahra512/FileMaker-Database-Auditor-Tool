@echo off
REM ============================================================
REM build_exe.bat
REM Builds FileMakerAuditor.exe from the FastAPI backend + the
REM static frontend, so it can be sent to someone who doesn't
REM have Python or Docker installed -- they just double-click it.
REM
REM RUN THIS ON WINDOWS, from the project root folder (same
REM folder as this .bat file, backend\, and frontend\).
REM ============================================================

echo Installing build requirements (this only needs to happen once)...
pip install -r requirements.txt
pip install pyinstaller

echo.
echo Building FileMakerAuditor.exe ...
pyinstaller --noconfirm --onefile --console ^
    --name FileMakerAuditor ^
    --add-data "frontend;frontend" ^
    --hidden-import=anthropic ^
    --hidden-import=google.generativeai ^
    --hidden-import=openai ^
    --hidden-import=sqlalchemy ^
    backend\main.py

echo.
echo ============================================================
echo Done. Your .exe is at: dist\FileMakerAuditor.exe
echo Send that ONE file to User -- double-clicking it starts the
echo server and opens the app in his default browser automatically.
echo (First launch may take a few seconds longer while it unpacks.)
echo ============================================================
pause
