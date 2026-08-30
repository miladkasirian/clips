@echo off
rem  You have read output\<name>.review.txt and fixed what needed fixing.
rem  This carries on from there: speaks it, fits it, and builds the video.
setlocal
cd /d "%~dp0"
if not "%~1"=="" ( set "VIDEO=%~1" & goto go )
for /f "delims=" %%F in ('dir /b /o-d "input\*.mp4" 2^>nul') do (
  set "VIDEO=%~dp0input\%%F"
  goto go
)
echo.
echo   No video found. Drag the same .mp4 onto this file.
echo.
pause
exit /b 1

:go
echo.
python "%~dp0replacer.py" "%VIDEO%" --go
echo.
pause
