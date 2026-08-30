@echo off
rem  Drag an .mp4 onto this file. Or double-click it to use the newest mp4 in input\
setlocal
cd /d "%~dp0"
if "%~1"=="" goto pickone
set "VIDEO=%~1"
goto go

:pickone
set "VIDEO="
for /f "delims=" %%F in ('dir /b /o-d "input\*.mp4" 2^>nul') do (
  set "VIDEO=%~dp0input\%%F"
  goto go
)
echo.
echo   Put an .mp4 in the input folder, or drag one onto this file.
echo.
pause
exit /b 1

:go
echo.
python "%~dp0replacer.py" "%VIDEO%"
echo.
pause
