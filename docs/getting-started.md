# Getting Started with Code Scanner

Code Scanner is an AI-powered code analysis tool that uses local LLMs (Large Language Models) to detect issues, suggest improvements, and enforce coding standards in your codebase.

## Features

- 🔍 **AI-Powered Analysis** - Uses LLMs to understand code context and find issues
- 🏠 **100% Local** - All processing happens on your machine, no cloud required
- ⚡ **Real-time Scanning** - Watch mode detects and analyzes file changes instantly
- 🔧 **Customizable Checks** - Define checks in plain English
- 📊 **Multiple Output Formats** - Terminal display and JSON export
- 🔌 **Multiple Backends** - Supports LM Studio and Ollama

## Prerequisites

Before installing Code Scanner, ensure you have:

1. **Python 3.10 or higher**
2. **Git** (for tracking file changes)
3. **An LLM Backend** - one of:
   - [LM Studio](https://lmstudio.ai) - GUI-based, great for beginners
   - [Ollama](https://ollama.ai) - CLI-based, lightweight and simple

## Quick Installation

We recommend using [UV](https://docs.astral.sh/uv/) for dependency management:

```bash
# Install UV (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/yourname/code-scanner.git
cd code-scanner

# Install dependencies
uv sync
```

## Configuration

The easiest way to configure Code Scanner is to copy one of the language-specific examples from the `examples/` directory to your project root as `config.toml`.

```bash
# Example: If you are working on a Python project
cp /path/to/code-scanner/examples/python-config.toml config.toml

# Example: If you are working on a JavaScript/TypeScript project
cp /path/to/code-scanner/examples/javascript-config.toml config.toml
```

### Available Examples

- **[examples/python-config.toml](../examples/python-config.toml)** - Python projects
- **[examples/javascript-config.toml](../examples/javascript-config.toml)** - JavaScript/TypeScript projects
- **[examples/java-config.toml](../examples/java-config.toml)** - Java projects
- **[examples/cpp-config.toml](../examples/cpp-config.toml)** - C++ projects
- **[examples/cpp-qt-config.toml](../examples/cpp-qt-config.toml)** - C++ with Qt framework
- **[examples/android-config.toml](../examples/android-config.toml)** - Android (Java + Kotlin)
- **[examples/ios-macos-config.toml](../examples/ios-macos-config.toml)** - iOS/macOS (Swift + Obj-C)
- **[examples/config.toml](../examples/config.toml)** - General purpose template

After copying, open `config.toml` and ensure the `[llm]` section matches your backend (Ollama or LM Studio).

## Running Your First Scan

1. **Start your LLM backend**

   For Ollama:
   ```bash
   # Pull a model (first time only)
   ollama pull qwen3:4b
   
   # Start Ollama (often runs automatically)
   ollama serve
   ```

   For LM Studio:
   - Open LM Studio
   - Download and load a model
   - Start the local server (default port: 1234)

2. **Run the scanner**

   ```bash
   # From the code-scanner directory
   uv run code-scanner --config /path/to/your/project/config.toml
   ```

3. **View results**

   Results are displayed in the terminal and saved to `code-scanner-results.json` (configurable).

## Continuous Scanning

The scanner automatically runs in continuous mode:
- Monitors for Git changes every 30 seconds
- Automatically analyzes modified files
- Displays issues in real-time
- Loops through all checks indefinitely

Press `Ctrl+C` to stop the scanner.

## Next Steps

- **Platform-specific setup**: See [Linux](linux-setup.md), [macOS](macos-setup.md), or [Windows](windows-setup.md)
- **Learn about backends**: [LM Studio docs](https://lmstudio.ai/docs/basics) | [Ollama docs](https://ollama.ai)
- **Customize checks**: See example configs in `examples/`

## Troubleshooting

### "Cannot connect to LLM backend"

1. Ensure your LLM backend is running
2. Check the host and port in your config match the running server
3. For Ollama, verify with: `curl http://localhost:11434/api/tags`
4. For LM Studio, verify with: `curl http://localhost:1234/v1/models`

### "Model not found" (Ollama)

1. Pull the model: `ollama pull model-name`
2. List available models: `ollama list`
3. Update your config with a model that exists

### "Context length exceeded"

1. Use a model with larger context window
2. Reduce `context_limit` in your config to force smaller batches
3. Use `.gitignore` to exclude large generated files from version control

### For more help

- Check the full documentation in `docs/`
- Open an issue on GitHub
