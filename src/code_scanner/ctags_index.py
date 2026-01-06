"""Universal Ctags integration for efficient symbol indexing and navigation.

This module provides a wrapper around Universal Ctags for fast symbol lookups,
definition finding, and codebase navigation. Ctags generates an index of all
symbols (functions, classes, variables, etc.) which enables O(1) lookups
instead of O(n) file scanning.

Universal Ctags must be installed on the system. Install via:
- Ubuntu/Debian: sudo apt install universal-ctags
- macOS: brew install universal-ctags
- Windows: choco install universal-ctags
"""

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CtagsNotFoundError(Exception):
    """Raised when Universal Ctags is not installed or not found."""

    pass


class CtagsError(Exception):
    """Raised when ctags execution fails."""

    pass


@dataclass
class Symbol:
    """Represents a symbol (function, class, variable, etc.) from ctags output."""

    name: str
    file_path: str
    line: int
    kind: str  # function, class, variable, method, member, etc.
    scope: Optional[str] = None  # Parent scope (e.g., class name for methods)
    scope_kind: Optional[str] = None  # Kind of parent scope
    signature: Optional[str] = None  # Function signature if available
    access: Optional[str] = None  # public, private, protected
    language: Optional[str] = None  # Programming language
    pattern: Optional[str] = None  # Search pattern from ctags
    extras: dict = field(default_factory=dict)  # Additional fields

    @classmethod
    def from_ctags_json(cls, data: dict) -> "Symbol":
        """Create Symbol from ctags JSON output.

        Args:
            data: Dictionary from ctags --output-format=json

        Returns:
            Symbol instance
        """
        return cls(
            name=data.get("name", ""),
            file_path=data.get("path", ""),
            line=data.get("line", 0),
            kind=data.get("kind", "unknown"),
            scope=data.get("scope"),
            scope_kind=data.get("scopeKind"),
            signature=data.get("signature"),
            access=data.get("access"),
            language=data.get("language"),
            pattern=data.get("pattern"),
            extras={
                k: v
                for k, v in data.items()
                if k
                not in {
                    "name",
                    "path",
                    "line",
                    "kind",
                    "scope",
                    "scopeKind",
                    "signature",
                    "access",
                    "language",
                    "pattern",
                    "_type",
                }
            },
        )


# Map ctags kind letters to human-readable names (language-agnostic common ones)
KIND_MAP = {
    # Universal
    "f": "function",
    "c": "class",
    "m": "method",
    "v": "variable",
    "d": "macro",
    "t": "type",
    "s": "struct",
    "e": "enum",
    "g": "enum_value",
    "n": "namespace",
    "i": "interface",
    "p": "property",
    "M": "member",
    "F": "field",
    # Python specific
    "I": "import",
    # JavaScript/TypeScript
    "C": "constant",
    "G": "generator",
    # Go
    "w": "field",
    "a": "alias",
    # Rust
    "P": "impl",
}


