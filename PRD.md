# Product Requirements Document: Local AI-Driven Code Scanner

## 1. Business Requirements

The primary objective of this project is to implement a software program that **scans a target source code directory** using a separate application to identify potential issues or answer specific user-defined questions.

*   **Core Value Proposition:** Provide developers with an automated, **language-agnostic** background scanner that identifies "undefined behavior," code style inconsistencies, optimization opportunities, and architectural violations (e.g., broken MVC patterns).
*   **Target Scope:** The application focuses on **uncommitted changes** in the Git branch by default, ensuring immediate feedback for the developer before code is finalized.
*   **Privacy and Efficiency:** By utilizing a **local AI model**, the application ensures that source code does not leave the local environment while providing the intelligence of a Large Language Model (LLM).
*   **MVP Philosophy:** The initial delivery will be an **MVP (Minimum Viable Product)**, focusing on core functionality without excessive configuration or customization.
*   **Success Criteria:** 
    *   Ability to accurately identify issues based on user-provided queries in a configuration file.
    *   Successful integration with a local LLM server (LM Studio).
    *   Automated re-scanning triggered by Git changes.

---

## 2. Functional Requirements

### 2.1 Git Integration and Change Detection
*   **Default Behavior:** The scanner must monitor the target directory and focus only on **uncommitted changes** within the current Git branch.
*   **Specific Commit Analysis:** Users must have the option to scan against a specific **Git commit hash** by passing it as a command-line argument to the application.
*   **Monitoring Loop:** The application will run in a "render loop." If changes are detected, the queries are restarted; if no changes occur, the application will **wait and periodically check** for new updates.

### 2.2 Query and Analysis Engine
*   **Configuration Input:** The scanner will take a **configuration file** containing multiple user-defined queries. 
*   **Sequential Processing:** Queries must be executed **one by one** against the identified code changes.
*   **AI Interaction:** Each query will be sent to the local AI model to find issues specified by the user (e.g., optimization ideas, architecture checks).

### 2.3 Output and Reporting
*   **Log Generation:** The system must produce a **text log file** as its primary output.
*   **Detailed Findings:** For every issue found, the log must specify the **exact file**, the **specific line number**, the nature of the issue, and a **suggested implementation fix**.
*   **System Verbosity:** The output should include system information and **verbose logging** to capture all issues and runtime data for debugging purposes.

---

## 3. Technical Requirements

### 3.1 Technology Stack
*   **Language:** The application must be written in **Python**.
*   **Dependency Management:** The project is required to use either **Poetry or UV** for managing packages and environments.
*   **AI Backend:** The system requires a running and configured **LM Studio server** to host the local AI model.

### 3.2 System Architecture and Logic
*   **Agnostic Design:** The scanner logic must remain **independent of the programming language** found in the target source directory.
*   **Runtime Monitoring:** It is critical to include robust logging to identify all possible issues during the application’s runtime.
*   **Input Handling:** The application must accept a configuration file for queries and support optional Git commit hashes as input arguments.

### 3.3 Execution Workflow
1.  Initialize by reading the **config file** and checking the **Git status**.
2.  If uncommitted changes (or changes since a specified hash) exist, trigger the **LLM query loop**.
3.  Communicate with the **LM Studio local server** via its API to process queries.
4.  Write results and system logs to the designated **output text file**.
5.  Enter a wait state, polling for changes at set intervals.

### 3.4 Default Configuration Checks
The following checks must be included in the default configuration and applied to every scan:

*   **Autonomous Iteration:** Check that iteration continues automatically until the final result, without requiring user prompts to proceed.
*   **Compile-Time Programming:** Check that `constexpr` and compile-time programming techniques are applied where appropriate.
*   **Stack Allocation Preference:** Check that stack allocation is preferred over heap allocation whenever possible.
*   **QStringView for Literals:** Check that string literals are handled through `QStringView` variables.
*   **Named QStringView Constants:** Check that string literals used multiple times are stored in named `QStringView` constants instead of being repeated.
*   **Error Fixing and Simplification:** Check that any detected errors are fixed and that code simplifications are applied where possible.
*   **Iterative Operations:** Check that all operations are performed iteratively without waiting for external prompts, and that necessary edits are made directly to files.
*   **Meaningful Comments:** Check that comments provide meaningful context or rationale and avoid restating obvious code behavior.
*   **Implementation in .cpp Files:** Check that functions are implemented in `.cpp` files rather than `.h` files.

***

**Analogy for Understanding:** 
Think of this code scanner as a **diligent proofreader** sitting over a writer's shoulder. Instead of waiting for the writer to finish the whole book, the proofreader only looks at the sentences the writer just typed (the uncommitted changes). The proofreader uses a specialized guidebook (the config file) to check for specific mistakes, and if they find one, they point to the exact line and offer a sticky note with a suggested correction—all while keeping their notes in a private journal (the log file).