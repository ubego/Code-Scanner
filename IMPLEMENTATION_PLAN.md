# Code Scanner Implementation Plan

## Architecture Overview

```
code_scanner/
├── src/
│   └── code_scanner/
│       ├── __init__.py
│       ├── __main__.py          # Entry point
│       ├── cli.py               # CLI argument parsing
│       ├── config.py            # TOML configuration
│       ├── git_watcher.py       # Git change detection thread
│       ├── scanner.py           # AI scanning thread
│       ├── llm_client.py        # LM Studio API client
│       ├── issue_tracker.py     # In-memory issue management
│       ├── output.py            # Markdown report generation
│       ├── models.py            # Data models (Issue, ScanResult, etc.)
│       └── utils.py             # Utilities (binary detection, token estimation)
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Pytest fixtures
│   ├── test_config.py
│   ├── test_git_watcher.py
│   ├── test_scanner.py
│   ├── test_llm_client.py
│   ├── test_issue_tracker.py
│   ├── test_output.py
│   └── sample_qt_project/       # Sample C++ Qt project for testing
│       ├── src/
│       │   ├── main.cpp
│       │   ├── widget.cpp
│       │   ├── widget.h
│       │   └── utils.cpp
│       └── CMakeLists.txt
├── pyproject.toml
├── config.example.toml
└── README.md
```

## Implementation Phases

### Phase 1: Project Setup
1. Initialize UV project with `pyproject.toml`
2. Define dependencies:
   - `openai` - LM Studio client (OpenAI-compatible)
   - `tomli` / `tomllib` - TOML parsing
   - `gitpython` - Git operations
   - `pytest` - Testing
   - `pytest-mock` - Mocking for tests

### Phase 2: Core Modules

#### 2.1 Configuration Module (`config.py`)
```python
@dataclass
class Config:
    target_directory: Path
    config_file: Path
    commit_hash: Optional[str]
    checks: list[str]
    lm_studio_host: str = "localhost"
    lm_studio_port: int = 1234
```
- Load and validate TOML config
- Merge CLI args with config file
- Fail on missing/empty checks

#### 2.2 Models (`models.py`)
```python
@dataclass
class Issue:
    file_path: str
    line_number: int
    description: str
    suggested_fix: str
    check_query: str
    timestamp: datetime
    status: Literal["OPEN", "RESOLVED"]
    code_snippet: str  # For matching

@dataclass
class ScanResult:
    issues: list[Issue]
    files_scanned: list[str]
    skipped_files: list[str]
```

#### 2.3 Git Integration (`git_watcher.py`)
- Use `gitpython` for Git operations
- Detect staged, unstaged, untracked files
- Respect `.gitignore`
- Detect rebase/merge in progress
- Compare against specific commit hash
- Thread with 30-second polling

#### 2.4 LM Studio Client (`llm_client.py`)
- OpenAI-compatible API client
- Query context window size at startup
- Send prompts with JSON response format
- Retry logic (3 retries, immediate)
- Connection failure handling

#### 2.5 Issue Tracker (`issue_tracker.py`)
- In-memory issue storage
- Whitespace-normalized matching
- Line number updates for moved issues
- Resolution tracking
- Deduplication logic

#### 2.6 Output Generation (`output.py`)
- Markdown report structure
- Group issues by file
- Include all required metadata
- File rewrite on changes

### Phase 3: Main Application

#### 3.1 Scanner Thread (`scanner.py`)
- Sequential query execution
- Context overflow strategy:
  1. All files together
  2. Group by directory hierarchy
  3. File-by-file fallback
- Restart signal handling
- Discard interrupted query results

#### 3.2 CLI & Main (`cli.py`, `__main__.py`)
- Argument parsing (target dir, config, commit hash)
- Lock file management
- Overwrite confirmation prompt
- SIGINT handling
- Thread coordination

### Phase 4: Testing

