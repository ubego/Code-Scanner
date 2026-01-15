# Code Scanner

![Code Scanner Banner](images/banner.png)

AI-powered code scanner that uses local LLMs (LM Studio or Ollama) to identify issues in your codebase based on configurable checks. **Your code never leaves your machine.**

---

⭐ **Star this project on GitHub to support its development!** [Code-Scanner on GitHub](https://github.com/ubego/Code-Scanner)

---


## Features

- 🏠 **100% Local (Privacy first)**: Uses LM Studio or Ollama with local APIs. All processing happens on your machine, no cloud required.
- 🖥️ **Hardware Efficient**: Designed for small local models. Runs comfortably on consumer GPUs like **NVIDIA RTX 3060**.
- 💰 **Cost Effective**: Zero token costs. Use your local resources instead of expensive API subscriptions.
- 🔍 **Language-agnostic**: Works with any programming language.
- 🧰 **AI Tools for Context Expansion**: LLM can interactively request additional codebase information (find usages, read files, list directories) for sophisticated architectural checks.
- ⚡ **Continuous Monitoring**: Runs in background mode, monitoring Git changes every 30 seconds and scanning indefinitely until stopped.
- 🔄 **Smart Change Detection**: When changes are detected mid-scan, continues from current check with refreshed file contents (preserves progress).
- 🔧 **Configurable Checks**: Define checks in plain English via TOML configuration with file pattern support.
- 📊 **Issue Tracking**: Tracks issue lifecycle (new, existing, resolved).
- 📝 **Real-time Updates**: Output file updates immediately when issues are found (not just at end of scan).
- 🤖 **Daemon-Ready**: Fully uninteractive mode—no prompts, configurable via file only. Supports autostart on all platforms.

![Scanner Workflow](images/workflow.png)

## Quick Start

### Prerequisites

1. **Python 3.10 or higher**
2. **Git** (for tracking file changes)
3. **Universal Ctags** (for symbol indexing)
4. **[LM Studio](https://lmstudio.ai)** or **[Ollama](https://ollama.ai)** - Local LLM backend

For detailed platform-specific installation, see:
- **[Linux Setup](docs/linux-setup.md)** | **[macOS Setup](docs/macos-setup.md)** | **[Windows Setup](docs/windows-setup.md)**

### Quick Installation

```bash
# Install UV (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/ubego/Code-Scanner.git
cd Code-Scanner

# Install dependencies
uv sync
```

### Configuration

Copy a language-specific example from `examples/` to your project root:

```bash
cp examples/python-config.toml config.toml
```

See `examples/` directory for configs tailored to JavaScript, Java, C++, Android, iOS, and more.

### Running Your First Scan

1. **Start LM Studio**
   - Open LM Studio
   - Search for "qwen2.5-coder-7b-instruct" and download it
   - Click the "<->" icon to open Local Server tab
   - **Crucial**: Set "Context Overlap" to 0 and **"Context Length"** to at least **16384** in the right sidebar
   - Click "Start Server"

2. **Run the scanner**
   ```bash
   uv run code-scanner /path/to/your/project
   ```

3. **View results**
   
   Results are saved to `code_scanner_results.md` in your project directory.

4. **Stop the scanner**
   
   Press `Ctrl+C`. The scanner runs continuously until interrupted.

5. **(Optional) Enable autostart**
   
   To start the scanner automatically on login:
   ```bash
   # Linux
   ./scripts/autostart-linux.sh
   
   # macOS
   ./scripts/autostart-macos.sh
   
   # Windows
   scripts\autostart-windows.bat
   ```

## Documentation

For detailed platform-specific setup instructions:
- **[Linux Setup](docs/linux-setup.md)** | **[Autostart](docs/autostart-linux.md)**
- **[macOS Setup](docs/macos-setup.md)** | **[Autostart](docs/autostart-macos.md)**
- **[Windows Setup](docs/windows-setup.md)** | **[Autostart](docs/autostart-windows.md)**

**Advanced Features:**
- **[AI Tools for Context Expansion](docs/ai-tools.md)** - How the AI can request additional codebase information for sophisticated checks

## Supported LLM Backends

| Backend | Best For | Installation |
|---------|----------|--------------|
| **[LM Studio](https://lmstudio.ai)** | GUI users, trying different models | Download from lmstudio.ai |
| **[Ollama](https://ollama.ai)** | CLI users, automation, simpler setup | `curl -fsSL https://ollama.ai/install.sh \| sh` |

## Configuration Reference

### Basic Configuration

**For Ollama:**
```toml
[llm]
backend = "ollama"
host = "localhost"
port = 11434
model = "qwen3:4b"
timeout = 120
context_limit = 16384  # Required

[[checks]]
pattern = "*"
checks = ["Check for bugs and issues."]
```

**For LM Studio:**
```toml
[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
timeout = 120
context_limit = 16384  # Required

[[checks]]
pattern = "*"
checks = ["Check for bugs and issues."]
```

### Check Groups

Checks are organized into **groups**, each with a file pattern and list of rules:

```toml
# C++/Qt specific checks
[[checks]]
pattern = "*.cpp, *.h, *.cxx, *.hpp"
checks = [
    "Check for any detectable errors and suggest code simplifications where possible.",
    "Check that stack allocation is preferred over heap allocation whenever possible.",
]

# General checks for all files
[[checks]]
pattern = "*"
checks = [
    "Check for unused files or dead code.",
    "Check for architectural violations (e.g., layers accessing each other incorrectly).",
]
```

**Advanced checks using AI Tools:**
```toml
# Checks that leverage AI's ability to explore the codebase
[[checks]]
pattern = "*.py"
checks = [
    "Find duplicate or very similar function implementations that could be refactored.",
    "Verify all database queries use parameterized statements (check all files).",
    "Check for inconsistent naming conventions across modules.",
]
```

**Pattern syntax:**
- `"*.cpp, *.h"` - Match multiple extensions (comma-separated)
- `"*"` - Match all files
- `"src/*.py"` - Match files in specific directories

### Ignore Patterns

Files matching patterns with an **empty checks list** will be ignored during scanning. This is useful for excluding documentation files, configuration files, or other non-code files:

```toml
# Ignore documentation and config files
[[checks]]
pattern = "*.md, *.txt, *.rst, *.html, *.json, *.toml, *.yaml, *.yml"
checks = []
```

The scanner uses a **unified filtering architecture** that applies all exclusion rules in a single pass:
1. **Scanner output files** - Always excluded (O(1) set lookup)
2. **Config ignore patterns** - Applied via fnmatch
3. **Gitignore patterns** - Applied via in-memory pathspec matching

This eliminates redundant subprocess calls and multiple filtering passes, improving performance on large repositories.

### Context Limit (Required)

The `context_limit` parameter is **required** and specifies the context window size (in tokens) of your LLM.

> **⚠️ Warning:** Setting `context_limit` below 16384 is not recommended. The scanner needs context space for system prompts (~1000-2000 tokens), response buffer (~500-1000 tokens), and actual source code.

```toml
[llm]
context_limit = 16384  # Required - recommended minimum
```

Common values:
- 16384 - **Recommended minimum**
- 32768 - Large context models (Llama 3, Qwen, etc.)
- 131072 - Very large context models (GPT-4, Claude, etc.)

## CLI Options

```
code-scanner [OPTIONS] TARGET_DIRECTORY

Arguments:
  TARGET_DIRECTORY    Project directory to scan (must be a Git repository)

Options:
  -c, --config PATH   Path to config.toml (default: config.toml in scanner directory)
  --commit HASH       Scan changes relative to specific commit
  --version           Show version
  --help              Show help message
```

## Troubleshooting

### "Cannot connect to LLM backend"

1. Ensure your LLM backend is running
2. Check the host and port in your config match the running server
3. For Ollama: `curl http://localhost:11434/api/tags`
4. For LM Studio: `curl http://localhost:1234/v1/models`

### Connection Lost During Scan

If the LLM backend becomes unavailable during scanning (e.g., LM Studio crashes, network issues, server restart), the scanner will:

1. **Pause immediately** when the connection error is detected
2. **Retry every 10 seconds** until the connection is restored
3. **Continue scanning** from where it left off once reconnected

### Scanner Keeps Rescanning Without Code Changes

The scanner automatically excludes its own output files (`code_scanner_results.md` and `code_scanner_results.md.bak`) from change detection. If you're experiencing unexpected rescans:

1. **Check the logs** for "New changed files detected" or "File modified since last check" messages
2. **Verify no other tools** are modifying files in the target directory
3. **Check for IDE auto-save** or other processes that might be touching files

This allows you to restart LM Studio or fix network issues without stopping the scanner. The scanner handles various connection errors including:
- Lost connection
- Connection refused
- Connection timeout
- Network errors

### "Model not found" (Ollama)

1. Pull the model: `ollama pull model-name`
2. List available models: `ollama list`

### "Context length exceeded"

1. Use a model with larger context window
2. Reduce `context_limit` in your config to force smaller batches
3. Use `.gitignore` to exclude large generated files

## Technical Details

### Lock File

The scanner creates `~/.code-scanner/code_scanner.lock` (global location) to prevent multiple instances. The lock file stores the PID of the running process and automatically detects/removes stale locks from crashed processes. It's automatically removed on exit (Ctrl+C, SIGTERM, or normal exit).

### LLM Compatibility

- **JSON response format**: Uses `response_format={"type": "json_object"}` if supported
- **Auto-correction**: If LLM returns non-JSON, the scanner asks it to reformat
- **Context limit**: Required in config file (no interactive prompts)

### Excluded Files

The scanner uses a **unified file filtering system** that combines all exclusion rules for efficiency:

**Scanner Output Files** (always excluded):
- `code_scanner_results.md` - The output report
- `code_scanner_results.md.bak` - The backup file
- `code_scanner.log` - The log file

**Config Ignore Patterns**:
- Files matching patterns in check groups with empty `checks = []`
- Example: `*.md, *.txt, *.json` for documentation files

**Gitignore Patterns**:
- Files matching `.gitignore` are excluded via in-memory pattern matching
- No subprocess calls - uses the `pathspec` library for efficiency

### Backup Files

On startup, if `code_scanner_results.md` exists, its content is automatically appended to `code_scanner_results.md.bak` with a timestamp. This preserves previous results without requiring user confirmation.

## Development

### Running Tests

```bash
uv run pytest                    # Run all tests
uv run pytest -v                 # Verbose output
uv run pytest tests/test_scanner.py -v  # Specific file
```

### Coverage Reports

```bash
uv run pytest --cov=code_scanner --cov-report=term-missing
uv run pytest --cov=code_scanner --cov-report=html  # Open htmlcov/index.html
```

**Current Coverage:** 93% with 640 tests.

### Project Structure

```
src/code_scanner/
├── models.py        # Data models (LLMConfig, Issue, etc.)
├── config.py        # Configuration loading and validation
├── base_client.py   # Abstract base class for LLM clients
├── lmstudio_client.py # LM Studio client
├── ollama_client.py # Ollama client
├── ai_tools.py      # AI tool executor for function calling
├── git_watcher.py   # Git repository monitoring
├── issue_tracker.py # Issue lifecycle management
├── output.py        # Markdown report generation
├── scanner.py       # AI scanning logic
├── cli.py           # CLI and application coordinator
├── utils.py         # Utility functions
└── __main__.py      # Entry point
```

## License

GNU Affero General Public License v3.0
