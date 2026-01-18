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

## Git Installation

Git is usually pre-installed on macOS. If not:

```bash
# Install Git using Homebrew
brew install git

# Verify installation
git --version
```

Or install Xcode Command Line Tools:

```bash
xcode-select --install
```

## Universal Ctags Installation

Universal Ctags is required for symbol indexing, which enables AI tools to efficiently navigate your codebase.

```bash
# Install using Homebrew
brew install universal-ctags

# Verify installation (should show "Universal Ctags")
ctags --version
```

> **Note**: Make sure it's "Universal Ctags" (not "Exuberant Ctags"). The macOS built-in `ctags` is Exuberant, so always use Homebrew's version.

## Ripgrep Installation

Ripgrep is required for fast code search across the repository.

```bash
# Install using Homebrew
brew install ripgrep

# Verify installation
rg --version
```

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
git clone https://github.com/ubego/Code-Scanner.git
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

LM Studio provides a native macOS app with a great GUI.

1. Download from [lmstudio.ai](https://lmstudio.ai)
2. Open the `.dmg` file
3. Drag LM Studio to Applications
4. Launch LM Studio

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

Use the provided autostart script for easy setup:

```bash
./scripts/autostart-macos.sh
```

See **[Autostart Guide](autostart-macos.md)** for detailed instructions.

The script creates a LaunchAgent with:
- 60-second startup delay for LLM backend
- Automatic lock file cleanup
- Log files in `~/.code-scanner/`

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
