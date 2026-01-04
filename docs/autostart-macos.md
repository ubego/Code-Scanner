# Code Scanner Autostart - macOS

This guide explains how to configure Code Scanner to start automatically on macOS using the provided autostart script.

## Prerequisites

- Code Scanner installed and working via command line
- LLM backend (Ollama or LM Studio) installed

## Quick Setup

Run the autostart script:

```bash
./scripts/autostart-macos.sh
```

The script will interactively guide you through:

1. **Project path** - The directory to scan
2. **Config file path** - Your `config.toml` location
3. **Test launch** - Verifies the scanner works before registering
4. **LaunchAgent registration** - Creates a login item

## What the Script Does

1. **Detects legacy LaunchAgents** and offers to remove them
2. **Validates paths** for project and config file
3. **Test launches** the scanner to verify configuration
4. **Creates wrapper script** at `~/.code-scanner/launch-wrapper.sh`
5. **Creates LaunchAgent** at `~/Library/LaunchAgents/com.code-scanner.plist`
6. **Loads the agent** to start on login
7. **Includes 60-second delay** to allow LLM backend startup

## Managing the Service

```bash
# Check if running
launchctl list | grep code-scanner

# View logs
cat ~/.code-scanner/launchd-stdout.log
cat ~/.code-scanner/launchd-stderr.log

# Stop service
launchctl unload ~/Library/LaunchAgents/com.code-scanner.plist

# Start service
launchctl load ~/Library/LaunchAgents/com.code-scanner.plist

# Remove service completely
launchctl unload ~/Library/LaunchAgents/com.code-scanner.plist
rm ~/Library/LaunchAgents/com.code-scanner.plist
rm ~/.code-scanner/launch-wrapper.sh
```

## Log Files

- **Scanner log:** `~/.code-scanner/code_scanner.log`
- **Results:** `<project>/code_scanner_results.md`
- **LaunchAgent stdout:** `~/.code-scanner/launchd-stdout.log`
- **LaunchAgent stderr:** `~/.code-scanner/launchd-stderr.log`

## Troubleshooting

### Service won't start

1. Check logs: `cat ~/.code-scanner/launchd-stderr.log`
2. Verify config file path is correct
3. Ensure LLM backend is running
4. Check wrapper script is executable: `chmod +x ~/.code-scanner/launch-wrapper.sh`

### Lock file errors

Another instance may be running. Check with:

```bash
cat ~/.code-scanner/code_scanner.lock
ps aux | grep code-scanner
```

Delete stale lock if needed:

```bash
rm ~/.code-scanner/code_scanner.lock
```

### Permission issues

Ensure the wrapper script is executable:

```bash
chmod +x ~/.code-scanner/launch-wrapper.sh
```