#### 4.1 Sample C++ Qt Project
Create intentional issues:
- Heap allocation where stack would work
- Repeated string literals
- Missing `constexpr`
- Functions in header files
- Meaningless comments
- Code style violations

#### 4.2 Test Cases
- Unit tests for each module
- Integration tests with mocked LM Studio
- End-to-end test with sample project

## Module Dependencies

```
cli.py
  └── config.py
        └── models.py
  └── git_watcher.py
        └── utils.py
  └── scanner.py
        └── llm_client.py
        └── issue_tracker.py
              └── models.py
        └── output.py
              └── models.py
```

## Key Design Decisions

1. **Threading Model**: Use `threading.Thread` with `threading.Event` for signaling
2. **Lock File**: Simple file-based locking with PID written for debugging
3. **Token Estimation**: ~4 characters per token (conservative estimate)
4. **Issue Matching**: Normalize whitespace, compare code snippet + description
5. **Directory Batching**: Sort by depth (deepest first), group siblings

## Error Handling Strategy

| Scenario | Action |
|----------|--------|
| No Git repo | Fail immediately with error |
| Missing config | Fail immediately with error |
| Empty checks | Fail immediately with error |
| LM Studio unreachable at startup | Fail immediately with error |
| LM Studio fails mid-session | Retry every 10 seconds |
| Context limit unavailable | Fail immediately with error |
| Malformed JSON response | Retry 3 times, then skip query |
| Lock file exists | Fail with error (manual removal required) |
| User declines overwrite | Exit immediately |
| SIGINT | Immediate exit, remove lock file |

## Execution Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         STARTUP                                  │
├─────────────────────────────────────────────────────────────────┤
│ 1. Check lock file → fail if exists, else create                │
│ 2. Check output file → prompt overwrite → exit if declined      │
│ 3. Load TOML config → fail if missing/empty                     │
│ 4. Connect to LM Studio → fail if unreachable                   │
│ 5. Query context limit → fail if unavailable                    │
│ 6. Start Git Watcher thread                                     │
│ 7. Start AI Scanner thread                                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      GIT WATCHER THREAD                          │
├─────────────────────────────────────────────────────────────────┤
│ Loop every 30 seconds:                                          │
│   1. Check for rebase/merge → wait if in progress               │
│   2. Get changed files (staged + unstaged + untracked)          │
│   3. Filter out .gitignore matches                              │
│   4. Compare with previous state                                │
│   5. If changes detected → signal Scanner thread                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AI SCANNER THREAD                           │
├─────────────────────────────────────────────────────────────────┤
│ Loop:                                                           │
│   1. Wait for changes (or start immediately if changes exist)   │
│   2. Get file contents                                          │
│   3. Apply context overflow strategy if needed                  │
│   4. For each check query:                                      │
│      a. Send to LM Studio                                       │
│      b. Parse JSON response                                     │
│      c. Check for restart signal → finish query, then restart   │
│   5. Update issue tracker                                       │
│   6. Rewrite output file                                        │
│   7. Loop back to first check                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Files to Create (in order)

1. `pyproject.toml` - Project configuration
2. `src/code_scanner/__init__.py` - Package init
3. `src/code_scanner/models.py` - Data models
4. `src/code_scanner/utils.py` - Utilities
5. `src/code_scanner/config.py` - Configuration
6. `src/code_scanner/llm_client.py` - LM Studio client
7. `src/code_scanner/git_watcher.py` - Git integration
8. `src/code_scanner/issue_tracker.py` - Issue management
9. `src/code_scanner/output.py` - Markdown generation
10. `src/code_scanner/scanner.py` - AI scanner thread
11. `src/code_scanner/cli.py` - CLI interface
12. `src/code_scanner/__main__.py` - Entry point
13. `config.example.toml` - Example configuration
14. `tests/sample_qt_project/` - Test fixtures
15. `tests/conftest.py` - Test configuration
16. `tests/test_*.py` - Test modules
