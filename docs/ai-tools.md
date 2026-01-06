# AI Tools for Context Expansion 

The Code Scanner provides **AI Tools** (also known as function calling) that allow the Language Model to interactively request additional information from the codebase beyond the files with uncommitted changes. This enables sophisticated cross-file analysis and architectural checks.

## Prerequisites

**Universal Ctags** is required for symbol indexing and lookup functionality. Install it before using the scanner:

```bash
# Ubuntu/Debian
sudo apt-get install universal-ctags

# macOS (via Homebrew)
brew install universal-ctags

# Fedora
sudo dnf install ctags

# Arch Linux
sudo pacman -S ctags
```

Verify installation with `ctags --version`. You should see "Universal Ctags" in the output.

## Overview

While the scanner provides the full content of all modified files to the AI, it is limited by only analyzing uncommitted changes. To perform complex checks like:

- Verifying architectural patterns across the entire codebase
- Finding all usages of a specific function or class
- Checking consistency of naming conventions
- Analyzing dependencies between modules

The AI needs to "look outside" the immediate set of changed files. The AI Tools API solves this by allowing the AI to request additional context on-demand during its analysis.

## Available Tools

### 1. search_text

**Purpose:** Search the entire repository for text patterns (strings, function names, class names, variables, etc.). Supports both literal text search and regular expressions.

**Parameters:**
- `patterns` (required): Single string or array of strings to search for
- `is_regex` (optional): Boolean (default: false) - if true, treat patterns as regular expressions
- `match_whole_word` (optional): Boolean (default: true) - match only whole words (ignored when is_regex is true)
- `case_sensitive` (optional): Boolean (default: false) - case-sensitive matching
- `file_pattern` (optional): Glob pattern to filter files (e.g., "*.py")
- `offset` (optional): Number of results to skip for pagination (default: 0)

**Returns:**
- `patterns`: Array of patterns searched
- `total_matches`: Total number of matches found across all patterns
- `returned_count`: Number of matches in this response
- `offset`: Current offset position
- `has_more`: Boolean indicating if more results exist
- `next_offset`: Value to use for next request (only if `has_more` is true)
- `matches_by_pattern`: Object mapping each pattern to its matches
  - Each match includes: `file`, `line`, `code`

**Example Usage:**
```python
# Search for a function name (literal search)
search_text(patterns="calculate_total")

# Search with regex to find function definitions
search_text(patterns=r"def\s+\w+_handler", is_regex=True)

# Search for multiple patterns at once
search_text(patterns=["calculate_total", "compute_sum"])

# Regex with alternation to find class or function definitions
search_text(patterns=r"(class|def)\s+MyClass", is_regex=True)

# Case-sensitive search in Python files only
search_text(patterns="ClassName", case_sensitive=True, file_pattern="*.py")

# Result:
{
  "patterns": ["calculate_total"],
  "total_matches": 75,
  "returned_count": 50,
  "offset": 0,
  "has_more": true,
  "next_offset": 50,
  "matches_by_pattern": {
    "calculate_total": [
      {"file": "src/main.py", "line": 10, "code": "result = calculate_total(items)"},
      {"file": "src/utils/math.py", "line": 5, "code": "def calculate_total(items):"},
      ...
    ]
  }
}

# To get more results, request with offset:
search_text(patterns="calculate_total", offset=50)
```

**Behavior:**
- Searches all non-binary files recursively
- Skips hidden directories (`.git`, `.vscode`, etc.)
- Skips common build directories (`node_modules`, `__pycache__`, `build`, `dist`, `target`)
- Results paginated at 50 matches per page
- Includes ⚠️ warning if more results available with instructions for next request

### 2. read_file

**Purpose:** Read the content of any file in the repository, even if it has no uncommitted changes.

**Parameters:**
- `file_path` (required): Relative path to the file from repository root
- `start_line` (optional): Line number to start reading from (1-based)
- `end_line` (optional): Line number to stop reading at (1-based, inclusive)

**Returns:**
- `file_path`: The requested file path
- `content`: File content (may be partial)
- `start_line`: Actual starting line number
- `end_line`: Actual ending line number
- `total_lines`: Total number of lines in the file
- `lines_returned`: Number of lines in this response
- `is_partial`: Boolean indicating if content is truncated
- `has_more`: Boolean indicating if more lines exist after `end_line`
- `next_start_line`: Line number to use for next request (only if `has_more` is true)
- `hint` (optional): Helpful guidance for the LLM about the file state

