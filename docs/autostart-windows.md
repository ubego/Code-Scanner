# Code Scanner Autostart - Windows

This guide explains how to configure Code Scanner to start automatically on Windows using the provided autostart script.

## Prerequisites

- Code Scanner installed and working via command line
- LLM backend (Ollama or LM Studio) installed
- PowerShell or Command Prompt with administrator access (for some operations)

## Quick Setup

Run the autostart script by double-clicking or from Command Prompt:

```batch
scripts\autostart-windows.bat
```

The script will interactively guide you through:

1. **Project path** - The directory to scan
2. **Config file path** - Your `config.toml` location
3. **Test launch** - Verifies the scanner works before registering
4. **Task Scheduler registration** - Creates a login task

## What the Script Does

1. **Detects legacy tasks** and offers to remove them
2. **Validates paths** for project and config file
3. **Test launches** the scanner to verify configuration
4. **Creates wrapper script** at `%USERPROFILE%\.code-scanner\launch-wrapper.bat`
5. **Creates scheduled task** named "CodeScanner" via Task Scheduler
6. **Configures login trigger** to start on user logon
7. **Includes 60-second delay** to allow LLM backend startup

## Managing the Service

```batch
REM Check status
schtasks /query /tn "CodeScanner"

REM Run manually
schtasks /run /tn "CodeScanner"

REM Stop
schtasks /end /tn "CodeScanner"

REM Remove completely
schtasks /delete /tn "CodeScanner" /f
del "%USERPROFILE%\.code-scanner\launch-wrapper.bat"
```

## Log Files

- **Scanner log:** `%USERPROFILE%\.code-scanner\code_scanner.log`
- **Results:** `<project>\code_scanner_results.md`

## Using Task Scheduler GUI

You can also manage the task via the graphical interface:

1. Press `Win + R`, type `taskschd.msc`, press Enter
2. Find "CodeScanner" in the task list
3. Right-click to Run, End, Disable, or Delete

## Troubleshooting

### Task won't start

1. Check scanner log: `type %USERPROFILE%\.code-scanner\code_scanner.log`
2. Verify config file path is correct
3. Ensure LLM backend is running
4. Open Task Scheduler and check the task's "History" tab

### Lock file errors

Another instance may be running. Check with:

```batch
type %USERPROFILE%\.code-scanner\code_scanner.lock
tasklist | findstr code-scanner
```

Delete stale lock if needed:

```batch
del %USERPROFILE%\.code-scanner\code_scanner.lock
```

### Permission issues

If the task fails to create, try running Command Prompt as Administrator:

1. Right-click Command Prompt
2. Select "Run as administrator"
3. Navigate to the code-scanner directory
4. Run the autostart script again
