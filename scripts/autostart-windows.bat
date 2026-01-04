@echo off
REM Code Scanner Autostart Management - Windows (Task Scheduler)
REM Usage: autostart-windows.bat [install|remove|status] [config_path] [target_directory]

setlocal enabledelayedexpansion

set "TASK_NAME=CodeScanner"
set "SCRIPT_DIR=%~dp0"

if "%~1"=="" goto :usage
if "%~1"=="install" goto :install
if "%~1"=="remove" goto :remove
if "%~1"=="status" goto :status
goto :usage

:usage
echo Code Scanner Autostart Management - Windows
echo.
echo Usage: %~nx0 ^<command^> [options]
echo.
echo Commands:
echo   install ^<config_path^> ^<target_directory^>  Install autostart task
echo   remove                                      Remove autostart task
echo   status                                      Check task status
echo.
echo Examples:
echo   %~nx0 install C:\path\to\config.toml C:\path\to\project
echo   %~nx0 remove
echo   %~nx0 status
exit /b 1

:install
if "%~2"=="" (
    echo [ERROR] Missing config_path argument
    goto :usage
)
if "%~3"=="" (
    echo [ERROR] Missing target_directory argument
    goto :usage
)

set "CONFIG_PATH=%~f2"
set "TARGET_DIR=%~f3"

REM Verify files exist
if not exist "%CONFIG_PATH%" (
    echo [ERROR] Config file not found: %CONFIG_PATH%
    exit /b 1
)
if not exist "%TARGET_DIR%\" (
    echo [ERROR] Target directory not found: %TARGET_DIR%
    exit /b 1
)

REM Find code-scanner
set "SCANNER_CMD="
where code-scanner >nul 2>&1 && set "SCANNER_CMD=code-scanner"
if "%SCANNER_CMD%"=="" (
    where uv >nul 2>&1 && set "SCANNER_CMD=uv run code-scanner"
)
if "%SCANNER_CMD%"=="" (
    echo [ERROR] Could not find code-scanner or uv. Please install code-scanner first.
    exit /b 1
)

echo [INFO] Testing code-scanner launch...
echo [INFO] Command: %SCANNER_CMD% --config "%CONFIG_PATH%" "%TARGET_DIR%"
echo.

REM Test launch (run for a few seconds)
timeout /t 5 /nobreak >nul 2>&1
start /b cmd /c "%SCANNER_CMD% --config "%CONFIG_PATH%" "%TARGET_DIR%" 2>&1 | head -20"
timeout /t 5 /nobreak >nul 2>&1

echo.
set /p "RESPONSE=Did the test launch succeed? (y/N): "
if /i not "%RESPONSE%"=="y" (
    echo [ERROR] Test launch failed or was declined. Fix configuration before installing.
    exit /b 1
)
echo [SUCCESS] Test launch verified.

REM Check for existing task
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if not errorlevel 1 (
    echo [WARNING] Found existing autostart task.
    set /p "REPLACE=Replace existing configuration? (y/N): "
    if /i not "!REPLACE!"=="y" (
        echo [INFO] Installation cancelled.
        exit /b 0
    )
    echo [INFO] Removing existing task...
    schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
)

REM Create wrapper script with 60-second delay
set "HOME_DIR=%USERPROFILE%\.code-scanner"
if not exist "%HOME_DIR%" mkdir "%HOME_DIR%"

set "WRAPPER_SCRIPT=%HOME_DIR%\launch-wrapper.bat"
(
    echo @echo off
    echo REM Code Scanner launch wrapper with startup delay
    echo timeout /t 60 /nobreak ^>nul
    echo %SCANNER_CMD% --config "%CONFIG_PATH%" "%TARGET_DIR%"
) > "%WRAPPER_SCRIPT%"

REM Create scheduled task to run at logon
echo [INFO] Creating scheduled task...
schtasks /create /tn "%TASK_NAME%" /tr "\"%WRAPPER_SCRIPT%\"" /sc onlogon /rl highest /f

if errorlevel 1 (
    echo [ERROR] Failed to create scheduled task.
    exit /b 1
)

echo [SUCCESS] Code Scanner autostart installed successfully!
echo.
echo [INFO] Useful commands:
echo   schtasks /query /tn "%TASK_NAME%"         # Check status
echo   schtasks /run /tn "%TASK_NAME%"           # Start manually
echo   schtasks /end /tn "%TASK_NAME%"           # Stop task
echo   schtasks /delete /tn "%TASK_NAME%" /f     # Remove task
exit /b 0

:remove
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if errorlevel 1 (
    echo [WARNING] No autostart task found.
    exit /b 0
)

echo [INFO] Ending task if running...
schtasks /end /tn "%TASK_NAME%" >nul 2>&1

echo [INFO] Removing scheduled task...
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

echo [INFO] Removing wrapper script...
del "%USERPROFILE%\.code-scanner\launch-wrapper.bat" >nul 2>&1

echo [SUCCESS] Code Scanner autostart removed.
exit /b 0

:status
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if errorlevel 1 (
    echo [WARNING] No autostart task configured.
    exit /b 0
)

echo [INFO] Scheduled task status:
schtasks /query /tn "%TASK_NAME%" /v /fo list
exit /b 0
