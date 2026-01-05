"""AI tools for context expansion - allows LLM to request additional codebase information."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

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
            "description": "Search the entire repository for text patterns. Can search for a single string or multiple strings at once. Returns file paths, line numbers, and matching lines. Useful for finding where code entities are defined/used, verifying imports, or finding any text pattern. Results are paginated - use 'offset' to get more results if 'has_more' is true.",
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
                    "match_whole_word": {
                        "type": "boolean",
                        "description": "If true (default), match only whole words. If false, match substring anywhere.",
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
]


class AIToolExecutor:
    """Executes AI tool requests for context expansion."""

    def __init__(self, target_directory: Path, context_limit: int):
        """Initialize the tool executor.

        Args:
            target_directory: Root directory of the repository.
            context_limit: Maximum context in tokens for chunk sizing.
        """
        self.target_directory = target_directory
        self.context_limit = context_limit
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
                    match_whole_word=arguments.get("match_whole_word", True),
                    case_sensitive=arguments.get("case_sensitive", False),
                    file_pattern=arguments.get("file_pattern"),
                    offset=arguments.get("offset", 0),
                )
            elif tool_name == "find_code_usage":
                # Legacy support - redirect to search_text
                return self._search_text(
                    patterns=arguments.get("entity_name", ""),
                    match_whole_word=True,
                    case_sensitive=False,
                    file_pattern=None,
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

    def _search_text(
        self,
        patterns: str | list[str],
        match_whole_word: bool = True,
        case_sensitive: bool = False,
        file_pattern: Optional[str] = None,
        offset: int = 0,
    ) -> ToolResult:
        """Search for text patterns in the repository.

        Args:
            patterns: Single pattern or list of patterns to search for.
            match_whole_word: If True, match whole words only.
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
        logger.info(f"Searching for {len(pattern_list)} pattern(s), offset: {offset}")

        # Build regex patterns
        regex_flags = 0 if case_sensitive else re.IGNORECASE
        compiled_patterns = []
        for pattern in pattern_list:
            if not pattern:
                continue
            escaped = re.escape(pattern)
            if match_whole_word:
                regex = rf"\b{escaped}\b"
            else:
                regex = escaped
            compiled_patterns.append((pattern, re.compile(regex, regex_flags)))

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
                            })

            except Exception as e:
                logger.debug(f"Error searching {relative_path}: {e}")
                continue

        total_matches = len(all_matches)

        # Apply pagination
        paginated_matches = all_matches[offset:offset + page_size]
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
