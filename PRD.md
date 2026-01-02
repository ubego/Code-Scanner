# Product Requirements Document: Local AI-Driven Code Scanner

## 1. Business Requirements

The primary objective of this project is to implement a software program that **scans a target source code directory** using a separate application to identify potential issues or answer specific user-defined questions.

*   **Core Value Proposition:** Provide developers with an automated, **language-agnostic** background scanner that identifies "undefined behavior," code style inconsistencies, optimization opportunities, and architectural violations (e.g., broken MVC patterns).
*   **Quality Assurance:** The codebase maintains **87% test coverage** with 482 unit tests ensuring reliability and maintainability.
*   **Target Scope:** The application focuses on **uncommitted changes** in the Git branch by default, ensuring immediate feedback for the developer before code is finalized.
*   **Directory Scope:** The scanner targets **strictly one directory**, but scans it **recursively** (all subdirectories).
*   **Git Requirement:** The target directory **must be a Git repository**. The scanner will fail with an error if Git is not initialized.
*   **Binary File Handling:** Binary files (images, compiled objects, etc.) are **silently skipped** during scanning.
*   **Privacy and Efficiency:** By utilizing a **local AI model**, the application ensures that source code does not leave the local environment while providing the intelligence of a Large Language Model (LLM).
*   **MVP Philosophy:** The initial delivery will be an **MVP (Minimum Viable Product)**, focusing on core functionality without excessive configuration or customization.
*   **Cross-Platform:** The scanner must be **cross-platform**, supporting Windows, macOS, and Linux.
*   **Interactive Mode Only:** The scanner is designed for **interactive terminal use only**. Non-interactive environments (CI, daemons) are not supported.
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
*   **Monitoring Loop:** The application will run in a continuous loop. If changes are detected via Git, the scanner will **continue from the last completed check** rather than restarting from the beginning—this ensures progress is preserved and avoids redundant re-scanning. If no changes occur, the application will **poll every 30 seconds** for new updates.
*   **Startup Behavior:** If no uncommitted changes exist at startup, the application must **enter the wait state immediately** and poll for changes. It should not exit.
*   **Change Detection Thread:** File change detection via Git runs in a **separate thread** from the AI scanning process.

### 2.2 Query and Analysis Engine
*   **Configuration Input:** The scanner will take a **TOML configuration file** containing user-defined prompts organized into check groups. The configuration file is **read once at startup** (no hot-reload support).
*   **Config File Location:** The TOML config file is specified via **CLI argument**, or defaults to the **scanner's script directory** if not provided.
*   **Missing Config File:** If no config file is found (not provided and not in script directory), **fail with error**.
*   **Empty Checks List:** If the config file exists but contains no checks, **fail with error**.
*   **Strict Configuration Validation:** The scanner validates configuration files strictly:
    *   **Supported Sections:** Only `[llm]` and `[[checks]]` sections are allowed. Any other top-level section (e.g., `[scan]`, `[output]`) causes an immediate error.
    *   **Supported LLM Parameters:** Only `backend`, `host`, `port`, `model`, `timeout`, `context_limit` are allowed in `[llm]`. Unknown parameters cause an error.
    *   **Supported Check Parameters:** Only `pattern` and `rules` are allowed in `[[checks]]`. Unknown parameters (e.g., `name`, `query`) cause an error.
    *   **Error Messages:** Validation errors list the unsupported parameters and show supported alternatives.
*   **Check Groups Structure:** Checks are organized into **groups**, each with a file pattern and list of rules:
    *   **Pattern:** Glob pattern to match files (e.g., `"*.cpp, *.h"` for C++ files, `"*"` for all files).
    *   **Rules:** List of prompt strings to run against matching files.
    *   **Legacy Support:** Simple list of strings format is still supported (converted to single group with `"*"` pattern).
*   **Sequential Processing:** Queries must be executed **one by one** against the identified code changes in an **AI scanning thread**.
*   **Pattern-Based Filtering:** For each check group, only files matching the group's pattern are included in the analysis batches.
*   **Aggregated Context:** Each query is sent to the AI with the **entire content of all matching modified files** as context, not file-by-file.
*   **Context Overflow Strategy:** If the combined content of all modified files exceeds the AI model's context window:
    1.  **Group by directory hierarchy:** Batch files from the same directory together, considering the **full directory hierarchy** (e.g., `src/utils/helpers/` first, then `src/utils/`, then `src/`).
    2.  **File-by-file fallback:** If a directory group still exceeds the limit, process files individually.
    3.  **Skip oversized files:** If a single file exceeds the context limit, skip it and log a warning.
    4.  **Merged Results:** When a check runs across multiple batches, all issues from all batches are **merged into a single result set**.
