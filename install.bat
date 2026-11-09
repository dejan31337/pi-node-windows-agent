@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.10+ launcher not found. Install Python and enable Add Python to PATH.
  pause
  exit /b 1
)
py -3 --version
if errorlevel 1 (
  echo Python 3 is unavailable.
  pause
  exit /b 1
)
if not exist ".env" (
  echo Enter the same NODE_STATUS_TOKEN used in SoloHost. Input is hidden.
  py -3 -c "import getpass,pathlib; s=getpass.getpass('Windows helper token: ').strip(); pathlib.Path('.env').write_text('NODE_STATUS_TOKEN='+s+'\n' if s else '',encoding='utf-8')"
  if errorlevel 1 exit /b 1
)
findstr /b /c:"NODE_STATUS_TOKEN=" ".env" >nul
if errorlevel 1 (
  echo NODE_STATUS_TOKEN is missing from .env.
  pause
  exit /b 1
)
echo Setup complete. Run start.bat.
pause
