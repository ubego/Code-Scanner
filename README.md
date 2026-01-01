# Code Scanner

AI-powered code scanner that uses local LLM (LM Studio) to identify issues in your codebase based on configurable checks.

## Features

- **Language-agnostic**: Works with any programming language
- **Local LLM**: Uses LM Studio with OpenAI-compatible API
- **Git integration**: Monitors repository changes and scans modified files
- **Configurable checks**: Define custom checks via TOML configuration
- **Issue tracking**: Tracks issue lifecycle (new, existing, resolved)
- **Markdown output**: Generates readable reports in `code_scanner_results.md` in the **target project directory** (created at startup)

## Installation

```bash
# Using UV (recommended)
uv sync

# Or using pip
pip install -e .
```

## Quick Start

1. **Start LM Studio** and load a model (e.g., `qwen-coder`)

2. **Configure** the scanner by creating `config.toml`:
   ```bash
   cp config.example.toml config.toml
   ```

3. **Run** the scanner:
   ```bash
   uv run code-scanner /path/to/your/project
   ```

## Configuration

See `config.example.toml` for all available options.

### Check Groups

Checks are organized into **groups**, each with a file pattern and list of rules:

```toml
# C++/Qt specific checks
[[checks]]
pattern = "*.cpp, *.h, *.cxx, *.hpp"
rules = [
    "Check for any detectable errors and suggest code simplifications where possible.",
    "Check that stack allocation is preferred over heap allocation whenever possible.",
    "Check that string literals are handled through QStringView variables.",
]

# General checks for all files
[[checks]]
pattern = "*"
rules = [
    "Check for unused files or dead code.",
]

# LM Studio connection settings
[llm]
host = "localhost"
port = 1234
# model = "specific-model-name"  # Leave commented to use default model
timeout = 120
# context_limit = 8192  # See "Context Limit" section below
```

**Pattern syntax:**
- `"*.cpp, *.h"` - Match multiple extensions (comma-separated)
- `"*"` - Match all files
- `"src/*.py"` - Match files in specific directories

**Legacy format:** Simple list of strings is still supported:
```toml
checks = ["Check for errors", "Check for style issues"]
```
This is converted to a single group with `"*"` pattern.

### Context Limit

The scanner needs to know the context window size (in tokens) of your LLM model to properly batch files for analysis.

**Auto-detection**: The scanner first tries to query the context limit from LM Studio's API.

**Interactive prompt**: If auto-detection fails and you're running interactively, the scanner will prompt you to enter the context limit:
```
Context limit could not be determined from LM Studio API.
Please enter the context window size for your model.
Common values: 4096, 8192, 16384, 32768, 131072

Enter context limit (tokens): 
```

**Manual configuration**: For non-interactive use or to skip the prompt, set `context_limit` in your config.toml:
```toml
[llm]
context_limit = 8192  # Your model's context window size in tokens
```

Common context limit values:
- 4096 - Smaller models
- 8192 - Standard models (Llama 2, etc.)
- 16384 - Extended context models
- 32768 - Large context models (Llama 3, etc.)
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

## Technical Details

### Lock File

The scanner creates a lock file `.code_scanner.lock` in the **scanner's script directory** (not the target project directory) to prevent multiple instances from running simultaneously.

**Graceful cleanup**: The lock file is automatically removed when the scanner exits via:
- Normal exit
- Ctrl+C (SIGINT)
- SIGTERM
- Any exception or error

The cleanup is guaranteed via `atexit` handler and signal handlers. If the lock file exists after a crash (rare), you must manually delete it.

### LLM Compatibility

The scanner is designed to work with various LM Studio models:

- **JSON response format**: Uses `response_format={"type": "json_object"}` if supported. Automatically falls back to prompt-based JSON formatting if the model doesn't support this parameter.
- **Reasoning effort**: Uses `reasoning_effort="high"` for thorough code analysis.
- **Context limit**: Auto-detected from API, with interactive prompt fallback.

### Error Handling

**Markdown fence stripping**: LLMs often wrap JSON in markdown code fences (` ```json ... ``` `) despite being told not to. The scanner automatically detects and strips these fences before parsing.

**Malformed JSON responses**: LLMs occasionally return incomplete or non-JSON responses. The scanner handles this intelligently:
1. Automatically strips markdown code fences if present
2. If parsing still fails, asks the LLM to **reformat its own response** into valid JSON
3. If reformatting fails, retries the original query (up to 3 times)

```
WARNING - Malformed JSON response (attempt 1/3): Expecting value: line 1 column 1 (char 0). Asking LLM to reformat response.
INFO - LLM successfully reformatted response to valid JSON.
```

This is normal behavior - the scanner handles it automatically.

**Empty responses**: If the LLM returns an empty response, the scanner retries automatically.

### Excluded Files

The scanner automatically excludes its own output files from scanning:
- `code_scanner_results.md` - The output report
- `code_scanner.log` - The log file

## Development

### Running Tests

```bash
uv run pytest
```

### Project Structure

```
src/code_scanner/
├── models.py       # Data models
├── config.py       # Configuration loading
├── llm_client.py   # LM Studio client
├── git_watcher.py  # Git repository monitoring
├── issue_tracker.py # Issue lifecycle management
├── output.py       # Markdown report generation
├── scanner.py      # AI scanning logic
├── cli.py          # CLI and application coordinator
└── __main__.py     # Entry point
```

## License

MIT