class CtagsIndex:
    """Manages Universal Ctags index for a repository.

    Provides fast symbol lookups, definition finding, and codebase navigation
    by maintaining an in-memory index of symbols parsed from ctags output.

    Attributes:
        repo_path: Path to the repository root.
        symbols_by_name: Index mapping symbol names to list of Symbol objects.
        symbols_by_file: Index mapping file paths to list of Symbol objects.
    """

    def __init__(self, repo_path: Path):
        """Initialize the ctags index.

        Args:
            repo_path: Path to the repository root.

        Raises:
            CtagsNotFoundError: If Universal Ctags is not installed.
        """
        self.repo_path = repo_path.resolve()
        self._ctags_path: Optional[str] = None
        self._symbols: list[Symbol] = []
        self._symbols_by_name: dict[str, list[Symbol]] = {}
        self._symbols_by_file: dict[str, list[Symbol]] = {}
        self._is_indexed = False

        # Verify ctags is available
        self._verify_ctags()

    def _verify_ctags(self) -> None:
        """Verify Universal Ctags is installed and available.

        Raises:
            CtagsNotFoundError: If ctags is not found or is not Universal Ctags.
        """
        ctags_path = shutil.which("ctags")

        if ctags_path is None:
            raise CtagsNotFoundError(
                "\n"
                + "=" * 70
                + "\n"
                "UNIVERSAL CTAGS NOT FOUND\n"
                + "=" * 70
                + "\n\n"
                "Code Scanner requires Universal Ctags for symbol indexing.\n\n"
                "Please install Universal Ctags:\n\n"
                "  Ubuntu/Debian:\n"
                "    sudo apt install universal-ctags\n\n"
                "  macOS:\n"
                "    brew install universal-ctags\n\n"
                "  Windows:\n"
                "    choco install universal-ctags\n\n"
                "  From source:\n"
                "    https://github.com/universal-ctags/ctags\n\n"
                + "=" * 70
            )

        # Verify it's Universal Ctags (not Exuberant Ctags)
        try:
            result = subprocess.run(
                [ctags_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            version_output = result.stdout + result.stderr

            if "Universal Ctags" not in version_output:
                raise CtagsNotFoundError(
                    "\n"
                    + "=" * 70
                    + "\n"
                    "WRONG CTAGS VERSION\n"
                    + "=" * 70
                    + "\n\n"
                    "Code Scanner requires Universal Ctags, but found:\n"
                    f"{version_output.strip()}\n\n"
                    "Universal Ctags provides JSON output and better language support.\n\n"
                    "Please install Universal Ctags:\n\n"
                    "  Ubuntu/Debian:\n"
                    "    sudo apt remove exuberant-ctags\n"
                    "    sudo apt install universal-ctags\n\n"
                    "  macOS:\n"
                    "    brew install universal-ctags\n\n"
                    + "=" * 70
                )

            self._ctags_path = ctags_path
            logger.info(f"Found Universal Ctags: {ctags_path}")

        except subprocess.TimeoutExpired:
            raise CtagsNotFoundError(
                "Ctags version check timed out. Please verify ctags installation."
            )
        except subprocess.SubprocessError as e:
            raise CtagsNotFoundError(f"Failed to run ctags: {e}")

    def generate_index(self) -> int:
        """Generate the ctags index for the repository.

        Runs ctags to generate symbol data and parses it into memory.

        Returns:
            Number of symbols indexed.

        Raises:
            CtagsError: If ctags execution fails.
        """
        logger.info(f"Generating ctags index for: {self.repo_path}")

        # Build ctags command
        # --output-format=json: Machine-readable output
        # --fields=*: Include all available fields
        # --extras=*: Include extra tag entries
        # -R: Recursive
        # --exclude patterns for common non-source directories
        cmd = [
            self._ctags_path,
            "--output-format=json",
            "--fields=*",
            "--extras=*",
            "-R",
            "--exclude=.git",
            "--exclude=node_modules",
            "--exclude=__pycache__",
            "--exclude=.venv",
            "--exclude=venv",
            "--exclude=build",
            "--exclude=dist",
            "--exclude=target",
            "--exclude=*.min.js",
            "--exclude=*.min.css",
            "--exclude=*.map",
            "--exclude=coverage",
            "--exclude=htmlcov",
            "--exclude=.pytest_cache",
            "--exclude=.mypy_cache",
            "--exclude=.tox",
            "--exclude=*.egg-info",
            ".",
        ]

        try:
            result = subprocess.run(
                cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout for large repos
            )

            if result.returncode != 0:
                raise CtagsError(
                    f"Ctags failed with exit code {result.returncode}:\n"
                    f"stderr: {result.stderr}\n"
                    f"stdout: {result.stdout}"
                )

            # Parse JSON output (one JSON object per line)
            self._symbols = []
            self._symbols_by_name = {}
            self._symbols_by_file = {}

            for line in result.stdout.splitlines():
                if not line.strip():
                    continue

                try:
                    data = json.loads(line)
                    # Skip non-tag entries (ctags outputs some metadata)
                    if data.get("_type") != "tag":
                        continue

                    symbol = Symbol.from_ctags_json(data)
                    self._symbols.append(symbol)

                    # Index by name
                    name_lower = symbol.name.lower()
                    if name_lower not in self._symbols_by_name:
                        self._symbols_by_name[name_lower] = []
                    self._symbols_by_name[name_lower].append(symbol)

                    # Index by file
                    if symbol.file_path not in self._symbols_by_file:
                        self._symbols_by_file[symbol.file_path] = []
                    self._symbols_by_file[symbol.file_path].append(symbol)

                except json.JSONDecodeError:
                    # Skip malformed lines
                    continue

            self._is_indexed = True
            logger.info(f"Indexed {len(self._symbols)} symbols from {len(self._symbols_by_file)} files")
            return len(self._symbols)

        except subprocess.TimeoutExpired:
            raise CtagsError(
                "Ctags timed out after 5 minutes. "
                "The repository may be too large or contain problematic files."
            )
        except subprocess.SubprocessError as e:
            raise CtagsError(f"Failed to run ctags: {e}")

    @property
    def is_indexed(self) -> bool:
        """Check if the index has been generated."""
        return self._is_indexed

    @property
    def symbol_count(self) -> int:
        """Get total number of indexed symbols."""
        return len(self._symbols)

    @property
    def file_count(self) -> int:
        """Get number of files with symbols."""
        return len(self._symbols_by_file)

    def find_symbol(
        self,
        name: str,
        kind: Optional[str] = None,
        case_sensitive: bool = False,
    ) -> list[Symbol]:
        """Find symbols by name.

        Args:
            name: Symbol name to search for.
            kind: Optional filter by symbol kind (function, class, etc.).
            case_sensitive: If True, match case exactly.

        Returns:
            List of matching Symbol objects.
        """
        if not self._is_indexed:
            return []

        # Always look up by lowercase (that's how symbols are indexed)
        lookup_name = name.lower()
        symbols = self._symbols_by_name.get(lookup_name, [])

        # Case-sensitive filtering if needed
        if case_sensitive:
            symbols = [s for s in symbols if s.name == name]

        # Kind filtering
        if kind:
            kind_lower = kind.lower()
            symbols = [s for s in symbols if self._matches_kind(s.kind, kind_lower)]

        return symbols

    def _matches_kind(self, symbol_kind: str, filter_kind: str) -> bool:
        """Check if symbol kind matches the filter.

        Handles both full names and single-letter abbreviations.
        """
        if not symbol_kind or not filter_kind:
            return True

        symbol_kind_lower = symbol_kind.lower()
        filter_kind_lower = filter_kind.lower()

        # Direct match
        if symbol_kind_lower == filter_kind_lower:
            return True

        # Check if symbol_kind is an abbreviation
        expanded = KIND_MAP.get(symbol_kind, symbol_kind_lower)
        if expanded == filter_kind_lower:
            return True

        # Check common aliases
        aliases = {
            "function": {"f", "function", "func", "method", "m"},
            "class": {"c", "class", "struct", "s"},
            "variable": {"v", "variable", "var"},
            "method": {"m", "method", "function", "f"},
            "constant": {"C", "constant", "const", "d"},
            "interface": {"i", "interface"},
            "type": {"t", "type", "typedef"},
        }

        if filter_kind_lower in aliases:
            return symbol_kind_lower in aliases[filter_kind_lower]

        return False

    def get_symbols_in_file(
        self,
        file_path: str,
        kind: Optional[str] = None,
    ) -> list[Symbol]:
        """Get all symbols defined in a file.

        Args:
            file_path: Relative path to file from repository root.
            kind: Optional filter by symbol kind.

        Returns:
            List of Symbol objects defined in the file, sorted by line number.
        """
        if not self._is_indexed:
            return []

        # Normalize path
        normalized = self._normalize_path(file_path)
        symbols = self._symbols_by_file.get(normalized, [])

        # Also try without leading ./
        if not symbols and normalized.startswith("./"):
            symbols = self._symbols_by_file.get(normalized[2:], [])
        elif not symbols and not normalized.startswith("./"):
            symbols = self._symbols_by_file.get("./" + normalized, [])

        if kind:
            symbols = [s for s in symbols if self._matches_kind(s.kind, kind)]

        return sorted(symbols, key=lambda s: s.line)

    def _normalize_path(self, path: str) -> str:
        """Normalize a file path for consistent lookups."""
        # Remove leading ./ if present, then add it back
        # This ensures consistent format
        path = path.lstrip("./")
        return "./" + path

    def find_definitions(self, name: str, kind: Optional[str] = None) -> list[Symbol]:
        """Find symbol definitions (not usages).

        This returns where symbols are defined, not where they're used.
        Equivalent to "Go to Definition" in IDEs.

        Args:
            name: Symbol name.
            kind: Optional kind filter.

        Returns:
            List of definition locations.
        """
        return self.find_symbol(name, kind=kind)

    def get_symbols_by_kind(self, kind: str) -> list[Symbol]:
        """Get all symbols of a specific kind.

        Args:
            kind: Symbol kind (function, class, variable, etc.).

        Returns:
            List of matching symbols.
        """
        if not self._is_indexed:
            return []

        return [s for s in self._symbols if self._matches_kind(s.kind, kind)]

    def find_symbols_by_pattern(
        self,
        pattern: str,
        kind: Optional[str] = None,
    ) -> list[Symbol]:
        """Find symbols matching a glob-like pattern.

        Args:
            pattern: Pattern with * wildcards (e.g., "*Service", "test_*").
            kind: Optional kind filter.

        Returns:
            List of matching symbols.
        """
        if not self._is_indexed:
            return []

        import fnmatch

        results = []
        for symbol in self._symbols:
            if fnmatch.fnmatch(symbol.name.lower(), pattern.lower()):
                if kind is None or self._matches_kind(symbol.kind, kind):
                    results.append(symbol)

        return results

    def get_class_members(self, class_name: str) -> list[Symbol]:
        """Get all members (methods, properties) of a class.

        Args:
            class_name: Name of the class.

        Returns:
            List of member symbols.
        """
        if not self._is_indexed:
            return []

        return [
            s
            for s in self._symbols
            if s.scope and s.scope.lower() == class_name.lower()
        ]

    def get_file_structure(self, file_path: str) -> dict:
        """Get structured representation of a file's contents.

        Returns a hierarchical view of classes with their members,
        standalone functions, imports, etc.

        Args:
            file_path: Relative path to file.

        Returns:
            Dictionary with structured file information.
        """
        symbols = self.get_symbols_in_file(file_path)

        if not symbols:
            return {
                "file_path": file_path,
                "classes": [],
                "functions": [],
                "variables": [],
                "imports": [],
                "other": [],
            }

        classes = {}
        functions = []
        variables = []
        imports = []
        other = []

        for symbol in symbols:
            kind_lower = symbol.kind.lower()
            expanded_kind = KIND_MAP.get(symbol.kind, kind_lower)

            if expanded_kind in ("class", "struct", "interface", "trait"):
                classes[symbol.name] = {
                    "name": symbol.name,
                    "line": symbol.line,
                    "kind": expanded_kind,
                    "methods": [],
                    "properties": [],
                }
            elif expanded_kind in ("function", "method"):
                if symbol.scope and symbol.scope in classes:
                    classes[symbol.scope]["methods"].append(
                        {
                            "name": symbol.name,
                            "line": symbol.line,
                            "signature": symbol.signature,
                            "access": symbol.access,
                        }
                    )
                else:
                    functions.append(
                        {
                            "name": symbol.name,
                            "line": symbol.line,
                            "signature": symbol.signature,
                        }
                    )
            elif expanded_kind in ("property", "member", "field"):
                if symbol.scope and symbol.scope in classes:
                    classes[symbol.scope]["properties"].append(
                        {
                            "name": symbol.name,
                            "line": symbol.line,
                            "access": symbol.access,
                        }
                    )
                else:
                    variables.append({"name": symbol.name, "line": symbol.line})
            elif expanded_kind in ("variable", "constant"):
                variables.append({"name": symbol.name, "line": symbol.line})
            elif expanded_kind == "import":
                imports.append({"name": symbol.name, "line": symbol.line})
            else:
                other.append(
                    {"name": symbol.name, "line": symbol.line, "kind": expanded_kind}
                )

        return {
            "file_path": file_path,
            "classes": list(classes.values()),
            "functions": functions,
            "variables": variables,
            "imports": imports,
            "other": other,
        }

    def get_stats(self) -> dict:
        """Get statistics about the index.

        Returns:
            Dictionary with index statistics.
        """
        if not self._is_indexed:
            return {"indexed": False}

        # Count by kind
        kind_counts = {}
        for symbol in self._symbols:
            kind = KIND_MAP.get(symbol.kind, symbol.kind)
            kind_counts[kind] = kind_counts.get(kind, 0) + 1

        # Count by language
        lang_counts = {}
        for symbol in self._symbols:
            lang = symbol.language or "unknown"
            lang_counts[lang] = lang_counts.get(lang, 0) + 1

        return {
            "indexed": True,
            "total_symbols": len(self._symbols),
            "total_files": len(self._symbols_by_file),
            "by_kind": kind_counts,
            "by_language": lang_counts,
        }
