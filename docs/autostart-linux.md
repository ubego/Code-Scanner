# Code Scanner Autostart - Linux

This guide explains how to configure Code Scanner to start automatically on Linux using the provided autostart script.

## Prerequisites

- Code Scanner installed and working via command line
- systemd user services available (most modern Linux distributions)
- LLM backend (Ollama or LM Studio) installed

## Quick Setup

Run the autostart script:

```bash
./scripts/autostart-linux.sh
```

The script will interactively guide you through:

1. **Project path** - The directory to scan
2. **Config file path** - Your `config.toml` location
3. **Test launch** - Verifies the scanner works before registering
4. **Service registration** - Creates a systemd user service

## What the Script Does

1. **Detects legacy services** and offers to remove them
2. **Validates paths** for project and config file
3. **Test launches** the scanner to verify configuration
4. **Creates systemd service** at `~/.config/systemd/user/code-scanner.service`
5. **Enables autostart** on user login
6. **Includes 60-second delay** to allow LLM backend startup

## Managing the Service

```bash
# Check status
systemctl --user status code-scanner

# View logs
journalctl --user -u code-scanner -f

# Stop service
systemctl --user stop code-scanner

# Restart service
systemctl --user restart code-scanner

# Disable autostart
systemctl --user disable code-scanner

# Remove service completely
systemctl --user stop code-scanner
systemctl --user disable code-scanner
rm ~/.config/systemd/user/code-scanner.service
systemctl --user daemon-reload
```

## Log Files

- **Scanner log:** `~/.code-scanner/code_scanner.log`
- **Results:** `<project>/code_scanner_results.md`
- **systemd logs:** `journalctl --user -u code-scanner`

## Troubleshooting

### Service won't start

1. Check logs: `journalctl --user -u code-scanner -f`
2. Verify config file path is correct
3. Ensure LLM backend is running
4. Try increasing the startup delay in the service file

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

### User services not working

Enable lingering for your user:

```bash
loginctl enable-linger $USER
```