**Hints:**
The response may include a `hint` field to guide the LLM:
- For complete files: `"This is the COMPLETE file (150 lines). No need to read it again."`
- For mostly-read files (≥80%): `"You now have 85% of this file. Consider proceeding with analysis."`

**Example Usage:**
```python
# AI might request this to check configuration files
read_file(file_path="config/settings.py")

# Result:
{
  "file_path": "config/settings.py",
  "content": "API_KEY = 'secret'\nDEBUG = True\n...",
  "start_line": 1,
  "end_line": 150,
  "total_lines": 500,
  "lines_returned": 150,
  "is_partial": true,
  "has_more": true,
  "next_start_line": 151
}

# To read more, request with start_line:
read_file(file_path="config/settings.py", start_line=151)
```

**Behavior:**
- Validates path is within repository (security check)
- Rejects binary files
- Automatically chunks large files (≤4000 tokens per chunk by default)
- Includes ⚠️ warning with instructions for requesting next chunk if content is partial
- Supports reading specific line ranges for efficient partial reads

### 3. list_directory

**Purpose:** List all files and subdirectories in a specific directory to explore repository structure. Includes file sizes to help plan which files to read.

**Parameters:**
- `directory_path` (required): Relative path to directory from repository root (use `"."` for root)
- `recursive` (optional): If true, list all files recursively (default: false)
- `offset` (optional): Number of items to skip for pagination (default: 0)

**Returns:**
- `directory_path`: The requested directory
- `directories`: Array of subdirectory paths (relative to repo root)
- `files`: Array of file objects with path and line count
  - `path`: Relative file path
  - `lines`: Number of lines in the file (for text files only)
- `total_directories`: Count of directories (total in directory)
- `total_files`: Count of files (total in directory)
- `total_items`: Total count of files + directories
- `returned_count`: Number of items in this response
- `offset`: Current offset position
- `has_more`: Boolean indicating if more items exist
- `next_offset`: Value to use for next request (only if `has_more` is true)
- `recursive`: Whether listing was recursive

**Example Usage:**
```python
# AI might request this to understand project structure
list_directory(directory_path="src", recursive=False)

# Result:
{
  "directory_path": "src",
  "directories": ["src/utils", "src/models"],
  "files": [
    {"path": "src/main.py", "lines": 150},
    {"path": "src/__init__.py", "lines": 5}
  ],
  "total_directories": 2,
  "total_files": 2,
  "total_items": 4,
  "returned_count": 4,
  "offset": 0,
  "has_more": false,
  "recursive": false
}

# For large directories with many items:
list_directory(directory_path="node_modules", recursive=True)
# Result with pagination:
{
  "total_items": 500,
  "returned_count": 100,
  "offset": 0,
  "has_more": true,
  "next_offset": 100,
  ...
}

# To get more results:
list_directory(directory_path="node_modules", recursive=True, offset=100)
```

The `lines` field helps the LLM plan which files to read:
- Small files (< 100 lines) can usually be read in one request
- Medium files (100-500 lines) may need chunking
- Large files (> 500 lines) will definitely be chunked

**Behavior:**
- Validates path is within repository (security check)
- Automatically filters hidden files and directories (starting with `.`)
- Skips common build directories (`node_modules`, `__pycache__`, `build`, `dist`, `target`)
- Results paginated at 100 items per page
- Includes ⚠️ warning if more results available with instructions for next request

### 4. get_file_diff

**Purpose:** Get git diff for a specific file, showing only the changed lines relative to HEAD. This is much more token-efficient than reading the entire file when you only need to understand what was modified.

**Parameters:**
- `file_path` (required): Relative path to the file from repository root
- `context_lines` (optional): Number of unchanged lines to include around each change (default: 3, max: 10)

**Returns:**
- `file_path`: The requested file path
- `has_changes`: Boolean indicating if the file has uncommitted changes
- `diff`: The unified diff output (null if no changes)
- `lines_added`: Approximate count of added lines
- `lines_removed`: Approximate count of removed lines
- `context_lines`: Number of context lines used
- `message`: Helpful message when no changes exist

