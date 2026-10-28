@echo off
setlocal
cd /d "%~dp0"
py -3 main.py
if errorlevel 1 (
  echo.
  echo Abyssal Choir did not exit cleanly. Read the error text above.
  pause
)
endlocal
