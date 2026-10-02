@echo off
REM Sync agency-agents Cursor rules from https://github.com/msitarzewski/agency-agents
setlocal
cd /d "%~dp0.."

set REPO=%~dp0..\..\agency-agents
if not exist "%REPO%\.git" (
    echo Clonando agency-agents...
    git clone --depth 1 https://github.com/msitarzewski/agency-agents.git "%REPO%"
    if errorlevel 1 exit /b 1
) else (
    echo Actualizando agency-agents...
    git -C "%REPO%" pull --ff-only
    if errorlevel 1 exit /b 1
)

python scripts\install_agency_cursor_rules.py "%REPO%" ".cursor\rules"
exit /b %ERRORLEVEL%