**Example Usage:**
```python
# Get diff for a modified file
get_file_diff(file_path="src/main.py")

# Result with changes:
{
  "file_path": "src/main.py",
  "has_changes": true,
  "diff": "--- a/src/main.py\n+++ b/src/main.py\n@@ -10,3 +10,5 @@\n def calculate():\n-    return 0\n+    # Fixed calculation\n+    return total * 1.1",
  "lines_added": 2,
  "lines_removed": 1,
  "context_lines": 3
}

# Result with no changes:
{
  "file_path": "src/main.py",
  "has_changes": false,
  "diff": null,
  "message": "No changes in this file relative to HEAD"
}
```

**Behavior:**
- Uses git diff command internally
- Returns error if not in a git repository
- Token-efficient alternative to read_file for understanding changes

### 5. get_file_summary

**Purpose:** Get a structural summary of a file without reading all content. Returns classes, functions, and imports—much more token-efficient than read_file when you only need to understand the file structure.

**Parameters:**
- `file_path` (required): Relative path to the file from repository root

**Returns:**
- `file_path`: The requested file path
- `total_lines`: Total number of lines in the file
- `classes`: Array of class definitions, each with `name` and `line` number
- `functions`: Array of function definitions, each with `name` and `line` number
- `imports`: Array of import statements (full lines)
- `constants`: Array of constant definitions (if detected)
- `summary`: Counts summary object with `class_count`, `function_count`, `import_count`, `constant_count`

**Example Usage:**
```python
# Get structure of a module
get_file_summary(file_path="src/services/user_service.py")

# Result:
{
  "file_path": "src/services/user_service.py",
  "total_lines": 250,
  "classes": [
    {"name": "UserService", "line": 15},
    {"name": "UserValidator", "line": 180}
  ],
  "functions": [
    {"name": "__init__", "line": 20},
    {"name": "create_user", "line": 35},
    {"name": "delete_user", "line": 55},
    {"name": "validate_email", "line": 185}
  ],
  "imports": [
    "from typing import Optional",
    "from models import User",
    "import logging"
  ],
  "constants": [],
  "summary": {
    "class_count": 2,
    "function_count": 4,
    "import_count": 3,
    "constant_count": 0
  }
}
```

**Behavior:**
- Language-agnostic: Detects common patterns like `class`, `def`, `function`, `import`, `require`, `#include`, etc.
- Returns error if file not found
- Much more token-efficient than read_file for understanding file organization

### 6. symbol_exists

**Purpose:** Quick check if a symbol (function, class, variable, etc.) is defined anywhere in the repository using the ctags index. Returns location if found. Use this BEFORE reporting "undefined symbol" issues—it's instant with O(1) lookup.

**Parameters:**
- `symbol` (required): The symbol name to search for (function name, class name, variable, etc.)
- `symbol_type` (optional): Filter by symbol type. Values: `function`, `class`, `method`, `variable`, `constant`, `any` (default: `any`)

**Returns:**
- `symbol`: The symbol searched for
- `symbol_type`: The type filter applied (or "any")
- `exists`: Boolean indicating if symbol was found
- `locations`: Array of locations where symbol is defined, each with:
  - `file`: File path
  - `line`: Line number
  - `kind`: Symbol kind (function, class, method, etc.)

**Example Usage:**
```python
# Check if a function exists
symbol_exists(symbol="calculate_tax")

# Result when found:
{
  "symbol": "calculate_tax",
  "symbol_type": "any",
  "exists": true,
  "locations": [
    {
      "file": "src/finance/tax.py",
      "line": 25,
      "kind": "function"
    }
  ]
}

# Result when not found:
{
  "symbol": "nonexistent_function",
  "symbol_type": "any",
  "exists": false,
  "locations": []
}

# Filter by symbol type
symbol_exists(symbol="User", symbol_type="class")
```

**Behavior:**
- Uses Universal Ctags index for O(1) symbol lookup
- Type filtering based on ctags symbol kinds
- Instant lookup compared to file-based search
- Returns only definition locations, not usage locations

### 7. find_definition

**Purpose:** Find the exact definition location of a symbol using the ctags index. More precise than search_text for locating where a function, class, or variable is defined.

