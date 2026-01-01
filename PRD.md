# Product Requirements Document: Local AI-Driven Code Scanner

## 1. Business Requirements

The primary objective of this project is to implement a software program that **scans a target source code directory** using a separate application to identify potential issues or answer specific user-defined questions.

*   **Core Value Proposition:** Provide developers with an automated, **language-agnostic** background scanner that identifies "undefined behavior," code style inconsistencies, optimization opportunities, and architectural violations (e.g., broken MVC patterns).
*   **Target Scope:** The application focuses on **uncommitted changes** in the Git branch by default, ensuring immediate feedback for the developer before code is finalized.
*   **Privacy and Efficiency:** By utilizing a **local AI model**, the application ensures that source code does not leave the local environment while providing the intelligence of a Large Language Model (LLM).
*   **MVP Philosophy:** The initial delivery will be an **MVP (Minimum Viable Product)**, focusing on core functionality without excessive configuration or customization.
*   **Passive Operation:** The scanner operates as a **passive background tool** that only reports issues to a log file. It does **not** modify any source files in the target directory.
*   **Success Criteria:** 
    *   Ability to accurately identify issues based on user-provided queries in a configuration file.
    *   Successful integration with a local LLM server (LM Studio).
    *   Automated re-scanning triggered by Git changes.

---

## 2. Functional Requirements

### 2.1 Git Integration and Change Detection
*   **Default Behavior:** The scanner must monitor the target directory and identify **files with uncommitted changes**.
*   **Whole File Analysis:** When a file is modified, the scanner analyzes the **entire file content**, not just the diff/changed lines, to ensure full context is available for the AI.
*   **Specific Commit Analysis:** Users must have the option to scan changes **relative to a specific commit hash** (similar to `git reset --soft <hash>`). This allows scanning cumulative changes against a parent branch. After the initial scan, the application continues to monitor for new changes relative to that base.
*   **Monitoring Loop:** The application will run in a continuous loop. If changes are detected via Git, the scanner must **restart from the beginning** of the check list. If no changes occur, the application will **poll every 30 seconds** for new updates.
*   **Startup Behavior:** If no uncommitted changes exist at startup, the application must **enter the wait state immediately** and poll for changes. It should not exit.
*   **Change Detection Thread:** File change detection via Git runs in a **separate thread** from the AI scanning process.

### 2.2 Query and Analysis Engine
*   **Configuration Input:** The scanner will take a **TOML configuration file** containing a simple list of user-defined prompts. The configuration file is **read once at startup**.
*   **Structure:** Checks in the TOML file are simple prompt strings without complex metadata.
*   **Sequential Processing:** Queries must be executed **one by one** against the identified code changes in an **AI scanning thread**.
*   **Continuous Loop:** Once all checks in the list are completed, the scanner **restarts from the beginning** of the check list and continues indefinitely.
*   **AI Interaction:** Each query will be sent to the local AI model.
*   **Context Safety:** If a file is too large for the AI model's context window, the scanner must **skip analysis** for that file and log a warning to the system log (not the user output).
*   **AI Configuration:** The scanner should default to connecting to LM Studio at `localhost` with default ports, but these values (host, port, model) must be overridable via the TOML config.

### 2.3 Output and Reporting
*   **Log Generation:** The system must produce a **Markdown log file** (`.md`) as its primary and only User Interface.
*   **Detailed Findings:** For every issue found, the log must specify the **exact file**, the **specific line number**, the nature of the issue, and a **suggested implementation fix** (using markdown code blocks).
*   **State Management & Persistence:** The system must maintain an internal model of detected issues.
    *   **Startup Restoration:** On startup, the scanner must **read the existing output file** to rebuild its internal state. this ensures previously resolved or open issues are tracked correctly across sessions.
    *   **Smart Matching & Deduplication:** Issues are tracked primarily by **file** and **issue nature/description/code pattern**, not strictly by line number.
        *   If an issue is detected at a different line number (e.g., due to code added above it) but matches an existing open issue's pattern, the scanner must **update the line number** in the existing record rather than creating a duplicate or resolving/re-opening.
    *   **Resolution Tracking:** If the scanner determines that a previously reported issue is no longer present (fixed), it must update the status of that issue in the output to **"RESOLVED"**. The original entry should remain for historical context, but its status changes.
    *   **Source of Truth:** The scanner is the **authoritative source** for the log file. Any manual edits by the user (e.g., deleting an "OPEN" issue) will be **overwritten** if the scanner detects that the issue still exists in the code during the next scan.
    *   **File Rewriting:** To reflect these status updates, the scanner **rewrites the entire output file** each time the internal model changes.
