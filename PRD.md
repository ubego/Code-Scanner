# Product Requirements Document: Local AI-Driven Code Scanner

## 1. Business Requirements

The primary objective of this project is to implement a software program that **scans a target source code directory** using a separate application to identify potential issues or answer specific user-defined questions.

*   **Core Value Proposition:** Provide developers with an automated, **language-agnostic** background scanner that identifies "undefined behavior," code style inconsistencies, optimization opportunities, and architectural violations (e.g., broken MVC patterns).
*   **Quality Assurance:** The codebase maintains **91% test coverage** with 799+ unit tests ensuring reliability and maintainability.
*   **Target Scope:** The application focuses on **uncommitted changes** in the Git branch by default, ensuring immediate feedback for the developer before code is finalized.
*   **Directory Scope:** The scanner targets **strictly one directory**, but scans it **recursively** (all subdirectories).
*   **Git Requirement:** The target directory **must be a Git repository**. The scanner will fail with an error if Git is not initialized.
*   **Binary File Handling:** Binary files (images, compiled objects, etc.) are **silently skipped** during scanning.
*   **Privacy and Efficiency:** By utilizing a **local AI model**, the application ensures that source code does not leave the local environment while providing the intelligence of a Large Language Model (LLM).
*   **MVP Philosophy:** The initial delivery will be an **MVP (Minimum Viable Product)**, focusing on core functionality without excessive configuration or customization.
*   **Cross-Platform:** The scanner must be **cross-platform**, supporting Windows, macOS, and Linux.
*   **Uninteractive Daemon Mode:** The scanner is designed for **fully uninteractive daemon operation**. No interactive prompts are used—all configuration must be provided via the config file. This enables running as a system service or background process.
*   **Continuous Scanning by Default:** The scanner runs in continuous monitoring mode automatically—there is no separate "watch mode" flag. Once started, it monitors for changes and scans indefinitely until manually stopped (`Ctrl+C`).
*   **Passive Operation:** The scanner operates as a **passive background tool** that only reports issues to a log file. It does **not** modify any source files in the target directory.
*   **Success Criteria:** 
    *   Ability to accurately identify issues based on user-provided queries in a configuration file.
    *   Successful integration with local LLM servers (**LM Studio** and **Ollama**).
    *   Automated re-scanning triggered by Git changes.

---

## 2. Functional Requirements

### 2.1 Git Integration and Change Detection
*   **Default Behavior:** The scanner must monitor the target directory and identify **files with uncommitted changes**.
*   **Change Scope:** Uncommitted changes include:
    *   **Staged files** (added to index with `git add`)
    *   **Unstaged files** (modified but not staged)
    *   **Untracked files** (new files not yet added to Git)
*   **Gitignore Respect:** Files matching patterns in `.gitignore` are **excluded** from scanning, even if they appear as untracked.
*   **Deleted Files:** When a file is deleted (uncommitted deletion), the scanner must **trigger resolution** of any open issues associated with that file. Resolution occurs during the **next full scan cycle** (not immediately upon detection).
*   **Whole File Analysis:** When a file is modified, the scanner analyzes the **entire file content**, not just the diff/changed lines, to ensure full context is available for the AI.
*   **Specific Commit Analysis:** Users must have the option to scan changes **relative to a specific commit hash** (similar to `git reset --soft <hash>`). This allows scanning cumulative changes against a parent branch. After the initial scan, the application continues to monitor for new changes relative to that base.
    *   **Untracked Files:** Untracked files are **still included** in commit-relative mode, regardless of the specified commit.
*   **Rebase/Merge Conflict Handling:** If a rebase or merge with conflict resolution is in progress (detected via `.git/MERGE_HEAD`, `.git/REBASE_HEAD`, or similar), the scanner must **wait for completion** before launching new scans. Poll for resolution status during the wait state.
*   **Monitoring Loop:** The application will run in a continuous loop, polling every **30 seconds** for new updates when idle. When files change during a scan, the scanner uses a **watermark algorithm** for efficient rescanning:
    1.  Each check is executed with the **latest file content** fetched at scan time.
    2.  If files change at check index N, checks N+1 onwards already used fresh content.
    3.  After completing the cycle, only checks 0..N (the "stale" checks) are re-run.
    4.  This repeats until a full cycle completes with no file changes.
    5.  This ensures **all checks run on a consistent worktree snapshot** without redundant work.