**Parameters:**
- `symbol` (required): The symbol name to find
- `symbol_type` (optional): Filter by type: `function`, `class`, `method`, `variable`, `any` (default: `any`)

**Returns:**
- `symbol`: The symbol searched for
- `symbol_type`: The type filter applied
- `found`: Boolean indicating if definition was found
- `definitions`: Array of definition locations, each with:
  - `file`: File path
  - `line`: Line number
  - `kind`: Symbol kind
  - `scope`: Parent scope (e.g., class name for methods)
  - `signature`: Function signature if available

**Example Usage:**
```python
# Find where a function is defined
find_definition(symbol="process_data")

# Result:
{
  "symbol": "process_data",
  "symbol_type": "any",
  "found": true,
  "definitions": [
    {
      "file": "src/processor.py",
      "line": 42,
      "kind": "function",
      "scope": null,
      "signature": "(data: list, options: dict = None)"
    }
  ]
}
```

### 8. list_symbols

**Purpose:** List all symbols in a specific file. Useful for getting an overview of a file's structure without reading the entire content.

**Parameters:**
- `file_path` (required): Relative path to the file

**Returns:**
- `file_path`: The requested file
- `symbols`: Array of symbols in the file, each with:
  - `name`: Symbol name
  - `line`: Line number
  - `kind`: Symbol kind (function, class, method, variable)
  - `scope`: Parent scope if any

**Example Usage:**
```python
# List all symbols in a file
list_symbols(file_path="src/models/user.py")

# Result:
{
  "file_path": "src/models/user.py",
  "symbols": [
    {"name": "User", "line": 10, "kind": "class", "scope": null},
    {"name": "__init__", "line": 15, "kind": "method", "scope": "User"},
    {"name": "validate", "line": 25, "kind": "method", "scope": "User"},
    {"name": "DEFAULT_ROLE", "line": 5, "kind": "variable", "scope": null}
  ]
}
```

### 9. find_symbols

**Purpose:** Find symbols matching a pattern across the entire codebase. Supports wildcards for flexible symbol discovery.

**Parameters:**
- `pattern` (required): Pattern to match (supports * and ? wildcards)
- `symbol_type` (optional): Filter by type: `function`, `class`, `method`, `variable`, `any` (default: `any`)

**Returns:**
- `pattern`: The pattern searched for
- `symbol_type`: The type filter applied
- `count`: Number of matching symbols
- `symbols`: Array of matching symbols, each with file, line, kind, scope

**Example Usage:**
```python
# Find all test functions
find_symbols(pattern="test_*", symbol_type="function")

# Result:
{
  "pattern": "test_*",
  "symbol_type": "function",
  "count": 15,
  "symbols": [
    {"name": "test_login", "file": "tests/test_auth.py", "line": 10, "kind": "function"},
    {"name": "test_logout", "file": "tests/test_auth.py", "line": 25, "kind": "function"},
    ...
  ]
}

# Find all handler classes
find_symbols(pattern="*Handler", symbol_type="class")
```

### 10. get_class_members

**Purpose:** Get all members (methods, attributes) of a specific class. Essential for understanding class structure and inheritance.

**Parameters:**
- `class_name` (required): Name of the class to inspect

**Returns:**
- `class_name`: The class inspected
- `found`: Boolean indicating if class was found
- `file`: File where class is defined
- `line`: Line number of class definition
- `members`: Array of class members, each with:
  - `name`: Member name
  - `kind`: Member kind (method, member, etc.)
  - `line`: Line number
  - `signature`: Method signature if available

**Example Usage:**
```python
# Get members of a class
get_class_members(class_name="UserService")

# Result:
{
  "class_name": "UserService",
  "found": true,
  "file": "src/services/user_service.py",
  "line": 15,
  "members": [
    {"name": "__init__", "kind": "method", "line": 20, "signature": "(self, db)"},
    {"name": "create_user", "kind": "method", "line": 30, "signature": "(self, data)"},
    {"name": "delete_user", "kind": "method", "line": 45, "signature": "(self, user_id)"},
    {"name": "_validate", "kind": "method", "line": 60, "signature": "(self, data)"}
  ]
}
```

### 11. get_index_stats

**Purpose:** Get statistics about the ctags symbol index. Useful for understanding repository size and symbol distribution.

