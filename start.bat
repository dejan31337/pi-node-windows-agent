@echo off
setlocal
cd /d "%~dp0"
if not exist ".env" (
  echo Missing .env. Run install.bat first.
  pause
  exit /b 1
)
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
  if "%%A"=="NODE_STATUS_TOKEN" set "NODE_STATUS_TOKEN=%%B"
  if "%%A"=="PI_NODE_CONTAINER" set "PI_NODE_CONTAINER=%%B"
  if "%%A"=="AGENT_HOST" set "AGENT_HOST=%%B"
  if "%%A"=="AGENT_PORT" set "AGENT_PORT=%%B"
)
if "%NODE_STATUS_TOKEN%"=="" (
  echo NODE_STATUS_TOKEN is missing.
  pause
  exit /b 1
)
py -3 windows-agent.py
pause