*   **Scan Completion Behavior:** After completing all checks in a scan cycle with no mid-scan changes, the scanner **waits for new file changes** before starting another scan. It tracks file modification times and content hashes to detect actual changes—simply having uncommitted files or touched timestamps is not enough to trigger a rescan if content remains identical. This prevents endless scanning loops.
*   **Scanner Output File Exclusion:** The scanner's own output files (`code_scanner_results.md` and `code_scanner_results.md.bak`) are **automatically excluded from change detection**. This prevents infinite rescan loops that would otherwise occur because the scanner writes to these files during each scan cycle.
*   **Startup Behavior:** If no uncommitted changes exist at startup, the application must **enter the wait state immediately** and poll for changes. It should not exit.
*   **Change Detection Thread:** File change detection via Git runs in a **separate thread** from the AI scanning process.
*   **Change Detection Logging:** When changes are detected, the scanner logs which specific files triggered the rescan. This includes:
    *   **New/removed files:** Files added to or removed from the changed files set.
    *   **Modified files:** Files whose content was modified in-place (detected via modification time).
    *   **Scan startup:** List of all changed files at the beginning of each scan cycle.

### 2.2 Query and Analysis Engine
*   **Configuration Input:** The scanner will take a **TOML configuration file** containing user-defined prompts organized into check groups. The configuration file is **read once at startup** (no hot-reload support).
*   **Config File Location:** The TOML config file is specified via **CLI argument**, or defaults to the **scanner's script directory** if not provided.
*   **Missing Config File:** If no config file is found (not provided and not in script directory), **fail with error**.
*   **Empty Checks List:** If the config file exists but contains no checks, **fail with error**.
*   **Strict Configuration Validation:** The scanner validates configuration files strictly:
    *   **Supported Sections:** Only `[llm]` and `[[checks]]` sections are allowed. Any other top-level section (e.g., `[scan]`, `[output]`) causes an immediate error.
    *   **Supported LLM Parameters:** Only `backend`, `host`, `port`, `model`, `timeout`, `context_limit` are allowed in `[llm]`. Unknown parameters cause an error.
    *   **Supported Check Parameters:** Only `pattern` and `checks` are allowed in `[[checks]]`. Unknown parameters (e.g., `name`, `query`) cause an error.
    *   **Error Messages:** Validation errors list the unsupported parameters and show supported alternatives.
*   **Check Groups Structure:** Checks are organized into **groups**, each with a file pattern and list of check items:
    *   **Pattern:** Glob pattern to match files (e.g., `"*.cpp, *.h"` for C++ files, `"*"` for all files).
    *   **Checks:** List of prompt strings to run against matching files.
    *   **Legacy Support:** Simple list of strings format is still supported (converted to single group with `"*"` pattern).
*   **Ignore Patterns:** Check groups with an **empty checks list** define ignore patterns. Files matching these patterns are **excluded from all scanning**:
    *   **File patterns:** Match by extension (e.g., `*.md, *.txt, *.json`)
    *   **Directory patterns:** Match files in directories using `/*dirname*/` syntax (e.g., `/*tests*/`, `/*3rdparty*/`, `/*build*/`)
    *   Example: `[[checks]]\npattern = "*.md, *.txt, /*tests*/, /*vendor*/"\nchecks = []`
    *   Directory patterns support wildcards (e.g., `/*cmake-build-*/` matches `cmake-build-debug`, `cmake-build-release`)
    *   Files matching ignore patterns are silently skipped, reducing noise and improving performance.
    *   Useful for excluding documentation, test directories, third-party code, and build artifacts.
    *   **Unified Filtering:** Ignore patterns are combined with gitignore patterns in the unified `FileFilter` component, ensuring consistent filtering throughout the scan lifecycle (change detection, file iteration, and issue resolution).
*   **Sequential Processing:** Queries must be executed **one by one** against the identified code changes in an **AI scanning thread**.
*   **Pattern-Based Filtering:** For each check group, only files matching the group's pattern are included in the analysis batches.
*   **Aggregated Context:** Each query is sent to the AI with the **entire content of all matching modified files** as context, not file-by-file.
*   **Context Overflow Strategy:** If the combined content of all modified files exceeds the AI model's context window:
    1.  **Group by directory hierarchy:** Batch files from the same directory together, considering the **full directory hierarchy** (e.g., `src/utils/helpers/` first, then `src/utils/`, then `src/`).
    2.  **File-by-file fallback:** If a directory group still exceeds the limit, process files individually.
    3.  **Skip oversized files:** If a single file exceeds the context limit, skip it and log a warning.
    4.  **Merged Results:** When a check runs across multiple batches, all issues from all batches are **merged into a single result set**.
