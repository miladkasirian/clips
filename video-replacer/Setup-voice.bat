@echo off
rem  Only needed if you want a voice cloned from a recording.
rem  Everything else works without this.
setlocal
cd /d "%~dp0"
echo.
echo   Installing the local voice model. This is a few gigabytes and takes a while.
echo   It all goes in .venv\ inside this folder - nothing else on your PC is touched.
echo.
if not exist "%~dp0.venv\Scripts\python.exe" python -m venv "%~dp0.venv"
"%~dp0.venv\Scripts\python.exe" -m pip install --upgrade pip
rem  torch 2.8 on purpose: 2.9 wants torchcodec, which needs ffmpeg DLLs that the
rem  static Windows build of ffmpeg does not ship.
"%~dp0.venv\Scripts\python.exe" -m pip install "torch==2.8.0" "torchaudio==2.8.0"
"%~dp0.venv\Scripts\python.exe" -m pip install coqui-tts "transformers<5"
echo.
echo   Done. Open the app, go to the Voice tab, and press "Add a voice".
echo.
pause
