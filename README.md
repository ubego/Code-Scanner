# Code Scanner

AI-powered code scanner that uses local LLM (LM Studio) to identify issues in your codebase based on configurable checks.

## Features

- **Language-agnostic**: Works with any programming language
- **Local LLM**: Uses LM Studio with OpenAI-compatible API
- **Git integration**: Monitors repository changes and scans modified files
- **Configurable checks**: Define custom checks via TOML configuration
- **Issue tracking**: Tracks issue lifecycle (new, existing, resolved)
- **Markdown output**: Generates readable reports in `code_scanner_results.md`

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
   code-scanner --project /path/to/your/project
   ```

## Configuration

See `config.example.toml` for all available options.

### Basic Configuration

```toml
[project]
path = "/path/to/your/project"
output_path = "/path/to/output"

[llm]
host = "http://localhost:1234"
model = "qwen-coder"
context_limit = 8192
temperature = 0.1

[[checks]]
name = "heap-allocation"
enabled = true
prompt = "Find heap allocations without smart pointers"
severity = "warning"
file_patterns = ["*.cpp", "*.h"]
```

## CLI Options

```
code-scanner [OPTIONS]

Options:
  --project PATH     Project directory to scan
  --config PATH      Path to config.toml (default: config.toml)
  --output PATH      Output directory for results
  --commit HASH      Scan changes relative to specific commit
  --once             Run once and exit (no watching)
  --overwrite        Overwrite existing results without prompting
  --help             Show help message
```

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