*   **Dynamic Token Tracking:** To prevent context overflow during multi-turn tool calling:
    1.  **Batch Size:** Uses **55% of context limit** for file content, leaving 45% for system prompt, tool iterations, and response.
    2.  **Runtime Tracking:** Scanner tracks accumulated tokens during tool call iterations.
    3.  **Early Termination:** At **85% context usage**, tool calling stops and LLM is instructed to finalize with available information.
    4.  **Fallback:** If overflow still occurs despite tracking, log **ERROR** (indicates limit miscalculation) and skip the batch.
*   **Token Estimation:** Use a **simple character/word ratio** approximation to estimate token count before sending to the LLM.
*   **Continuous Loop:** Once all checks in the list are completed, the scanner **restarts from the beginning** of the check list and continues indefinitely.
*   **AI Interaction:** Each query will be sent to the local AI model.
*   **Context Limit Configuration:** The AI model's context window size is configured in the TOML config:
    *   **Required Parameter:** The `context_limit` parameter is **required** in the `[llm]` section. Missing context_limit is a configuration error that causes immediate failure.
    *   **LM Studio:** The scanner queries context limit from LM Studio API for validation but uses the config value.
    *   **Ollama:** The scanner queries context limit via `/api/show` endpoint for validation.
    *   **Context Limit Validation (Ollama):** When using Ollama, if config `context_limit` exceeds the model's actual limit (from `/api/show`), **fail with error**. If config value is less than or equal to the model's limit, log a warning and continue with config value.
    *   **Recommended Values:** Common values are 4096 (small models), 8192 (medium), 16384 (recommended minimum), 32768 (large), 131072 (very large).
*   **AI Configuration:** Connection settings (host, port, model) must be specified in the TOML config `[llm]` section. No default ports are assumed.
*   **LM Studio Client:** Use the **Python client library for LM Studio** (OpenAI-compatible API client).
*   **Ollama Client:** Use the **native Ollama `/api/chat` endpoint** for message-based interactions with system/user role separation.
*   **Model Selection:**
    *   **LM Studio:** Use the **first/default model** available. No explicit model selection required.
    *   **Ollama:** Model specification is **required** in config (e.g., `model = "qwen3:4b"`).
*   **Client Architecture:** Both `LMStudioClient` and `OllamaClient` must implement a common **abstract base class** (`BaseLLMClient`) to ensure interchangeable usage by the Scanner.
*   **Prompt Format:** Use an optimized prompt structure that is well-understood by LLMs (system prompt with instructions, user prompt with code context).
*   **Response Format:** The scanner must request a **structured JSON response** from the LLM with a fixed schema.
    *   **Strict Prompt Instructions:** The system prompt must explicitly forbid markdown code fences, explanations, and any text outside the JSON object.
    *   **Markdown Fence Stripping:** If the LLM wraps JSON in markdown fences (` ```json ... ``` `), the scanner must **automatically strip them** before parsing.
    *   **JSON Enforcement:** Use the API parameter `response_format={ "type": "json_object" }` to guarantee valid JSON output.
    *   **Response Format Fallback:** If the LLM API does not support `response_format` parameter (returns error), the scanner must **automatically retry without the parameter** and rely on the system prompt for JSON formatting.
    *   Response is an **array of issues** (multiple issues per query are supported).
    *   Each issue contains: file, line number, description, suggested fix.
    *   **No issues found:** Return an empty array `[]`.
    *   **File Path Validation:** Issues with empty file paths or file paths that don't exist in the target directory are silently discarded. This prevents hallucinated file paths from polluting the results.
*   **Reasoning Effort:** The scanner must set **`reasoning_effort = "high"`** in API requests to maximize analysis quality.
*   **Malformed Response Handling:** If the LLM returns invalid JSON or doesn't follow the schema:
    *   **Reformat Request:** First, ask the LLM to **reformat its own response** into valid JSON. This is more effective than blind retrying.
    *   **Retry on failure:** If reformatting fails, retry the original query (no delay/backoff).
    *   **Maximum 3 retries** before skipping the query and logging an error.
    *   Log all retry attempts with attempt count (e.g., "attempt 1/3") to system log.
    *   Common causes: model timeout, context overflow, or model returning explanation text instead of JSON.
*   **LM Studio Connection Handling:**
    *   **Startup Failure:** If the LLM backend (LM Studio or Ollama) is not running or unreachable at startup, **fail immediately** with a clear error message.
    *   **Mid-Session Failure:** If the LLM backend becomes unavailable during scanning, **pause and retry every 10 seconds** until connection is restored. The scanner handles various connection-related errors including:
        *   Lost connection
        *   Connection refused
        *   Connection reset
        *   Network errors
        *   Timeout errors
    *   **Non-Connection Errors:** Other LLM errors (e.g., malformed JSON after retries) are logged and the scanner continues to the next check.

