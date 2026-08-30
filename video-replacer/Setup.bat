@echo off
rem  Run this once. It gets ffmpeg and checks the key.
setlocal
cd /d "%~dp0"
echo.
echo   Course Video Replacer - setup
echo.

where ffmpeg >nul 2>nul
if %errorlevel%==0 (
  echo   ffmpeg  : already installed
  goto keycheck
)
if exist "%~dp0ffmpeg\bin\ffmpeg.exe" (
  echo   ffmpeg  : already here
  goto keycheck
)

echo   ffmpeg  : not found, fetching it...
where winget >nul 2>nul
if %errorlevel%==0 (
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  where ffmpeg >nul 2>nul
  if %errorlevel%==0 (
    echo   ffmpeg  : installed. CLOSE this window and open a new one so Windows sees it.
    goto keycheck
  )
)

echo   winget could not do it - fetching the portable build instead
powershell -NoProfile -Command ^
  "$ErrorActionPreference='Stop'; $u='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip';" ^
  "Invoke-WebRequest $u -OutFile ffmpeg.zip;" ^
  "Expand-Archive ffmpeg.zip -DestinationPath _ff -Force;" ^
  "$d=(Get-ChildItem _ff -Directory | Select-Object -First 1).FullName;" ^
  "Move-Item $d ffmpeg -Force; Remove-Item _ff,ffmpeg.zip -Recurse -Force"
if exist "%~dp0ffmpeg\bin\ffmpeg.exe" (
  echo   ffmpeg  : unpacked into this folder
) else (
  echo   ffmpeg  : FAILED. Install it yourself, then run this again.
)

:keycheck
echo.
if exist "%~dp0key.txt" (
  echo   key.txt : found
) else (
  echo   key.txt : MISSING
  echo             Make a file called key.txt in this folder with your OpenAI key
  echo             on one line. It stays on this computer - it is never committed.
)
if not exist "%~dp0input"  mkdir "%~dp0input"
if not exist "%~dp0output" mkdir "%~dp0output"
echo.
echo   Ready. Drag an .mp4 onto Replace.bat
echo.
pause