*   **Token Estimation:** Use a **simple character/word ratio** approximation to estimate token count before sending to the LLM.
*   **Continuous Loop:** Once all checks in the list are completed, the scanner **restarts from the beginning** of the check list and continues indefinitely.
*   **AI Interaction:** Each query will be sent to the local AI model.
*   **Context Limit Detection:** The AI model's context window size handling varies by backend:
    *   **LM Studio:** Query context limit from LM Studio API at runtime.
    *   **Ollama:** Query context limit via `/api/show` endpoint.
    *   **Config Override:** If `context_limit` is specified in the TOML config `[llm]` section, use that value.
    *   **Context Limit Validation (Ollama):** When using Ollama, if config `context_limit` exceeds the model's actual limit (from `/api/show`), **fail with error**. If config value is less than or equal to the model's limit, log a warning and continue with config value.
    *   **Interactive Fallback:** If the API does not return a valid context limit and running interactively, **prompt the user** to enter the context limit manually. Display common values (4096, 8192, 16384, 32768, 131072) as guidance.
    *   **Non-Interactive Failure:** If the API does not return a valid context limit and running non-interactively, the application must **fail with a clear error** instructing the user to set `context_limit` in config.toml.
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
*   **Reasoning Effort:** The scanner must set **`reasoning_effort = "high"`** in API requests to maximize analysis quality.
*   **Malformed Response Handling:** If the LLM returns invalid JSON or doesn't follow the schema:
    *   **Reformat Request:** First, ask the LLM to **reformat its own response** into valid JSON. This is more effective than blind retrying.
    *   **Retry on failure:** If reformatting fails, retry the original query (no delay/backoff).
    *   **Maximum 3 retries** before skipping the query and logging an error.
    *   Log all retry attempts with attempt count (e.g., "attempt 1/3") to system log.
    *   Common causes: model timeout, context overflow, or model returning explanation text instead of JSON.
*   **LM Studio Connection Handling:**
    *   **Startup Failure:** If the LLM backend (LM Studio or Ollama) is not running or unreachable at startup, **fail immediately** with a clear error message.
    *   **Mid-Session Failure:** If the LLM backend becomes unavailable during scanning, **pause and retry every 10 seconds** until connection is restored.

### 2.3 Output and Reporting
*   **Log Generation:** The system must produce a **Markdown log file** named `code_scanner_results.md` as its primary and only User Interface.
*   **Output Location:** The output file is written to the **target directory** root.
*   **Initial Output:** The output file must be **created at startup** (before scanning begins) to provide immediate feedback that the scanner is running.
*   **Scanner Files Exclusion:** The scanner must automatically exclude its own output files (`code_scanner_results.md` and `code_scanner.log`) from scanning to prevent self-referential analysis.
*   **Detailed Findings:** For every issue found, the log must include:
    *   **File path** (exact location)
    *   **Line number** (specific line)
    *   **Issue description** (nature of the issue)
    *   **Suggested fix** (using markdown code blocks)
    *   **Timestamp** (when the issue was detected)
    *   **Check query prompt** (which check/query caused this issue)
*   **Output Organization:** Issues are grouped **by file**. Within each file section, each issue specifies which query/check caused it.
*   **State Management & Persistence:** The system must maintain an internal model of detected issues **in memory only**.
    *   **No Persistence Across Restarts:** State is **not persisted** to disk. Each scanner session starts fresh.
    *   **Overwrite Confirmation:** On startup, if `code_scanner_results.md` exists, **prompt the user** (interactive only) to confirm deletion/overwrite. If the user declines (answers "No"), the application must **exit immediately**.
    *   **In-Session Tracking:** Smart matching, deduplication, and resolution tracking apply **within a single session** only.
    *   **Lock File:** The scanner must create a lock file named **`.code_scanner.lock`** in the **scanner's script directory** (not the target directory) to prevent multiple instances from running simultaneously.
        *   **Stale Locks:** If a lock file exists, **fail with a clear error message**. The user must **manually delete** the file if it is stale (e.g., after a crash). There is no automatic stale lock detection.
    *   **Smart Matching & Deduplication:** Issues are tracked primarily by **file** and **issue nature/description/code pattern**, not strictly by line number.
        *   **Matching Algorithm:** Issue matching compares the source code snippet with **whitespace-normalized comparison** (truncating/collapsing spaces). This algorithm may be improved in future versions.
        *   If an issue is detected at a different line number (e.g., due to code added above it) but matches an existing open issue's pattern, the scanner must **update the line number** in the existing record rather than creating a duplicate or resolving/re-opening.
    *   **Resolution Tracking:** If the scanner determines that a previously reported issue is no longer present (fixed), it must update the status of that issue in the output to **"RESOLVED"**. The original entry should remain for historical context, but its status changes.
    *   **Resolved Issues Lifecycle:** Resolved issues remain in the log **indefinitely** for historical tracking. Users may manually remove them if desired.
    *   **Source of Truth:** The scanner is the **authoritative source** for the log file. Any manual edits by the user (e.g., deleting an "OPEN" issue) will be **overwritten** if the scanner detects that the issue still exists in the code during the next scan.
    *   **File Rewriting:** To reflect these status updates, the scanner **rewrites the entire output file** each time the internal model changes.