**Parameters:** None

**Returns:**
- `total_symbols`: Total number of indexed symbols
- `total_files`: Number of files indexed
- `symbols_by_kind`: Count of symbols by kind (function, class, etc.)
- `top_files`: Files with most symbols (top 10)

**Example Usage:**
```python
# Get index statistics
get_index_stats()

# Result:
{
  "total_symbols": 1250,
  "total_files": 85,
  "symbols_by_kind": {
    "function": 450,
    "class": 75,
    "method": 520,
    "variable": 205
  },
  "top_files": [
    {"file": "src/core/engine.py", "count": 85},
    {"file": "src/models/base.py", "count": 62},
    ...
  ]
}
```

## Pagination Pattern

All tools use a consistent pagination pattern to allow the LLM to fetch additional results when needed:

| Field | Type | Description |
|-------|------|-------------|
| `offset` | integer | Starting index (0-based). Default is 0. |
| `has_more` | boolean | `true` if more results exist beyond current page. |
| `next_offset` | integer | Value to use in next request (only present if `has_more` is `true`). |
| `returned_count` | integer | Number of items in current response. |
| `total_*` | integer | Total count of items (varies by tool). |

**Page Sizes:**
- `search_text`: 50 matches per page
- `list_directory`: 100 items per page
- `read_file`: Uses line ranges (controlled via `start_line` / `end_line`)

**Warning Messages:**
When results are partial, the response includes a warning message like:
```
⚠️ PARTIAL RESULTS: Showing 50 of 150 total matches (offset 0).
To get more results, call search_text again with offset=50
```

## How It Works

### Execution Flow

1. **Initial Query:** Scanner sends the analysis request to the LLM with tool definitions included
2. **Tool Request:** If the LLM needs more context, it requests one or more tools
3. **Tool Execution:** Scanner executes the requested tools and gathers results
4. **Result Delivery:** Scanner sends tool results back to the LLM
5. **Iteration:** Process repeats (max 10 iterations) until LLM provides final analysis
6. **Final Answer:** LLM returns detected issues in standard JSON format

### Example Conversation Flow

```
User: "Check for architectural violations in MVC pattern"

LLM: [requests] search_text(patterns="Controller")

Scanner: [executes] Returns all Controller class usages

LLM: [requests] read_file(file_path="src/views/user_view.py")

Scanner: [executes] Returns view file content

LLM: [analyzes] Detects that view is calling model directly (bypasses controller)

LLM: [returns] Issues found:
{
  "issues": [{
    "file": "src/views/user_view.py",
    "line_number": 45,
    "description": "MVC violation: View directly accesses Model, should use Controller",
    ...
  }]
}
```

## Partial Content Handling

When tools return content that exceeds the configured `context_limit`, the scanner manages the data carefully:

### Chunking Strategy

Files and results are automatically chunked to fit within the context limit:

- **File reading:** Large files are split into chunks of ~4000 tokens. Use `next_start_line` to continue reading.
- **Usage search:** Paginated at 50 matches per page. Use `next_offset` to fetch more results.
- **Directory listing:** Paginated at 100 items per page. Use `next_offset` to fetch more items.

### Warning Messages

When partial content is returned, a standardized warning is included:

```
⚠️ PARTIAL CONTENT: This file is too large to return in full.
Showing lines 1-150 of 500.
To read more, call read_file again with start_line=151.
```

```
⚠️ PARTIAL RESULTS: Showing 50 of 150 total matches (offset 0).
To get more results, call search_text again with offset=50
```

The AI is instructed to:
- Recognize partial content warnings and `has_more` flags
- Use pagination parameters (`offset`, `next_start_line`) to fetch additional results
- Work with available partial information when sufficient for the analysis

## Configuration

No additional configuration is required. AI tools are automatically available when the scanner is running.

The tools use the existing `context_limit` setting from the `[llm]` section of your config file:

```toml
[llm]
context_limit = 32768  # Used for chunking tool results
```

Recommended `context_limit` values:
- **Minimum:** 16384 tokens (16K)
- **Recommended:** 32768 tokens (32K) or higher
- **Optimal:** 65536+ tokens (64K+) for complex architectural checks

## Best Practices

### For Check Authors

When writing checks that benefit from AI tools:

