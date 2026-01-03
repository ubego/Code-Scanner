# Linux Setup Guide

This guide covers setting up Code Scanner on Linux distributions.

## Python Installation

### Ubuntu/Debian

```bash
# Update package list
sudo apt update

# Install Python 3.10+
sudo apt install python3 python3-pip python3-venv

# Verify installation
python3 --version  # Should be 3.10 or higher
```

### Fedora

```bash
# Install Python
sudo dnf install python3 python3-pip

# Verify installation
python3 --version
```

### Arch Linux

```bash
# Install Python
sudo pacman -S python python-pip

# Verify installation
python --version
```

## UV Installation

UV is the recommended package manager:

```bash
# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh

# Add to PATH (if not automatic)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Verify installation
uv --version
```

## Code Scanner Installation

```bash
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

### Option 1: Ollama (Recommended)

Ollama is lightweight and easy to use on Linux.

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Start Ollama (runs as a service on most distros)
ollama serve &

# Pull a model
ollama pull qwen3:4b

# Verify it's working
ollama list
curl http://localhost:11434/api/tags
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
context_limit = 16384
```

### Option 2: LM Studio

LM Studio provides a GUI and is great for trying different models.

```bash
# Download the AppImage from https://lmstudio.ai
# Example for version 0.3.x:
wget https://releases.lmstudio.ai/linux/x86_64/LM-Studio-x.x.x.AppImage

# Make it executable
chmod +x LM-Studio-*.AppImage

# Run LM Studio
./LM-Studio-*.AppImage
```

**In LM Studio:**
1. Search for "qwen2.5-coder-7b-instruct"
2. Download the model
3. Load the model
4. Go to "Local Server" tab (click the "<->" icon)
5. Click "Start Server" (default port: 1234)

**Configuration for LM Studio:**

Copy a language-specific example (e.g., `examples/python-config.toml`) and update the `[llm]` section:

```toml
[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
timeout = 120
```

## Running Code Scanner

```bash
# Navigate to your project
cd /path/to/your/project

# Create config.toml (see examples/)
cp /path/to/code-scanner/examples/python-config.toml config.toml

# Run the scanner (runs continuously until Ctrl+C)
uv run code-scanner --config config.toml
```

## Running as a Background Service

### Using systemd (User Service)

Create `~/.config/systemd/user/code-scanner.service`:

```ini
[Unit]
Description=Code Scanner
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/your/project
ExecStart=/path/to/code-scanner/.venv/bin/python -m code_scanner --config config.toml
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
# Enable and start
systemctl --user enable code-scanner
systemctl --user start code-scanner

# View logs
journalctl --user -u code-scanner -f
```

## Troubleshooting

### "Permission denied" for Ollama

```bash
# Add yourself to the ollama group
sudo usermod -aG ollama $USER

# Log out and back in, or:
newgrp ollama
```

### LM Studio AppImage won't run

```bash
# Install FUSE (required for AppImages)
# Ubuntu/Debian:
sudo apt install fuse libfuse2

# Fedora:
sudo dnf install fuse fuse-libs
```

### Out of memory errors

Large models require significant RAM. Try:
- Use a smaller model (7B instead of 13B)
- Close other applications
- Use Ollama's memory-efficient quantized models

### Slow model loading

First load is slow due to model loading. Subsequent queries are faster.
Consider keeping Ollama running as a service.