### 2.3 Output and Reporting
*   **Log Generation:** The system must produce a **Markdown log file** named `code_scanner_results.md` as its primary and only User Interface.
*   **Output Location:** The output file is written to the **target directory** root.
*   **Initial Output:** The output file must be **created at startup** (before scanning begins) to provide immediate feedback that the scanner is running.
*   **Scanner Files Exclusion:** The scanner must automatically exclude its own output files (`code_scanner_results.md`, `code_scanner_results.md.bak`, and `code_scanner.log`) from scanning to prevent self-referential analysis.
*   **Change Detection Exclusion:** The Git watcher must exclude `code_scanner_results.md` and `code_scanner_results.md.bak` from triggering rescans. Without this exclusion, every write to the output file would trigger a false "file changed" detection, causing endless rescan loops.
*   **Unified File Filtering:** All file exclusion rules are consolidated into a single `FileFilter` component for efficiency:
    *   **Scanner files:** Direct set lookup (O(1)) for output files.
    *   **Config ignore patterns:** fnmatch matching for patterns like `*.md, *.txt`.
    *   **Gitignore patterns:** In-memory pathspec matching (eliminates subprocess calls).
    *   **Single-pass filtering:** Files are filtered once early in the pipeline, before content is read.
    *   **Graceful degradation:** If pathspec library is unavailable, falls back to git subprocess.
*   **Detailed Findings:** For every issue found, the log must include:
    *   **File path** (exact location)
    *   **Line number** (specific line)
    *   **Issue description** (nature of the issue)
    *   **Suggested fix** (using markdown code blocks)
    *   **Timestamp** (when the issue was detected)
    *   **Check query prompt** (which check/query caused this issue)
*   **Output Organization:** Issues are grouped **by file**. Within each file section, each issue specifies which query/check caused it.
*   **State Management & Persistence:** The system must maintain an internal model of detected issues **in memory only**.
    *   **No Persistence Across Restarts:** State is **not persisted** to disk. Each scanner session starts fresh with no issues.
    *   **Automatic Results Backup:** On startup, if `code_scanner_results.md` exists, the scanner **automatically appends its content** to `code_scanner_results.md.bak` with a timestamp header, then starts with a fresh empty results file. No user prompt is required.
    *   **In-Session Tracking:** Smart matching, deduplication, and resolution tracking apply **within a single session** only.
    *   **Global Lock File:** The scanner creates a lock file at **`~/.code-scanner/code_scanner.lock`** (centralized location) to prevent multiple instances across all projects.
        *   **PID Tracking:** The lock file stores the PID of the running process.
        *   **Stale Lock Detection:** On startup, if a lock file exists, the scanner checks if the stored PID is still running. If the process is no longer active, the stale lock is automatically removed.
        *   **Active Lock:** If the PID is still running, fail with a clear error showing the active PID.
    *   **Smart Matching & Deduplication:** Issues are tracked primarily by **file** and **issue nature/description/code pattern**, not strictly by line number.
        *   **Matching Algorithm:** Issue matching uses **fuzzy string comparison** with a configurable similarity threshold (default: 0.8). This ensures that minor variations in issue descriptions or code snippets (e.g., whitespace changes, slight wording differences) are correctly identified as the same issue.
        *   **Whitespace Normalization:** Code snippets are compared with whitespace-normalized comparison (truncating/collapsing spaces).
        *   If an issue is detected at a different line number (e.g., due to code added above it) but matches an existing open issue's pattern, the scanner must **update the line number** in the existing record rather than creating a duplicate or resolving/re-opening.
    *   **Resolution Tracking:** If the scanner determines that a previously reported issue is no longer present (fixed), it must update the status of that issue in the output to **"RESOLVED"**. The original entry should remain for historical context, but its status changes.
    *   **Scoped Resolution:** Issues are only resolved based on scan results for files that were **actually scanned**. If a file was not included in the current scan (e.g., not in the changed files set), its issues remain unchanged. This prevents false resolution caused by LLM non-determinism.
    *   **Resolved Issues Lifecycle:** Resolved issues remain in the log **indefinitely** for historical tracking. Users may manually remove them if desired.
    *   **Source of Truth:** The scanner is the **authoritative source** for the log file. Any manual edits by the user (e.g., deleting an "OPEN" issue) will be **overwritten** if the scanner detects that the issue still exists in the code during the next scan.
    *   **File Rewriting:** To reflect these status updates, the scanner **rewrites the entire output file** each time the internal model changes.