*   **Real-Time Updates:** The output file is updated **immediately** when new issues are found during scanning, not just at the end of a scan cycle. This provides instant feedback to the user.
*   **System Verbosity:** Verbose logging is **always enabled** (no quiet mode). The output includes system information and detailed runtime data for debugging purposes.
*   **System Log Destination:** Internal system logs (retry attempts, skipped files, warnings, debug info) are written to **both**:
    *   **Console** (stdout/stderr) for real-time monitoring.
    *   **Separate log file** named `code_scanner.log` in the target directory.
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

### 3.3 Execution Workflow
1.  **Check for lock file.** If exists, fail with error. Otherwise, create lock file.
2.  **Check for existing output file.** If `code_scanner_results.md` exists, prompt user to confirm overwrite.
3.  Initialize by reading the **TOML config file**.
4.  Start the **Git watcher thread** to monitor for changes every 30 seconds.
5.  Start the **AI scanner thread**.
6.  **Wait Loop:** If no uncommitted changes (relative to HEAD or specified commit) exist, the scanner **must idle/wait**.
7.  **Scanning:** When changes are found, identify the **entire content** of the modified files.
    *   *Context Check:* If combined files exceed context limit, apply **context overflow strategy** (group by directory, then file-by-file).
    *   *Skip oversized:* If a single file exceeds context limit, skip and warn.
8.  Trigger the **LLM query loop**, processing check prompts sequentially.
    9.  Communicate with the **LM Studio local server** via its API.
        *   *Retry on failure:* If LLM returns malformed JSON, retry immediately (max 3 retries).
    10. **Graceful Interrupts:** If a Git change is detected during a query, the scanner must **finish the current query** before restarting the loop.
    11. **Update Output (Incremental):** After *each* completed query:
        *   Update the internal model with new findings.
        *   **immediatelyrewrite the output Markdown file** to provide real-time feedback.
12. Upon completing all checks, **loop back** to the first check and continue.
13. If the Git watcher detects new changes during scanning, the scanner **continues from the current check** with refreshed file contents (preserving progress rather than restarting).
14. On **SIGINT**, immediately exit and remove lock file.

### 3.4 Sample Configuration Checks
The following checks are provided as **examples only** and can be completely customized or replaced by the user in the TOML configuration file. Checks are organized into **groups by file pattern**:

**C++/Qt-specific checks (pattern: `"*.cpp, *.h, *.cxx, *.hpp"`):**
*   Check that iteration continues automatically until the final result, without requiring user prompts to proceed.
*   Check that `constexpr` and compile-time programming techniques are applied where appropriate.
*   Check that stack allocation is preferred over heap allocation whenever possible.
*   Check that string literals are handled through `QStringView` variables.
*   Check that string literals used multiple times are stored in named `QStringView` constants instead of being repeated.
*   Check that comments provide meaningful context or rationale and avoid restating obvious code behavior.
*   Check that functions are implemented in `.cpp` files rather than `.h` files.

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
    "Check for unused code"
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
    "Check for docstrings"
]
```

***

**Analogy for Understanding:** 
Think of this code scanner as a **diligent proofreader** sitting over a writer's shoulder. Instead of waiting for the writer to finish the whole book, the proofreader only looks at the sentences the writer just typed (the uncommitted changes). The proofreader uses a specialized guidebook (the config file) to check for specific mistakes, and if they find one, they point to the exact line and offer a sticky note with a suggested correction—all while keeping their notes in a private journal (the log file).