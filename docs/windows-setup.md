# Windows Setup Guide

This guide covers setting up Code Scanner on Windows.

## Python Installation

### Option 1: Microsoft Store (Recommended for beginners)

1. Open Microsoft Store
2. Search for "Python 3.12"
3. Click "Install"
4. Open PowerShell and verify: `python --version`

### Option 2: python.org Installer

1. Download from [python.org](https://www.python.org/downloads/windows/)
2. Run the installer
3. **Important**: Check "Add Python to PATH" during installation
4. Complete installation

### Verify Installation

Open PowerShell or Command Prompt:

```powershell
python --version   # Should be 3.10 or higher
pip --version
```

## UV Installation

Open PowerShell as Administrator:

```powershell
# Install UV
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Restart PowerShell, then verify
uv --version
```

## Git Installation

If Git isn't already installed:

1. Download from [git-scm.com](https://git-scm.com/download/win)
2. Run the installer
3. Use default options (Git Bash is recommended)

## Code Scanner Installation

Open PowerShell or Git Bash:

```powershell
# Clone the repository
git clone https://github.com/ubego/Code-Scanner.git
cd code-scanner

# Install dependencies with UV
uv sync

# Verify installation
uv run code-scanner --help
```

## LLM Backend Setup

Choose one of the following backends:

### Option 1: Ollama

Ollama now supports Windows natively.

1. Download from [ollama.ai/download](https://ollama.ai/download)
2. Run the installer
3. Ollama starts automatically

Open PowerShell:

```powershell
# Pull a model
ollama pull qwen3:4b

# Verify it's working
ollama list

# Test the API
curl http://localhost:11434/api/tags
# Or with PowerShell:
Invoke-WebRequest http://localhost:11434/api/tags
```

**Configuration for Ollama:**

Copy a language-specific example (e.g., `examples/python-config.toml`) and update the `[llm]` section:

```toml
[llm]
backend = "ollama"
host = "localhost"
port = 11434
model = "qwen3:4b"
timeout = 120
context_limit = 16384  # Required
```

### Option 2: LM Studio

LM Studio provides a user-friendly Windows application.

1. Download from [lmstudio.ai](https://lmstudio.ai)
2. Run the installer
3. Launch LM Studio

**In LM Studio:**
1. Search for "qwen2.5-coder-7b-instruct"
2. Download the model
3. Load the model
4. Go to "Local Server" tab (click the "<->" icon)
5. **Set "Context Length" to at least 16384** in the right sidebar
6. Click "Start Server" (default port: 1234)

**Configuration for LM Studio:**

Copy a language-specific example (e.g., `examples/python-config.toml`) and update the `[llm]` section:

```toml
[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
timeout = 120
context_limit = 16384  # Required
```

## Running Code Scanner

### Using PowerShell

```powershell
# Navigate to your project
cd C:\path\to\your\project

# Create config.toml (copy from examples)
Copy-Item C:\path\to\code-scanner\examples\python-config.toml config.toml

# Edit config.toml with your preferred editor
notepad config.toml

# Run the scanner (runs continuously until Ctrl+C)
uv run code-scanner --config config.toml
```

### Using Git Bash

```bash
# Navigate to your project
cd /c/path/to/your/project

# Create config.toml
cp /c/path/to/code-scanner/examples/python-config.toml config.toml

# Run the scanner
uv run code-scanner --config config.toml
```

### Using Command Prompt (cmd)

```cmd
:: Navigate to your project
cd C:\path\to\your\project

:: Run the scanner
uv run code-scanner --config config.toml
```

## GPU Acceleration

### NVIDIA GPUs

LM Studio and Ollama can use NVIDIA GPUs for faster inference:

1. Install [NVIDIA CUDA Toolkit](https://developer.nvidia.com/cuda-toolkit)
2. Install latest [NVIDIA drivers](https://www.nvidia.com/Download/index.aspx)
3. In LM Studio, enable GPU acceleration in settings
4. Ollama automatically uses CUDA if available

### AMD GPUs

- LM Studio supports AMD GPUs via ROCm
- Ollama support for AMD is limited on Windows

## Running as a Windows Service

Use the provided autostart script for easy setup:

```batch
scripts\autostart-windows.bat
```

See **[Autostart Guide](autostart-windows.md)** for detailed instructions.

The script creates a Task Scheduler task with:
- 60-second startup delay for LLM backend
- Automatic lock file cleanup
- Log files in `%USERPROFILE%\.code-scanner\`

## Troubleshooting

### "python is not recognized"

Python isn't in your PATH. Either:
- Reinstall Python with "Add to PATH" checked
- Add Python manually to PATH:
  1. Search "Environment Variables" in Start
  2. Edit PATH
  3. Add Python installation directory (e.g., `C:\Users\YourName\AppData\Local\Programs\Python\Python312`)

### "uv is not recognized"

Restart PowerShell after UV installation. If still not working:

```powershell
# Check UV location
$env:USERPROFILE\.local\bin\uv.exe --version

# Add to PATH manually
$env:PATH += ";$env:USERPROFILE\.local\bin"
```

### Firewall blocking connections

Windows Firewall may block LLM backends:

1. Open Windows Security
2. Firewall & network protection
3. Allow an app through firewall
4. Add LM Studio or Ollama

### Antivirus interference

Some antivirus software may slow down or block the scanner:
- Add code-scanner directory to exclusions
- Add LM Studio/Ollama to exclusions

### Long path issues

If you see path-related errors:

1. Open Group Policy Editor (gpedit.msc)
2. Navigate to: Computer Configuration > Administrative Templates > System > Filesystem
3. Enable "Enable Win32 long paths"
4. Restart your computer

### PowerShell script execution policy

If you see "execution of scripts is disabled":

```powershell
# Run as Administrator
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Connection refused errors

```powershell
# Check if Ollama is running
Get-Process ollama

# Check if LM Studio server is running
Test-NetConnection -ComputerName localhost -Port 1234

# For Ollama
Test-NetConnection -ComputerName localhost -Port 11434
```
