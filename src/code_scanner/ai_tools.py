"""AI tools for context expansion - allows LLM to request additional codebase information."""

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .ctags_index import CtagsIndex
from .utils import read_file_content, is_binary_file, estimate_tokens

logger = logging.getLogger(__name__)

# Maximum tokens for a single chunk when splitting large files
DEFAULT_CHUNK_SIZE_TOKENS = 4000


@dataclass
class ToolResult:
    """Result from a tool execution."""

    success: bool
    data: Any
    error: Optional[str] = None
    warning: Optional[str] = None  # For partial content warnings


# Tool schema definitions for LLM function calling
AI_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "**Use to verify assumptions.** Search repository for text patterns. MANDATORY before reporting: 'unused code' (search for usages), 'missing import' (check if imported elsewhere), 'dead code' (verify no callers). Returns file paths, line numbers, and matching lines. Supports literal text and regex.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patterns": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                        "description": "Text pattern(s) to search for. Can be a single string or an array of strings. Each pattern is searched as a whole word by default.",
                    },
                    "is_regex": {
                        "type": "boolean",
                        "description": "If true, treat patterns as regular expressions. Default is false (literal text search). Example regex: '(class|def)\\s+MyClass' to find class or function definitions.",
                    },
                    "match_whole_word": {
                        "type": "boolean",
                        "description": "If true (default), match only whole words. If false, match substring anywhere. Ignored when is_regex is true.",
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "If true, search is case-sensitive. Default is false (case-insensitive).",
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "Optional glob pattern to filter files (e.g., '*.py', '*.cpp'). If omitted, searches all text files.",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Skip this many results (for pagination). Use the 'next_offset' value from previous response to get more results.",
                        "minimum": 0,
                    },
                },
                "required": ["patterns"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the content of any file in the repository. For large files, content may be returned in chunks. If partial content is returned, use this tool again with start_line parameter to get subsequent chunks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative path to the file from repository root (e.g., 'src/module/file.ext')",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Optional: Line number to start reading from (1-based). Use this to request subsequent chunks of large files.",
                        "minimum": 1,
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Optional: Line number to stop reading at (1-based, inclusive). If omitted, reads to end or until chunk limit.",
                        "minimum": 1,
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List all files and subdirectories in a specific directory. Returns file paths with line counts (for text files). Results are paginated - use 'offset' to get more results if 'has_more' is true.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory_path": {
                        "type": "string",
                        "description": "Relative path to the directory from repository root (e.g., 'src/utils' or '.' for root)",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "If true, list all files recursively in subdirectories. Default is false (only direct children).",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Skip this many items (for pagination). Use the 'next_offset' value from previous response to get more results.",
                        "minimum": 0,
                    },
                },
                "required": ["directory_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_diff",
            "description": "Get the diff (changes) for a specific file relative to HEAD. Returns only the changed lines in unified diff format, which is much more token-efficient than reading the entire file. Useful for understanding what was modified.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative path to the file from repository root. Use EXACT path as shown in 'Files to analyze' (e.g., 'src/module/file.py').",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "Number of unchanged context lines to include around each change. Default is 3.",
                        "minimum": 0,
                        "maximum": 10,
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_summary",
            "description": "Get a structural summary of a file without reading all content. Returns classes, functions, imports - much more token-efficient than read_file when you only need to understand file structure. Language-agnostic: detects common patterns like 'class', 'def', 'function', 'import', 'require', '#include', etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative path to the file from repository root. Use EXACT path as shown in 'Files to analyze' section (e.g., 'src/module/file.py').",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "symbol_exists",
            "description": "**MANDATORY before reporting 'undefined symbol' issues.** Quick O(1) lookup to check if a symbol (function, class, variable) is defined anywhere in the repository. Returns definition location(s) if found. ALWAYS call this BEFORE reporting that a symbol is undefined, missing, or not found.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "The symbol name to search for (function name, class name, variable, etc.)",
                    },
                    "symbol_type": {
                        "type": "string",
                        "description": "Optional: filter by symbol type. Common types: 'function', 'class', 'method', 'variable', 'constant', 'type', 'interface'. If omitted, searches all types.",
                        "enum": ["function", "class", "method", "variable", "constant", "type", "interface", "any"],
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_definition",
            "description": "Go to where a symbol is defined (like IDE 'Go to Definition'). Returns exact file and line number. Use when you need to understand how a function/class is implemented, or to verify it exists before reporting issues.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "The symbol name to find definition for",
                    },
                    "kind": {
                        "type": "string",
                        "description": "Optional: filter by symbol kind (function, class, method, variable, etc.)",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_symbols",
            "description": "List all symbols (functions, classes, methods, etc.) defined in a file. Returns a structured view of the file's contents with classes, their methods, standalone functions, and variables.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative path to the file from repository root",
                    },
                    "kind": {
                        "type": "string",
                        "description": "Optional: filter by symbol kind (function, class, method, variable, etc.)",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_symbols",
            "description": "Find all symbols matching a pattern across the repository. Supports wildcards (*). Useful for finding all classes ending in 'Service', all functions starting with 'test_', etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Pattern to match symbol names. Use * as wildcard (e.g., '*Service', 'test_*', '*Handler*')",
                    },
                    "kind": {
                        "type": "string",
                        "description": "Optional: filter by symbol kind (function, class, method, etc.)",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_class_members",
            "description": "Get all members (methods, properties, fields) of a class. Returns a list of all symbols that belong to the specified class.",
            "parameters": {
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": "Name of the class to get members for",
                    },
                },
                "required": ["class_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_index_stats",
            "description": "Get statistics about the ctags index - total symbols, files indexed, breakdown by kind and language. Useful for understanding codebase structure.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


class AIToolExecutor:
    """Executes AI tool requests for context expansion.
    
    Uses Universal Ctags for efficient symbol indexing and navigation.
    """

    def __init__(self, target_directory: Path, context_limit: int, ctags_index: CtagsIndex):
        """Initialize the tool executor.

        Args:
            target_directory: Root directory of the repository.
            context_limit: Maximum context in tokens for chunk sizing.
            ctags_index: Pre-initialized CtagsIndex for symbol lookups.
        """
        self.target_directory = target_directory
        self.context_limit = context_limit
        self.ctags_index = ctags_index
        # Reserve some tokens for the tool response structure
        self.chunk_size = min(DEFAULT_CHUNK_SIZE_TOKENS, context_limit // 4)

    def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool and return the result.

        Args:
            tool_name: Name of the tool to execute.
            arguments: Tool arguments from LLM.

        Returns:
            ToolResult with execution outcome.
        """
        logger.info(f"Executing tool: {tool_name} with args: {arguments}")

        try:
            if tool_name == "search_text":
                return self._search_text(
                    patterns=arguments.get("patterns", ""),
                    is_regex=arguments.get("is_regex", False),
                    match_whole_word=arguments.get("match_whole_word", True),
                    case_sensitive=arguments.get("case_sensitive", False),
                    file_pattern=arguments.get("file_pattern"),
                    offset=arguments.get("offset", 0),
                )
            elif tool_name == "read_file":
                return self._read_file(
                    file_path=arguments.get("file_path", ""),
                    start_line=arguments.get("start_line"),
                    end_line=arguments.get("end_line"),
                )
            elif tool_name == "list_directory":
                return self._list_directory(
                    directory_path=arguments.get("directory_path", "."),
                    recursive=arguments.get("recursive", False),
                    offset=arguments.get("offset", 0),
                )
            elif tool_name == "get_file_diff":
                return self._get_file_diff(
                    file_path=arguments.get("file_path", ""),
                    context_lines=arguments.get("context_lines", 3),
                )
            elif tool_name == "get_file_summary":
                return self._get_file_summary(
                    file_path=arguments.get("file_path", ""),
                )
            elif tool_name == "symbol_exists":
                return self._symbol_exists(
                    symbol=arguments.get("symbol", ""),
                    symbol_type=arguments.get("symbol_type", "any"),
                )
            elif tool_name == "find_definition":
                return self._find_definition(
                    symbol=arguments.get("symbol", ""),
                    kind=arguments.get("kind"),
                )
            elif tool_name == "list_symbols":
                return self._list_symbols(
                    file_path=arguments.get("file_path", ""),
                    kind=arguments.get("kind"),
                )
            elif tool_name == "find_symbols":
                return self._find_symbols(
                    pattern=arguments.get("pattern", ""),
                    kind=arguments.get("kind"),
                )
            elif tool_name == "get_class_members":
                return self._get_class_members(
                    class_name=arguments.get("class_name", ""),
                )
            elif tool_name == "get_index_stats":
                return self._get_index_stats()
            else:
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Unknown tool: {tool_name}",
                )

        except Exception as e:
            logger.error(f"Tool execution error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                data=None,
                error=f"Tool execution failed: {str(e)}",
            )

    def _is_definition_line(self, line: str, symbol: str) -> bool:
        """Check if a line appears to be a definition of the given symbol.
        
        Detects common definition patterns across languages.
        """
        line_stripped = line.strip()
        
        # Common definition patterns by language
        definition_patterns = [
            # Python: def func_name, class ClassName
            rf"^\s*(def|class|async\s+def)\s+{re.escape(symbol)}\b",
            # JavaScript/TypeScript: function funcName, const/let/var name =, class Name
            rf"^\s*(function|const|let|var|class|export\s+(default\s+)?(function|class|const|let|var)?)\s+{re.escape(symbol)}\b",
            # C/C++/Java/C#: type name(, type name =
            rf"^\s*(\w+\s+)+{re.escape(symbol)}\s*[\(=;]",
            # Go: func name, type name struct/interface
            rf"^\s*(func|type)\s+(\([^)]+\)\s+)?{re.escape(symbol)}\b",
            # Rust: fn name, struct name, enum name, trait name
            rf"^\s*(pub\s+)?(fn|struct|enum|trait|type|const|static|impl)\s+{re.escape(symbol)}\b",
        ]
        
        for pattern in definition_patterns:
            if re.search(pattern, line_stripped, re.IGNORECASE):
                return True
        
        return False

    def _search_text(
        self,
        patterns: str | list[str],
        is_regex: bool = False,
        match_whole_word: bool = True,
        case_sensitive: bool = False,
        file_pattern: Optional[str] = None,
        offset: int = 0,
    ) -> ToolResult:
        """Search for text patterns in the repository.

        Args:
            patterns: Single pattern or list of patterns to search for.
            is_regex: If True, treat patterns as regular expressions.
            match_whole_word: If True, match whole words only (ignored when is_regex=True).
            case_sensitive: If True, search is case-sensitive.
            file_pattern: Optional glob pattern to filter files.
            offset: Number of results to skip (for pagination).

        Returns:
            ToolResult with list of matches grouped by pattern.
        """
        # Normalize patterns to list
        if isinstance(patterns, str):
            pattern_list = [patterns]
        else:
            pattern_list = list(patterns)

        if not pattern_list or all(not p for p in pattern_list):
            return ToolResult(
                success=False,
                data=None,
                error="At least one non-empty pattern is required",
            )

        page_size = 50  # Results per page
        logger.info(f"Searching for {len(pattern_list)} pattern(s), is_regex={is_regex}, offset: {offset}")

        # Build regex patterns
        regex_flags = 0 if case_sensitive else re.IGNORECASE
        compiled_patterns = []
        for pattern in pattern_list:
            if not pattern:
                continue
            try:
                if is_regex:
                    # Use pattern as-is when is_regex=True
                    regex = pattern
                else:
                    # Escape special characters for literal search
                    escaped = re.escape(pattern)
                    if match_whole_word:
                        regex = rf"\b{escaped}\b"
                    else:
                        regex = escaped
                compiled_patterns.append((pattern, re.compile(regex, regex_flags)))
            except re.error as e:
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Invalid regex pattern '{pattern}': {e}",
                )

        all_matches = []

        # Search all non-binary files in the repository
        for file_path in self.target_directory.rglob("*"):
            if not file_path.is_file():
                continue

            # Skip binary files
            if is_binary_file(file_path):
                continue

            relative_path = file_path.relative_to(self.target_directory)

            # Skip hidden files and common build/cache directories
            if any(part.startswith(".") for part in relative_path.parts):
                continue
            if any(
                part in {"node_modules", "__pycache__", "build", "dist", "target", ".git"}
                for part in relative_path.parts
            ):
                continue

            # Apply file pattern filter if specified
            if file_pattern:
                from fnmatch import fnmatch
                if not fnmatch(relative_path.name, file_pattern) and not fnmatch(str(relative_path), file_pattern):
                    continue

            try:
                content = read_file_content(file_path)
                if content is None:
                    continue

                lines = content.split("\n")
                for line_num, line in enumerate(lines, start=1):
                    for original_pattern, compiled in compiled_patterns:
                        if compiled.search(line):
                            all_matches.append({
                                "pattern": original_pattern,
                                "file": str(relative_path),
                                "line": line_num,
                                "code": line.strip(),
                                # Mark as definition if line looks like a definition
                                "is_definition": self._is_definition_line(line, original_pattern),
                            })

            except Exception as e:
                logger.debug(f"Error searching {relative_path}: {e}")
                continue

        # Deduplicate matches (same file+line+pattern)
        seen = set()
        unique_matches = []
        for match in all_matches:
            key = (match["file"], match["line"], match["pattern"])
            if key not in seen:
                seen.add(key)
                unique_matches.append(match)

        # Sort: definitions first, then by file path and line number
        unique_matches.sort(key=lambda m: (
            0 if m.get("is_definition") else 1,  # Definitions first
            m["file"],
            m["line"]
        ))

        total_matches = len(unique_matches)

        # Apply pagination
        paginated_matches = unique_matches[offset:offset + page_size]
        has_more = (offset + page_size) < total_matches
        next_offset = offset + page_size if has_more else None

        warning = None
        if has_more:
            warning = (
                f"⚠️ PARTIAL RESULTS: Showing {len(paginated_matches)} of {total_matches} total matches "
                f"(offset {offset}). To get more results, call search_text again with offset={next_offset}"
            )

        # Group results by pattern for easier reading
        results_by_pattern = {}
        for match in paginated_matches:
            pattern = match["pattern"]
            if pattern not in results_by_pattern:
                results_by_pattern[pattern] = []
            results_by_pattern[pattern].append({
                "file": match["file"],
                "line": match["line"],
                "code": match["code"],
                "is_definition": match.get("is_definition", False),
            })

        # Count total matches per pattern (from all results, not just paginated)
        pattern_counts = {}
        for match in all_matches:
            pattern = match["pattern"]
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

        logger.info(f"Found {total_matches} total matches for {len(pattern_list)} pattern(s)")

        result_data = {
            "patterns_searched": pattern_list,
            "total_matches": total_matches,
            "returned_count": len(paginated_matches),
            "offset": offset,
            "has_more": has_more,
            "matches_by_pattern": results_by_pattern,
            "pattern_match_counts": pattern_counts,
        }

        if next_offset is not None:
            result_data["next_offset"] = next_offset

        return ToolResult(
            success=True,
            data=result_data,
            warning=warning,
        )

    def _read_file(
        self,
        file_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> ToolResult:
        """Read file content with optional line range.

        Args:
            file_path: Relative path to the file.
            start_line: Optional starting line number (1-based).
            end_line: Optional ending line number (1-based, inclusive).

        Returns:
            ToolResult with file content.
        """
        if not file_path:
            return ToolResult(
                success=False,
                data=None,
                error="file_path is required",
            )

        # Resolve file path
        full_path = (self.target_directory / file_path).resolve()

        # Security check: ensure path is within target directory
        try:
            full_path.relative_to(self.target_directory)
        except ValueError:
            return ToolResult(
                success=False,
                data=None,
                error=f"Access denied: path '{file_path}' is outside repository",
            )

        if not full_path.exists():
            return ToolResult(
                success=False,
                data=None,
                error=f"File not found: {file_path}",
            )

        if not full_path.is_file():
            return ToolResult(
                success=False,
                data=None,
                error=f"Not a file: {file_path}",
            )

        if is_binary_file(full_path):
            return ToolResult(
                success=False,
                data=None,
                error=f"Cannot read binary file: {file_path}",
            )

        try:
            content = read_file_content(full_path)
            if content is None:
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Failed to read file: {file_path}",
                )

            lines = content.split("\n")
            total_lines = len(lines)

            # Determine line range
            start_idx = (start_line - 1) if start_line else 0
            end_idx = end_line if end_line else total_lines

            # Validate line numbers
            if start_idx < 0 or start_idx >= total_lines:
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Invalid start_line: {start_line} (file has {total_lines} lines)",
                )

            if end_idx < start_idx or end_idx > total_lines:
                end_idx = total_lines

            # Extract requested lines
            selected_lines = lines[start_idx:end_idx]
            chunk_content = "\n".join(selected_lines)

            # Check if content exceeds chunk size
            tokens = estimate_tokens(chunk_content)
            warning = None

            if tokens > self.chunk_size:
                # Calculate how many lines we can fit
                avg_tokens_per_line = tokens / len(selected_lines) if selected_lines else 1
                max_lines = int(self.chunk_size / avg_tokens_per_line)
                max_lines = max(10, max_lines)  # At least 10 lines

                # Truncate to fit chunk size
                selected_lines = selected_lines[:max_lines]
                chunk_content = "\n".join(selected_lines)
                actual_end_line = start_idx + len(selected_lines)

                warning = (
                    f"⚠️ PARTIAL CONTENT: This file is too large to return in full. "
                    f"Showing lines {start_idx + 1}-{actual_end_line} of {total_lines}. "
                    f"To read more, call read_file again with start_line={actual_end_line + 1}."
                )

                logger.info(f"Truncated file {file_path} to fit chunk size")

            # Check if we didn't return the full file (even after potential truncation)
            is_partial = start_line is not None or end_idx < total_lines or warning is not None

            # Add helpful hint based on how much of the file was returned
            lines_returned = len(selected_lines)
            coverage_pct = (lines_returned / total_lines * 100) if total_lines > 0 else 100

            hint = None
            if not is_partial:
                hint = f"This is the COMPLETE file ({total_lines} lines). No need to read it again."
            elif coverage_pct >= 80:
                hint = f"You now have {coverage_pct:.0f}% of this file. Consider proceeding with analysis."

            # Calculate pagination metadata
            actual_end_line = start_idx + len(selected_lines)
            has_more = actual_end_line < total_lines
            next_start_line = actual_end_line + 1 if has_more else None

            result_data = {
                "file_path": file_path,
                "content": chunk_content,
                "start_line": start_idx + 1,
                "end_line": actual_end_line,
                "total_lines": total_lines,
                "lines_returned": len(selected_lines),
                "is_partial": is_partial,
                "has_more": has_more,
            }

            if next_start_line is not None:
                result_data["next_start_line"] = next_start_line
            
            if hint:
                result_data["hint"] = hint

            return ToolResult(
                success=True,
                data=result_data,
                warning=warning,
            )

        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                data=None,
                error=f"Error reading file: {str(e)}",
            )

    def _get_file_info(self, full_path: Path, relative_path: Path) -> dict:
        """Get file information including line count for non-binary files.

        Args:
            full_path: Absolute path to the file.
            relative_path: Relative path from repository root.

        Returns:
            Dict with file path and optional line count.
        """
        info = {"path": str(relative_path)}

        # Try to get line count for text files
        if not is_binary_file(full_path):
            try:
                content = read_file_content(full_path)
                if content is not None:
                    info["lines"] = len(content.split("\n"))
            except Exception:
                pass  # Skip line count if we can't read the file

        return info

    def _list_directory(self, directory_path: str, recursive: bool = False, offset: int = 0) -> ToolResult:
        """List contents of a directory.

        Args:
            directory_path: Relative path to the directory.
            recursive: Whether to list recursively.
            offset: Number of items to skip (for pagination).

        Returns:
            ToolResult with directory listing.
        """
        if not directory_path:
            directory_path = "."

        page_size = 100  # Items per page

        # Resolve directory path
        full_path = (self.target_directory / directory_path).resolve()

        # Security check: ensure path is within target directory
        try:
            full_path.relative_to(self.target_directory)
        except ValueError:
            return ToolResult(
                success=False,
                data=None,
                error=f"Access denied: path '{directory_path}' is outside repository",
            )

        if not full_path.exists():
            return ToolResult(
                success=False,
                data=None,
                error=f"Directory not found: {directory_path}",
            )

        if not full_path.is_dir():
            return ToolResult(
                success=False,
                data=None,
                error=f"Not a directory: {directory_path}",
            )

        try:
            all_files = []
            all_directories = []

            if recursive:
                # Recursive listing with relative paths
                for item in full_path.rglob("*"):
                    # Skip hidden and common build directories
                    relative = item.relative_to(self.target_directory)
                    if any(part.startswith(".") for part in relative.parts):
                        continue
                    if any(
                        part in {"node_modules", "__pycache__", "build", "dist", "target"}
                        for part in relative.parts
                    ):
                        continue

                    if item.is_file():
                        all_files.append(self._get_file_info(item, relative))
                    elif item.is_dir():
                        all_directories.append(str(relative))
            else:
                # Non-recursive listing
                for item in full_path.iterdir():
                    # Skip hidden files
                    if item.name.startswith("."):
                        continue

                    relative = item.relative_to(self.target_directory)
                    if item.is_file():
                        all_files.append(self._get_file_info(item, relative))
                    elif item.is_dir():
                        all_directories.append(str(relative))

            # Sort for consistent ordering
            all_files.sort(key=lambda f: f["path"] if isinstance(f, dict) else f)
            all_directories.sort()

            # Combine and paginate
            # Directories first, then files
            all_items = [("dir", d) for d in all_directories] + [("file", f) for f in all_files]
            total_items = len(all_items)
            
            # Apply pagination
            paginated_items = all_items[offset:offset + page_size]
            has_more = (offset + page_size) < total_items
            next_offset = offset + page_size if has_more else None

            # Separate back into directories and files
            directories = [item[1] for item in paginated_items if item[0] == "dir"]
            files = [item[1] for item in paginated_items if item[0] == "file"]

            warning = None
            if has_more:
                warning = (
                    f"⚠️ PARTIAL LISTING: Showing {len(paginated_items)} of {total_items} total items "
                    f"(offset {offset}). To get more results, call list_directory again with offset={next_offset}"
                )

            result_data = {
                "directory_path": directory_path,
                "directories": directories,
                "files": files,
                "total_directories": len(all_directories),
                "total_files": len(all_files),
                "total_items": total_items,
                "returned_count": len(paginated_items),
                "offset": offset,
                "has_more": has_more,
                "recursive": recursive,
            }
            
            if next_offset is not None:
                result_data["next_offset"] = next_offset

            return ToolResult(
                success=True,
                data=result_data,
                warning=warning,
            )

        except Exception as e:
            logger.error(f"Error listing directory {directory_path}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                data=None,
                error=f"Error listing directory: {str(e)}",
            )

    def _get_file_diff(self, file_path: str, context_lines: int = 3) -> ToolResult:
        """Get git diff for a specific file.

        Args:
            file_path: Relative path to the file.
            context_lines: Number of context lines around changes.

        Returns:
            ToolResult with diff output.
        """
        if not file_path:
            return ToolResult(
                success=False,
                data=None,
                error="file_path is required",
            )

        # Resolve file path
        full_path = (self.target_directory / file_path).resolve()

        # Security check: ensure path is within target directory
        try:
            full_path.relative_to(self.target_directory)
        except ValueError:
            return ToolResult(
                success=False,
                data=None,
                error=f"Access denied: path '{file_path}' is outside repository",
            )

        try:
            # Run git diff command
            result = subprocess.run(
                ["git", "diff", f"-U{context_lines}", "HEAD", "--", file_path],
                cwd=self.target_directory,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0 and result.stderr:
                # Check if it's just "not a git repository"
                if "not a git repository" in result.stderr.lower():
                    return ToolResult(
                        success=False,
                        data=None,
                        error="Not a git repository",
                    )
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Git diff failed: {result.stderr.strip()}",
                )

            diff_output = result.stdout.strip()

            if not diff_output:
                return ToolResult(
                    success=True,
                    data={
                        "file_path": file_path,
                        "diff": None,
                        "has_changes": False,
                        "message": "No changes in this file relative to HEAD",
                    },
                )

            # Parse diff statistics
            lines_added = diff_output.count("\n+") - diff_output.count("\n+++")
            lines_removed = diff_output.count("\n-") - diff_output.count("\n---")

            return ToolResult(
                success=True,
                data={
                    "file_path": file_path,
                    "diff": diff_output,
                    "has_changes": True,
                    "lines_added": max(0, lines_added),
                    "lines_removed": max(0, lines_removed),
                    "context_lines": context_lines,
                },
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                data=None,
                error="Git diff command timed out",
            )
        except Exception as e:
            logger.error(f"Error getting diff for {file_path}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                data=None,
                error=f"Error getting diff: {str(e)}",
            )

    def _get_file_summary(self, file_path: str) -> ToolResult:
        """Get structural summary of a file using ctags index.

        Args:
            file_path: Relative path to the file.

        Returns:
            ToolResult with file structure summary.
        """
        if not file_path:
            return ToolResult(
                success=False,
                data=None,
                error="file_path is required",
            )

        # Resolve file path
        full_path = (self.target_directory / file_path).resolve()

        # Security check: ensure path is within target directory
        try:
            full_path.relative_to(self.target_directory)
        except ValueError:
            return ToolResult(
                success=False,
                data=None,
                error=f"Access denied: path '{file_path}' is outside repository",
            )

        if not full_path.exists():
            return ToolResult(
                success=False,
                data=None,
                error=f"File not found: {file_path}",
            )

        if not full_path.is_file():
            return ToolResult(
                success=False,
                data=None,
                error=f"Not a file: {file_path}",
            )

        try:
            # Use ctags index for file structure
            structure = self.ctags_index.get_file_structure(file_path)
            
            # Get total lines from file
            content = read_file_content(full_path)
            total_lines = len(content.split("\n")) if content else 0

            return ToolResult(
                success=True,
                data={
                    "file_path": file_path,
                    "total_lines": total_lines,
                    "classes": structure["classes"],
                    "functions": structure["functions"],
                    "variables": structure["variables"],
                    "imports": structure["imports"],
                    "other": structure["other"],
                    "summary": {
                        "class_count": len(structure["classes"]),
                        "function_count": len(structure["functions"]),
                        "variable_count": len(structure["variables"]),
                        "import_count": len(structure["imports"]),
                    },
                },
            )

        except Exception as e:
            logger.error(f"Error summarizing file {file_path}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                data=None,
                error=f"Error summarizing file: {str(e)}",
            )

    def _symbol_exists(self, symbol: str, symbol_type: str = "any") -> ToolResult:
        """Quick check if a symbol exists using ctags index.

        Args:
            symbol: Symbol name to search for.
            symbol_type: Type filter (function, class, method, variable, etc.).

        Returns:
            ToolResult with existence info and location.
        """
        if not symbol:
            return ToolResult(
                success=False,
                data=None,
                error="symbol is required",
            )

        try:
            # Use ctags index for O(1) lookup
            kind = symbol_type if symbol_type != "any" else None
            symbols = self.ctags_index.find_symbol(symbol, kind=kind)

            if symbols:
                locations = [
                    {
                        "file": s.file_path.lstrip("./"),
                        "line": s.line,
                        "kind": s.kind,
                        "code": s.pattern.strip("^$/") if s.pattern else "",
                        "signature": s.signature,
                        "scope": s.scope,
                    }
                    for s in symbols[:10]  # Limit results
                ]

                return ToolResult(
                    success=True,
                    data={
                        "symbol": symbol,
                        "symbol_type": symbol_type,
                        "exists": True,
                        "locations": locations,
                        "location_count": len(symbols),
                        "note": "Symbol found - do NOT report as undefined",
                    },
                )
            else:
                return ToolResult(
                    success=True,
                    data={
                        "symbol": symbol,
                        "symbol_type": symbol_type,
                        "exists": False,
                        "locations": [],
                        "location_count": 0,
                    },
                )

        except Exception as e:
            logger.error(f"Error checking symbol {symbol}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                data=None,
                error=f"Error checking symbol: {str(e)}",
            )

    def _find_definition(self, symbol: str, kind: Optional[str] = None) -> ToolResult:
        """Find where a symbol is defined (Go to Definition).

        Args:
            symbol: Symbol name to find.
            kind: Optional kind filter.

        Returns:
            ToolResult with definition locations.
        """
        if not symbol:
            return ToolResult(
                success=False,
                data=None,
                error="symbol is required",
            )

        try:
            symbols = self.ctags_index.find_definitions(symbol, kind=kind)

            if not symbols:
                return ToolResult(
                    success=True,
                    data={
                        "symbol": symbol,
                        "found": False,
                        "definitions": [],
                        "message": f"No definition found for '{symbol}'",
                    },
                )

            definitions = []
            for s in symbols[:20]:  # Limit results
                definitions.append({
                    "file": s.file_path.lstrip("./"),
                    "line": s.line,
                    "kind": s.kind,
                    "signature": s.signature,
                    "scope": s.scope,
                    "access": s.access,
                    "language": s.language,
                })

            return ToolResult(
                success=True,
                data={
                    "symbol": symbol,
                    "found": True,
                    "definition_count": len(symbols),
                    "definitions": definitions,
                },
            )

        except Exception as e:
            logger.error(f"Error finding definition for {symbol}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                data=None,
                error=f"Error finding definition: {str(e)}",
            )

    def _list_symbols(self, file_path: str, kind: Optional[str] = None) -> ToolResult:
        """List all symbols defined in a file.

        Args:
            file_path: Relative path to the file.
            kind: Optional kind filter.

        Returns:
            ToolResult with list of symbols.
        """
        if not file_path:
            return ToolResult(
                success=False,
                data=None,
                error="file_path is required",
            )

        try:
            symbols = self.ctags_index.get_symbols_in_file(file_path, kind=kind)

            if not symbols:
                return ToolResult(
                    success=True,
                    data={
                        "file_path": file_path,
                        "symbol_count": 0,
                        "symbols": [],
                        "message": f"No symbols found in '{file_path}'",
                    },
                )

            symbol_list = []
            for s in symbols:
                symbol_list.append({
                    "name": s.name,
                    "line": s.line,
                    "kind": s.kind,
                    "scope": s.scope,
                    "signature": s.signature,
                    "access": s.access,
                })

            return ToolResult(
                success=True,
                data={
                    "file_path": file_path,
                    "symbol_count": len(symbol_list),
                    "symbols": symbol_list,
                },
            )

        except Exception as e:
            logger.error(f"Error listing symbols in {file_path}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                data=None,
                error=f"Error listing symbols: {str(e)}",
            )

    def _find_symbols(self, pattern: str, kind: Optional[str] = None) -> ToolResult:
        """Find symbols matching a pattern.

        Args:
            pattern: Glob pattern (e.g., "*Service", "test_*").
            kind: Optional kind filter.

        Returns:
            ToolResult with matching symbols.
        """
        if not pattern:
            return ToolResult(
                success=False,
                data=None,
                error="pattern is required",
            )

        try:
            symbols = self.ctags_index.find_symbols_by_pattern(pattern, kind=kind)

            if not symbols:
                return ToolResult(
                    success=True,
                    data={
                        "pattern": pattern,
                        "match_count": 0,
                        "matches": [],
                        "message": f"No symbols matching '{pattern}'",
                    },
                )

            matches = []
            for s in symbols[:50]:  # Limit results
                matches.append({
                    "name": s.name,
                    "file": s.file_path.lstrip("./"),
                    "line": s.line,
                    "kind": s.kind,
                    "scope": s.scope,
                })

            return ToolResult(
                success=True,
                data={
                    "pattern": pattern,
                    "match_count": len(symbols),
                    "returned_count": len(matches),
                    "matches": matches,
                    "has_more": len(symbols) > 50,
                },
            )

        except Exception as e:
            logger.error(f"Error finding symbols matching {pattern}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                data=None,
                error=f"Error finding symbols: {str(e)}",
            )

    def _get_class_members(self, class_name: str) -> ToolResult:
        """Get all members of a class.

        Args:
            class_name: Name of the class.

        Returns:
            ToolResult with class members.
        """
        if not class_name:
            return ToolResult(
                success=False,
                data=None,
                error="class_name is required",
            )

        try:
            # First, find the class definition(s)
            class_symbols = self.ctags_index.find_symbol(class_name, kind="class")
            
            # Get all members with this class as scope
            all_members = self.ctags_index.get_class_members(class_name)

            if not class_symbols and not all_members:
                return ToolResult(
                    success=True,
                    data={
                        "class_name": class_name,
                        "found": False,
                        "members": [],
                        "message": f"Class '{class_name}' not found",
                    },
                )

            # If multiple class definitions exist, filter members by the first class's file
            # This prevents mixing members from different classes with the same name
            if class_symbols:
                target_file = class_symbols[0].file_path
                members = [m for m in all_members if m.file_path == target_file]
            else:
                members = all_members

            # Organize members by kind
            methods = []
            properties = []
            other = []

            for m in members:
                member_info = {
                    "name": m.name,
                    "line": m.line,
                    "kind": m.kind,
                    "file": m.file_path.lstrip("./"),
                    "signature": m.signature,
                    "access": m.access,
                }

                if m.kind in ("method", "function", "f", "m"):
                    methods.append(member_info)
                elif m.kind in ("property", "member", "field", "p", "M", "F"):
                    properties.append(member_info)
                else:
                    other.append(member_info)

            # Get class location
            class_info = None
            if class_symbols:
                c = class_symbols[0]
                class_info = {
                    "file": c.file_path.lstrip("./"),
                    "line": c.line,
                    "kind": c.kind,
                }

            return ToolResult(
                success=True,
                data={
                    "class_name": class_name,
                    "found": True,
                    "class_definition": class_info,
                    "member_count": len(members),
                    "methods": methods,
                    "properties": properties,
                    "other": other,
                },
            )

        except Exception as e:
            logger.error(f"Error getting members for {class_name}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                data=None,
                error=f"Error getting class members: {str(e)}",
            )

    def _get_index_stats(self) -> ToolResult:
        """Get statistics about the ctags index.

        Returns:
            ToolResult with index statistics.
        """
        try:
            stats = self.ctags_index.get_stats()

            return ToolResult(
                success=True,
                data=stats,
            )

        except Exception as e:
            logger.error(f"Error getting index stats: {e}", exc_info=True)
            return ToolResult(
                success=False,
                data=None,
                error=f"Error getting index stats: {str(e)}",
            )