*   **Real-Time Updates:** The output file is updated **immediately** when new issues are found during scanning, not just at the end of a scan cycle. This provides instant feedback to the user.
*   **System Verbosity:** Verbose logging is **always enabled** (no quiet mode). The output includes system information and detailed runtime data for debugging purposes.
*   **System Log Destination:** Internal system logs (retry attempts, skipped files, warnings, debug info) are written to **both**:
    *   **Console** (stdout/stderr) for real-time monitoring.
    *   **Separate log file** at **`~/.code-scanner/code_scanner.log`** (centralized location shared across all projects).
*   **Colored Console Output:** Console log messages use **ANSI color codes** for improved readability:
    *   **DEBUG:** Gray/dim text for low-priority diagnostic information.
    *   **INFO:** Cyan message with green level label for normal operation messages.
    *   **WARNING:** Yellow highlighting for potential issues that don't stop execution.
    *   **ERROR:** Red highlighting for errors that may affect functionality.
    *   **CRITICAL:** Bold red for severe errors requiring immediate attention.
    *   **Automatic Detection:** Colors are automatically disabled when output is not a TTY (e.g., piped to file).
    *   **Environment Variables:** Respects `NO_COLOR` (disables colors) and `FORCE_COLOR` (enables colors) standards.
    *   **File Logs:** The separate log file (`code_scanner.log`) does **not** contain color codes for clean text storage.
*   **Graceful Shutdown:** On `Ctrl+C` (SIGINT), SIGTERM, or any termination (killing the app):
    *   **Immediate exit** without waiting for the current query to complete.
    *   **Lock file cleanup** is guaranteed via `atexit` handler and signal handlers.
    *   The lock file is removed even on `sys.exit()`, exceptions, or crashes.

---

## 3. Technical Requirements

### 3.1 Technology Stack
*   **Language:** The application must be written in **Python**.
*   **Dependency Management:** The project is required to use either **Poetry or UV** for managing packages and environments.
*   **AI Backend:** The system supports two LLM backends:
    *   **LM Studio:** OpenAI-compatible API server for local LLM inference.
    *   **Ollama:** Native Ollama API server for local LLM inference.
    *   **Backend Selection:** The `backend` key in `[llm]` section is **required**. Valid values: `"lm-studio"` or `"ollama"`. Missing backend specification is a configuration error.
    *   **No Default Backend:** There is no default backend. Users must explicitly choose one.
*   **Configuration Format:** The configuration file must be in **TOML format**.

### 3.2 System Architecture and Logic
*   **Agnostic Design:** The scanner logic must remain **independent of the programming language** found in the target source directory.
*   **Multi-Threaded Architecture:** The application must use at least **two threads**:
    1.  **Git Watcher Thread:** Monitors the target directory for uncommitted changes via Git, polling every 30 seconds.
    2.  **AI Scanner Thread:** Executes checks sequentially against the LM Studio API.