*   **System Verbosity:** The output should include system information and **verbose logging** to capture all issues and runtime data for debugging purposes.

---

## 3. Technical Requirements

### 3.1 Technology Stack
*   **Language:** The application must be written in **Python**.
*   **Dependency Management:** The project is required to use either **Poetry or UV** for managing packages and environments.
*   **AI Backend:** The system requires a running **LM Studio server**. Default connection settings should be used unless overridden in the config.
*   **Configuration Format:** The configuration file must be in **TOML format**.

### 3.2 System Architecture and Logic
*   **Agnostic Design:** The scanner logic must remain **independent of the programming language** found in the target source directory.
*   **Multi-Threaded Architecture:** The application must use at least **two threads**:
    1.  **Git Watcher Thread:** Monitors the target directory for uncommitted changes via Git, polling every 30 seconds.
    2.  **AI Scanner Thread:** Executes checks sequentially against the LM Studio API.
*   **Thread Communication:** When the Git watcher detects changes, it must signal the AI scanner thread to **restart from the beginning** of the check list.
*   **Runtime Monitoring:** It is critical to include robust logging to identify all possible issues during the application's runtime.
*   **Input Handling:** The application must accept a configuration file for queries and support optional Git commit hashes as input arguments.

### 3.3 Execution Workflow
1.  Initialize by **reading the existing output file** (to restore state) and the **TOML config file**.
2.  Start the **Git watcher thread** to monitor for changes every 30 seconds.
3.  Start the **AI scanner thread**.
4.  **Wait Loop:** If no uncommitted changes (relative to HEAD or specified commit) exist, the scanner **must idle/wait**.
5.  **Scanning:** When changes are found, identify the **entire content** of the modified files.
    *   *Check:* If file > context limit, skip and warn.
6.  Trigger the **LLM query loop**, processing check prompts sequentially.
7.  Communicate with the **LM Studio local server** via its API.
8.  **Graceful Interrupts:** If a Git change is detected during a query, the scanner must **finish the current query** before restarting the loop (Finish-Then-Restart strategy).
9.  **Update Output:**
    *   Update the internal model with new findings.
    *   Mark fixed issues as "RESOLVED".
    *   **Rewrite the output Markdown file** with the full list of detected and resolved issues.
10. Upon completing all checks, **loop back** to the first check and continue.
11. If the Git watcher detects new changes, **restart the scanner** from the beginning of the check list.

### 3.4 Sample Configuration Checks
The following checks are provided as **examples only** and can be completely customized or replaced by the user in the TOML configuration file. These samples demonstrate C++/Qt-specific checks but the scanner supports **any language**:

*   **Autonomous Iteration:** Check that iteration continues automatically until the final result, without requiring user prompts to proceed.
*   **Compile-Time Programming:** Check that `constexpr` and compile-time programming techniques are applied where appropriate.
*   **Stack Allocation Preference:** Check that stack allocation is preferred over heap allocation whenever possible.
*   **QStringView for Literals:** Check that string literals are handled through `QStringView` variables.
*   **Named QStringView Constants:** Check that string literals used multiple times are stored in named `QStringView` constants instead of being repeated.
*   **Error Detection:** Check for any detectable errors and suggest code simplifications where possible.
*   **Meaningful Comments:** Check that comments provide meaningful context or rationale and avoid restating obvious code behavior.
*   **Implementation in .cpp Files:** Check that functions are implemented in `.cpp` files rather than `.h` files.

***

**Analogy for Understanding:** 
Think of this code scanner as a **diligent proofreader** sitting over a writer's shoulder. Instead of waiting for the writer to finish the whole book, the proofreader only looks at the sentences the writer just typed (the uncommitted changes). The proofreader uses a specialized guidebook (the config file) to check for specific mistakes, and if they find one, they point to the exact line and offer a sticky note with a suggested correction—all while keeping their notes in a private journal (the log file).