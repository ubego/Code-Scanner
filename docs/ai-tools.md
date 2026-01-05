# AI Tools for Context Expansion 

The Code Scanner provides **AI Tools** (also known as function calling) that allow the Language Model to interactively request additional information from the codebase beyond the files with uncommitted changes. This enables sophisticated cross-file analysis and architectural checks.

## Overview

While the scanner provides the full content of all modified files to the AI, it is limited by only analyzing uncommitted changes. To perform complex checks like:

- Verifying architectural patterns across the entire codebase
- Finding all usages of a specific function or class
- Checking consistency of naming conventions
- Analyzing dependencies between modules

The AI needs to "look outside" the immediate set of changed files. The AI Tools API solves this by allowing the AI to request additional context on-demand during its analysis.

## Available Tools

### 1. find_code_usage

**Purpose:** Search the entire repository for all occurrences of a code entity (function, class, variable, method, constant).

**Parameters:**
- `entity_name` (required): The name of the code entity to search for
- `entity_type` (optional): Hint about the entity type: `"function"`, `"class"`, `"variable"`, `"method"`, `"constant"`, or `"any"`
- `offset` (optional): Number of results to skip for pagination (default: 0)

**Returns:**
- `entity_name`: The searched entity name
- `entity_type`: The entity type
- `total_matches`: Total number of matches found
- `returned_count`: Number of matches in this response
- `offset`: Current offset position
- `has_more`: Boolean indicating if more results exist
- `next_offset`: Value to use for next request (only if `has_more` is true)
- `usages`: Array of usage locations (50 per page)
  - `file`: Relative file path
  - `line`: Line number (1-based)
  - `code`: Code snippet from that line

**Example Usage:**
```python
# AI might request this to check if a function is used consistently
find_code_usage(entity_name="calculate_total", entity_type="function")

# Result:
{
  "entity_name": "calculate_total",
  "entity_type": "function",
  "total_matches": 75,
  "returned_count": 50,
  "offset": 0,
  "has_more": true,
  "next_offset": 50,
  "usages": [
    {"file": "src/main.py", "line": 10, "code": "result = calculate_total(items)"},
    {"file": "src/utils/math.py", "line": 5, "code": "def calculate_total(items):"},
    ...
  ]
}

# To get more results, request with offset:
find_code_usage(entity_name="calculate_total", entity_type="function", offset=50)
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
- `find_code_usage`: 50 matches per page
- `list_directory`: 100 items per page
- `read_file`: Uses line ranges (controlled via `start_line` / `end_line`)

**Warning Messages:**
When results are partial, the response includes a warning message like:
```
⚠️ PARTIAL RESULTS: Showing 50 of 150 total matches (offset 0).
To get more results, call find_code_usage again with offset=50
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

LLM: [requests] find_code_usage(entity_name="Controller", entity_type="class")

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
To get more results, call find_code_usage again with offset=50
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
       "Verify all database queries use parameterized statements (check all files using find_code_usage)"
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

- Use `find_code_usage` for architectural checks and dependency analysis
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
2. AI uses `find_code_usage` to locate similar function names
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
1. AI uses `find_code_usage` to find all database access calls
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