*   **Thread Communication:** When the Git watcher detects changes, it must signal the AI scanner thread to **re-fetch file contents and continue** from the current check position. The scanner preserves its progress through the check list rather than restarting from the beginning.
*   **Runtime Monitoring:** It is critical to include robust logging to identify all possible issues during the application's runtime.
*   **Input Handling:** The application must accept:
    *   A **target directory** as a required CLI argument.
    *   A **configuration file path** as an optional CLI argument (defaults to scanner's script directory).
    *   An optional **Git commit hash** to scan changes relative to a specific commit.

### 3.3 AI Tooling for Context Expansion
The scanner provides **AI Tools** (function calling) that allow the LLM to interactively request additional information from the broader codebase beyond the modified files. This enables sophisticated architectural checks and cross-file analysis.

**Prerequisites:**
*   **Universal Ctags** must be installed for symbol indexing. The ctags-based tools (find_definition, find_symbols) require Universal Ctags to be available in the system PATH.
*   **ripgrep** must be installed for fast code search. The search_text tool requires ripgrep (`rg`) to be available in the system PATH.

**Available AI Tools (13 tools):**

1.  **search_text(patterns, is_regex, match_whole_word, case_sensitive, file_pattern, offset):**
    *   Searches the entire repository for text patterns (strings, function names, class names, variables, etc.).
    *   `patterns`: Single string or array of strings to search for.
    *   `is_regex`: Boolean (default: false) - treat patterns as regular expressions.
    *   `match_whole_word`: Boolean (default: true) - match only whole words (ignored when is_regex is true).
    *   `case_sensitive`: Boolean (default: false) - case-sensitive matching.
    *   `file_pattern`: Optional glob pattern to filter files (e.g., "*.py").
    *   Returns file paths, line numbers, and code snippets for all matches.
    *   **Ripgrep-Powered:** Uses `ripgrep` for fast search. Ripgrep respects `.gitignore` and skips hidden files by default.
    *   **Smart Ordering:** Definitions are prioritized before usages in results.
    *   **Pagination:** Results are paginated (50 matches per page). Use `offset` parameter to fetch additional pages when `has_more` is `true`.
    *   Response includes: `total_matches`, `returned_count`, `offset`, `has_more`, `next_offset`, `matches_by_pattern`.
    *   Use case: Verify symbol definitions, find all usages, check naming patterns, search for specific code constructs.

2.  **read_file(file_path, start_line, end_line):**
    *   Reads the content of any file in the repository, even if it has no uncommitted changes.
    *   Supports line-range parameters for reading specific sections.
    *   Large files are automatically chunked (≤4000 tokens per chunk by default).
    *   **Enhanced Validation:** File paths are validated with helpful error messages including:
        *   Suggestions for similar files when path not found (e.g., "Did you mean: main.py, utils.py?").
        *   Clear feedback for directory traversal attempts or invalid paths.
    *   **Pagination:** Response includes `has_more` and `next_start_line` fields to guide subsequent read requests.
    *   **Helpful Hints:** Response includes hints to guide the LLM:
        *   For complete files: "This is the COMPLETE file (N lines). No need to read it again."
        *   For files mostly read: "You now have 85% of this file. Consider proceeding with analysis."
    *   Use case: Check related files for context, verify patterns in other modules, read configuration files.

3.  **list_directory(directory_path, recursive, offset):**
    *   Lists all files and subdirectories in a specified directory.
    *   Supports recursive listing to explore entire directory trees.
    *   **Enhanced Validation:** Directory paths are validated with suggestions for similar directories when not found.
    *   **File Size Information:** Each file includes line count for text files, allowing the LLM to plan which files to read and whether chunking may be needed. Format: `{"path": "src/file.py", "lines": 150}`.
    *   **Pagination:** Results are paginated (100 items per page). Use `offset` parameter to fetch additional pages when `has_more` is `true`.
    *   Response includes: `total_items`, `returned_count`, `offset`, `has_more`, `next_offset`.
    *   Hidden directories (starting with `.`) and common build directories (`node_modules`, `__pycache__`, etc.) are automatically filtered.
    *   Use case: Explore project structure, discover available modules, plan file reading strategy.

4.  **get_file_diff(file_path, context_lines):**
    *   Gets the git diff for a specific file relative to HEAD.
    *   Returns only changed lines in unified diff format—more token-efficient than read_file.
    *   `context_lines`: Number of unchanged lines around each change (default: 3, max: 10).
    *   Use case: Understand what was modified without reading entire file.

5.  **get_file_summary(file_path):**
    *   Gets structural summary of a file using ctags index without reading all content.
    *   Returns classes, functions, variables, imports with line numbers.
    *   Much more token-efficient than read_file when only file structure is needed.
    *   Use case: Understand file organization before deciding what to read in detail.

6.  **symbol_exists(symbol, symbol_type):**
    *   Quick O(1) lookup using ctags index to check if a symbol exists in the repository.
    *   `symbol_type`: Optional filter (function, class, variable, constant, type, interface).
    *   Returns location if found, with up to 10 locations.
    *   **Critical:** Use this BEFORE reporting "undefined symbol" issues to avoid false positives.
    *   Use case: Verify a symbol exists before flagging it as undefined.

7.  **find_definition(symbol, kind):**
    *   Find where a symbol is defined (Go to Definition functionality).
    *   Uses ctags index for instant lookup.
    *   `kind`: Optional filter by symbol kind (function, class, method, etc.).
    *   Returns file path, line number, and code pattern.
    *   Use case: Navigate directly to symbol definitions for cross-file analysis.


8.  **find_symbols(pattern, kind, case_sensitive):**
    *   Search for symbols matching a pattern across the entire repository.
    *   Supports wildcards: `*` (any chars), `?` (single char).
    *   `kind`: Optional filter by symbol kind.
    *   `case_sensitive`: Default false for flexible matching.
    *   Use case: Find symbols by naming convention (e.g., `test_*`, `*Handler`).


9.  **get_enclosing_scope(file_path, line_number):**
    *   Identify and retrieve the content of the innermost function, class, or method containing a specific line.
    *   Returns symbol name, kind, start/end lines, and the complete source code of the scope.
    *   Smartly truncates excessively large scopes to respect context limits.
    *   Use case: Retrieve full function context when analyzing a specific bug or line, completely avoiding manual line counting.

10. **find_usages(symbol, file_path, include_definitions):**
    *   Find all references to a symbol across the repository.
    *   Combines text search with ctags intelligence to distinguish definitions from usages.
    *   `file_path`: Optional filter to search within a specific file.
    *   `include_definitions`: Boolean to optionally include definition sites in results.
    *   Use case: Impact analysis (who calls this function?), finding all instantiations of a class, checking for unused code.

**Pagination Pattern:**

All tools use a consistent pagination pattern to enable the LLM to fetch more results when needed:
*   `offset`: Starting index (0-based). Default is 0.
*   `has_more`: Boolean indicating whether more results exist beyond current page.
*   `next_offset`: If `has_more` is `true`, the value to use for next request.
*   Warning messages explicitly instruct the LLM how to fetch more results.

**Tool Execution Workflow:**

1.  Scanner sends initial query with tool definitions to LLM.
2.  If LLM requests tools, scanner executes them and returns results.
3.  LLM receives tool results and can either:
    *   Request additional tools for more context.
    *   Provide final analysis with detected issues.
4.  Process repeats iteratively (max 10 iterations to prevent infinite loops).
5.  All tool results include success/error status and optional warnings for partial content.

**Security and Safety:**

*   All file paths are validated to be within the target repository (prevents directory traversal attacks).
*   Binary files are automatically detected and rejected.
*   Partial content warnings ensure LLM is aware when it's not seeing complete information.
*   Tool execution failures are communicated to the LLM as error messages.

### 3.4 Text Processing Utilities

The scanner includes a dedicated `text_utils` module providing advanced text processing capabilities:

**String Similarity Functions:**
*   **Levenshtein Distance:** Calculate edit distance between strings for fuzzy matching.
*   **Similarity Ratio:** Compute similarity ratio (0.0 to 1.0) between strings using SequenceMatcher.
*   **Fuzzy Matching:** Compare strings with configurable similarity threshold (default: 0.8).
*   **Find Similar Strings:** Find top N most similar strings from a list of candidates.

**Output Management:**
*   **Truncation with Hints:** Large outputs are automatically truncated with actionable hints:
    *   Maximum 2,000 lines per output (configurable).
    *   Maximum 50KB per output (configurable).
    *   Truncation includes helpful messages: "Output truncated. Use search_text with specific patterns to narrow results."
*   **Whitespace Normalization:** Collapse multiple whitespace characters for consistent comparison.

**Validation Helpers:**
*   **File Path Validation:** Comprehensive validation with:
    *   Empty path detection with clear error messages.
    *   Path traversal prevention (denies `..` escaping repository).
    *   File existence checking with similar file suggestions.
    *   Directory vs file detection.
*   **Line Number Validation:** Validates 1-based line numbers against file length.
*   **File Suggestions:** When a file is not found, suggests similar files using:
    *   Recursive search through repository (skipping hidden/build directories).
    *   Similarity ranking using Levenshtein distance.
    *   Returns top 5 most similar files by default.

**Integration with Existing Architecture:**

*   Tools are integrated into `LMStudioClient` and `OllamaClient` via the `tools` parameter in the `query()` method.
*   Both backends support OpenAI-compatible function calling API.
*   System prompt is enhanced to inform the LLM about available tools and usage guidelines.
*   The `reasoning_effort = "high"` parameter continues to be set for deep analysis.

### 3.4 Execution Workflow
1.  **Check for lock file.** If exists and PID is running, fail with error. If stale (PID not running), remove and continue. Create lock file with current PID.
2.  **Backup existing output file.** If `code_scanner_results.md` exists, append to `.bak` with timestamp, then start with a fresh empty results file. Print lock/log file paths.
3.  Initialize by reading the **TOML config file**.
4.  Start the **Git watcher thread** to monitor for changes every 30 seconds.
5.  Start the **AI scanner thread** with **AI tool executor** initialized.
6.  **Wait Loop:** If no uncommitted changes (relative to HEAD or specified commit) exist, the scanner **must idle/wait**.
7.  **Scanning:** When changes are found, identify the **entire content** of the modified files.
    *   *Context Check:* If combined files exceed context limit, apply **context overflow strategy** (group by directory, then file-by-file).
    *   *Skip oversized:* If a single file exceeds context limit, skip and warn.
8.  Trigger the **LLM query loop with tool support**, processing check prompts sequentially:
    9.  Communicate with the **LM Studio or Ollama local server** via their APIs with tool definitions.
        *   *Tool Execution:* If LLM requests tools, execute them and send results back in a conversation loop.
        *   *Retry on failure:* If LLM returns malformed JSON, retry immediately (max 3 retries).
    10. **Graceful Interrupts:** If a Git change is detected during a query, the scanner must **finish the current query** before restarting the loop.
    11. **Update Output (Incremental):** After *each* completed query:
        *   Update the internal model with new findings.
        *   **immediately rewrite the output Markdown file** to provide real-time feedback.
12. Upon completing all checks, **loop back** to the first check and continue.
13. If the Git watcher detects new changes during scanning, the scanner uses the **watermark algorithm**: complete the current cycle, then rescan only the checks that ran before the change point (checks 0..N where N is the index where the change was detected). This repeats until no changes occur during a cycle.
14. On **SIGINT**, immediately exit and remove lock file.

### 3.5 Service Installation
The scanner can be installed as a system service to start automatically on boot. Autostart scripts are provided in the `scripts/` directory:

*   **Linux:** `scripts/autostart-linux.sh` - Creates a systemd user service. See [docs/autostart-linux.md](docs/autostart-linux.md).
*   **macOS:** `scripts/autostart-macos.sh` - Creates a LaunchAgent plist. See [docs/autostart-macos.md](docs/autostart-macos.md).
*   **Windows:** `scripts/autostart-windows.bat` - Creates a Task Scheduler task. See [docs/autostart-windows.md](docs/autostart-windows.md).

All scripts include:
*   **60-second startup delay** to allow LLM servers to initialize.
*   **Test launch** before registering the service.
*   **Legacy service detection** and removal.
*   **Interactive prompts** for project paths and config files.

### 3.6 Sample Configuration Checks
The following checks are provided as **examples only** and can be completely customized or replaced by the user in the TOML configuration file. Checks are organized into **groups by file pattern**:

**C++/Qt-specific checks (pattern: `"*.cpp, *.h, *.cxx, *.hpp"`):**
*   Check that iteration continues automatically until the final result, without requiring user prompts to proceed.
*   Check that `constexpr` and compile-time programming techniques are applied where appropriate.
*   Check that stack allocation is preferred over heap allocation whenever possible.
*   Check that string literals are handled through `QStringView` variables.
*   Check that string literals used multiple times are stored in named `QStringView` constants instead of being repeated.
*   Check that comments provide meaningful context or rationale and avoid restating obvious code behavior.
*   Check that functions are implemented in `.cpp` files rather than `.h` files.

**Architectural checks leveraging AI tools (pattern: `"*"`):**
*   Check for architectural violations (e.g., MVC pattern breakage) using `search_text` to verify layer separation.
*   Check for inconsistent naming patterns across the codebase using `list_directory` and `read_file`.
*   Check for duplicate or similar function implementations using `search_text`.

**General checks for all files (pattern: `"*"`):**
*   Check for any detectable errors and suggest code simplifications where possible.
*   Check for unused files or dead code.

**Example TOML configuration (LM Studio):**
```toml
[llm]
backend = "lm-studio"
host = "localhost"
port = 1234
# model = "specific-model-name"  # Optional for LM Studio
context_limit = 32768

[[checks]]
pattern = "*.cpp, *.h"
checks = [
    "Check for memory leaks",
    "Check that RAII is used properly"
]

[[checks]]
pattern = "*"
checks = [
    "Check for unused code",
    "Check for architectural violations in MVC pattern"
]
```

**Example TOML configuration (Ollama):**
```toml
[llm]
backend = "ollama"
host = "localhost"
port = 11434
model = "qwen3:4b"  # Required for Ollama
context_limit = 16384  # Minimum 16384 recommended

[[checks]]
pattern = "*.py"
checks = [
    "Check for type hints",
    "Check for docstrings",
    "Check for duplicate function names across modules"
]
```

***

**Analogy for Understanding:** 
Think of this code scanner as a **diligent proofreader** sitting over a writer's shoulder. Instead of waiting for the writer to finish the whole book, the proofreader only looks at the sentences the writer just typed (the uncommitted changes). The proofreader uses a specialized guidebook (the config file) to check for specific mistakes. 

**With AI Tooling**, the proofreader now has a **library card**. Instead of just looking at the new sentences, the proofreader can get up, go to the bookshelf (the codebase), and pull out an old chapter (another file) to make sure a character's name is still spelled correctly or that a plot point remains consistent. The proofreader can even browse the table of contents (directory listings) to understand the book's structure before making recommendations.