1. **Be specific about what to verify:**
   ```toml
   checks = [
       "Verify all database queries use parameterized statements (check all files using search_text)"
   ]
   ```

2. **Suggest exploring related files:**
   ```toml
   checks = [
       "Check that API endpoints follow RESTful conventions (examine all route definitions)"
   ]
   ```

3. **Request architectural analysis:**
   ```toml
   checks = [
       "Verify MVC pattern: controllers should not contain business logic (check related files)"
   ]
   ```

### For AI Analysis

The system prompt automatically instructs the AI to:

- Use `search_text` for architectural checks and dependency analysis
- Use `read_file` to examine related files for context
- Use `list_directory` to understand project structure
- Handle partial results by making additional requests when needed

### Security Considerations

All tools include built-in security measures:

- **Path validation:** All paths are validated to be within the target repository
- **Directory traversal protection:** Attempts to access `../` paths outside the repo are rejected
- **Binary file protection:** Binary files are detected and rejected automatically
- **Resource limits:** Results are limited to prevent context overflow

## Performance Notes

### Tool Execution Overhead

- Tool execution adds 1-3 seconds per tool call (filesystem operations)
- Complex checks may require 2-5 tool calls before reaching final answer
- Total analysis time increases by 5-15 seconds for tool-enhanced checks

### Optimization Tips

1. **Context limit matters:** Higher limits allow more content per tool call
2. **Specific queries work better:** "Check function X" is faster than "Check everything"
3. **Sequential processing:** Each check runs one at a time to preserve tool context

## Troubleshooting

### Tool Calls Not Working

**Symptom:** LLM provides analysis without using tools

**Causes:**
- Model doesn't support function calling (use newer models)
- Context limit too small (increase to 16K+)
- Model not following instructions (use reasoning-capable models)

**Solution:**
- Use models with strong reasoning capabilities (Qwen 2.5+, DeepSeek, etc.)
- Ensure `context_limit` is at least 16384 tokens
- Update to latest version of LM Studio or Ollama

### Partial Content Issues

**Symptom:** AI complains about incomplete information

**Solution:**
- This is normal behavior for large files/results
- The AI should automatically request more chunks
- If not, increase `context_limit` in config

### Slow Performance

**Symptom:** Checks take a very long time

**Causes:**
- Too many tool iterations (max 10 per check)
- Large repository with many files
- Slow model inference

**Solution:**
- Use faster models for routine checks
- Make checks more specific to reduce tool usage
- Ensure SSD storage for repository (faster file access)

## Examples

### Example 1: Finding Duplicate Functions

**Check:**
```toml
checks = [
    "Find duplicate or very similar function implementations that could be refactored"
]
```

**Tool Usage:**
1. AI uses `list_directory` to find all Python files
2. AI uses `search_text` to locate similar function names
3. AI uses `read_file` to compare implementations
4. AI reports duplicates with suggestions

### Example 2: Architectural Validation

**Check:**
```toml
checks = [
    "Verify that service layer doesn't directly access database (should use repositories)"
]
```

**Tool Usage:**
1. AI uses `search_text` to find all database access calls
2. AI uses `read_file` to check which layer each call is in
3. AI reports violations with layer names and line numbers

### Example 3: Naming Convention Check

**Check:**
```toml
checks = [
    "Ensure all test files follow naming convention test_*.py"
]
```

**Tool Usage:**
1. AI uses `list_directory(directory_path="tests", recursive=True)`
2. AI checks each file name against the pattern
3. AI reports files that don't match convention

## Technical Details

### Implementation

- **Module:** `src/code_scanner/ai_tools.py`
- **Class:** `AIToolExecutor`
- **Integration:** `scanner.py` - `_run_check_with_tools()` method
- **Schema:** OpenAI-compatible function calling format

### Tool Schema Format

Tools are defined using OpenAI's function calling schema:

```python
{
    "type": "function",
    "function": {
        "name": "tool_name",
        "description": "What the tool does",
        "parameters": {
            "type": "object",
            "properties": { ... },
            "required": [ ... ]
        }
    }
}
```

### Backend Support

- **LM Studio:** Full support via OpenAI-compatible API
- **Ollama:** Native function calling support via `/api/chat` endpoint

Both backends receive the same tool definitions and handle tool calls identically.
