@echo off
rem  Rebuild "Course Video Replacer.exe" after changing app.pyw or replacer.py.
rem  You only need this if you edit the code. Using the app never needs it.
setlocal
cd /d "%~dp0"
if not exist "_build\.venv\Scripts\python.exe" (
  echo   preparing the build environment, once...
  python -m venv "_build\.venv"
  "_build\.venv\Scripts\python.exe" -m pip install -q --upgrade pip pyinstaller
)
copy /y app.pyw    "_build\app_main.py" >nul
copy /y replacer.py "_build\replacer.py" >nul
cd _build
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name CourseVideoReplacer --distpath dist --workpath work --specpath . ^
  --exclude-module torch --exclude-module TTS --exclude-module numpy ^
  --exclude-module matplotlib --exclude-module scipy --exclude-module pandas ^
  app_main.py
cd ..
copy /y "_build\dist\CourseVideoReplacer.exe" "Course Video Replacer.exe" >nul
echo.
echo   Done: "Course Video Replacer.exe"
echo.
pause
