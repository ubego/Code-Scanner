# macOS Setup Guide

This guide covers setting up Code Scanner on macOS.

## Python Installation

### Using Homebrew (Recommended)

```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python
brew install python@3.12

# Verify installation
python3 --version  # Should be 3.10 or higher
```

### Using python.org Installer

1. Download from [python.org](https://www.python.org/downloads/macos/)
2. Run the installer
3. Follow the installation prompts

## UV Installation

```bash
# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh

# For Apple Silicon Macs, add to PATH if needed
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# Verify installation
uv --version
```

## Code Scanner Installation

```bash
# Clone the repository
git clone https://github.com/yourname/code-scanner.git
cd code-scanner

# Install dependencies with UV
uv sync

# Verify installation
uv run code-scanner --help
```

## LLM Backend Setup

Choose one of the following backends:

### Option 1: Ollama (Recommended for Apple Silicon)

Ollama runs natively on Apple Silicon and provides excellent performance.

```bash
# Install with Homebrew
brew install ollama

# Or download from https://ollama.ai/download

# Start Ollama (runs automatically after install)
ollama serve &

# Pull a model
ollama pull qwen3:4b

# For Apple Silicon, you can use larger models efficiently:
# ollama pull llama3:70b  # If you have 64GB+ RAM

# Verify it's working
ollama list
curl http://localhost:11434/api/tags
```

**Configuration for Ollama:**

Copy the [general example](../examples/config.toml) and update the `[llm]` section:

```toml
[llm]
backend = "ollama"
host = "localhost"
port = 11434
model = "qwen3:4b"
timeout = 120
context_limit = 8192
```

### Option 2: LM Studio

LM Studio provides a native macOS app with a great GUI.

1. Download from [lmstudio.ai](https://lmstudio.ai)
2. Open the `.dmg` file
3. Drag LM Studio to Applications
4. Launch LM Studio

**In LM Studio:**
1. Go to the "Models" tab
2. Download a model (e.g., TheBloke/Mistral-7B-Instruct-v0.2-GGUF)
3. Load the model
4. Go to "Local Server" tab
5. Click "Start Server" (default port: 1234)

**Configuration for LM Studio:**

Copy the [general example](../examples/config.toml) and update the `[llm]` section:

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

# Create config.toml
cp /path/to/code-scanner/examples/python-config.toml config.toml

# Run the scanner (runs continuously until Ctrl+C)
uv run code-scanner --config config.toml
```

## Apple Silicon Optimization

Apple Silicon Macs (M1/M2/M3) can run LLMs very efficiently:

### Ollama Performance Tips

```bash
# For M1/M2/M3 Macs with 16GB+ RAM, try larger models if needed:
ollama pull qwen3:4b      # Lightweight (Recommended)
ollama pull llama3.1:8b    # Latest version
ollama pull codellama:13b  # Better for code analysis

# Check GPU utilization
ollama ps
```

### LM Studio Performance Tips

- Use models optimized for Metal (Apple GPU)
- Enable GPU acceleration in settings
- Look for "GGUF" format models

## Running as a Background Service

### Using launchd

Create `~/Library/LaunchAgents/com.code-scanner.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.code-scanner</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/code-scanner/.venv/bin/python</string>
        <string>-m</string>
        <string>code_scanner</string>
        <string>--config</string>
        <string>/path/to/project/config.toml</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/project</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardErrorPath</key>
    <string>/tmp/code-scanner.err</string>
    <key>StandardOutPath</key>
    <string>/tmp/code-scanner.out</string>
</dict>
</plist>
```

```bash
# Load the service
launchctl load ~/Library/LaunchAgents/com.code-scanner.plist

# Check status
launchctl list | grep code-scanner

# View logs
tail -f /tmp/code-scanner.out
```

## Troubleshooting

### "python3: command not found"

```bash
# If using Homebrew Python
echo 'export PATH="/opt/homebrew/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### Ollama not starting automatically

```bash
# Check if Ollama is running
pgrep ollama

# Start manually
ollama serve

# Or restart the Ollama app
```

### Slow first model load

The first load downloads and initializes the model. Subsequent loads are faster.
Keep Ollama running in the background for best performance.

### "Cannot connect to backend" errors

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Check if LM Studio server is running
curl http://localhost:1234/v1/models
```

### Memory issues with large models

- Close memory-intensive applications
- Use smaller quantized models (Q4_K_M instead of Q8)
- Monitor memory with Activity Monitor
