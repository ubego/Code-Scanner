import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from code_scanner.ai_tools import AIToolExecutor, ToolResult
from code_scanner.ctags_index import CtagsIndex, Symbol

class TestAIToolsCtagsCoverage:
    """Test suite for ctags-based tools in AIToolExecutor."""

    @pytest.fixture
    def mock_ctags_index(self):
        return MagicMock(spec=CtagsIndex)

    @pytest.fixture
    def executor(self, mock_ctags_index):
        # Create executor with mocked ctags index
        executor = AIToolExecutor(
            target_directory="/tmp/test_repo",
            context_limit=10000,
            ctags_index=mock_ctags_index
        )
        # Mock _is_ctags_ready to return True by default
        executor._is_ctags_ready = MagicMock(return_value=True)
        return executor
    
    def test_find_definition_success(self, executor, mock_ctags_index):
        """Test _find_definition returns found definitions."""
        # Setup mock return
        mock_symbol = MagicMock(spec=Symbol)
        mock_symbol.file_path = "src/model.py"
        mock_symbol.line = 100
        mock_symbol.kind = "class"
        mock_symbol.signature = "class Model"
        mock_symbol.scope = "module"
        mock_symbol.access = "public"
        mock_symbol.language = "Python"
        
        mock_ctags_index.find_definitions.return_value = [mock_symbol]
        
        # Execute
        result = executor._find_definition("Model", "class")
        
        # Verify
        assert result.success is True
        assert result.data["found"] is True
        assert result.data["symbol"] == "Model"
        assert len(result.data["definitions"]) == 1
        assert result.data["definitions"][0]["file"] == "src/model.py"

    def test_find_definition_not_found(self, executor, mock_ctags_index):
        """Test _find_definition handles missing symbol."""
        mock_ctags_index.find_definitions.return_value = []
        
        result = executor._find_definition("Missing", None)
        
        assert result.success is True
        assert result.data["found"] is False
        assert result.data["definitions"] == []

    def test_find_definition_missing_arg(self, executor):
        """Test _find_definition requires symbol arg."""
        result = executor._find_definition("", None)
        assert result.success is False
        assert "symbol is required" in result.error

    def test_find_definition_exception(self, executor, mock_ctags_index):
        """Test _find_definition handles exceptions."""
        mock_ctags_index.find_definitions.side_effect = Exception("DB error")
        
        result = executor._find_definition("Symbol", None)
        
        assert result.success is False
        assert "Error finding definition" in result.error

    def test_list_symbols_success(self, executor, mock_ctags_index):
        """Test _list_symbols returns symbols in file."""
        mock_symbol = MagicMock(spec=Symbol)
        mock_symbol.name = "func"
        mock_symbol.line = 10
        mock_symbol.kind = "function"
        mock_symbol.scope = "global"
        mock_symbol.signature = "def func()"
        mock_symbol.access = "public"
        
        mock_ctags_index.get_symbols_in_file.return_value = [mock_symbol]
        
        result = executor._list_symbols("src/main.py", None)
        
        assert result.success is True
        assert result.data["file_path"] == "src/main.py"
        assert result.data["symbol_count"] == 1
        assert result.data["symbols"][0]["name"] == "func"

    def test_list_symbols_empty(self, executor, mock_ctags_index):
        """Test _list_symbols handles files with no symbols."""
        mock_ctags_index.get_symbols_in_file.return_value = []
        
        result = executor._list_symbols("src/empty.py", None)
        
        assert result.success is True
        assert result.data["symbol_count"] == 0
        assert result.data["symbols"] == []

    def test_list_symbols_missing_arg(self, executor):
        """Test _list_symbols requires file_path."""
        result = executor._list_symbols("", None)
        assert result.success is False
        assert "file_path is required" in result.error

    def test_find_symbols_success(self, executor, mock_ctags_index):
        """Test _find_symbols returns matching symbols."""
        mock_symbol = MagicMock(spec=Symbol)
        # Use configure_mock to set attributes safely
        mock_symbol.configure_mock(
            name="UserHandler",
            file_path="src/handler.py",
            line=50,
            kind="class",
            scope="global"
        )
        
        mock_ctags_index.find_symbols_by_pattern.return_value = [mock_symbol]
        
        result = executor._find_symbols("*Handler", "class")
        
        assert result.success is True
        assert result.data["match_count"] == 1
        assert result.data["matches"][0]["name"] == "UserHandler"

    def test_find_symbols_pagination(self, executor, mock_ctags_index):
        """Test _find_symbols handles larger result sets (pagination simulation)."""
        # Create 60 mock symbols
        long_list = []
        for i in range(60):
            m = MagicMock(spec=Symbol)
            m.configure_mock(
                name=f"Sym{i}",
                file_path="f",
                line=i,
                kind="var",
                scope="g"
            )
            long_list.append(m)

        mock_ctags_index.find_symbols_by_pattern.return_value = long_list
        
        result = executor._find_symbols("Sym*", None)
        
        assert result.success is True
        assert result.data["match_count"] == 60
        assert result.data["returned_count"] == 50  # Capped at 50
        assert result.data["has_more"] is True

    def test_get_class_members_success_with_filtering(self, executor, mock_ctags_index):
        """Test _get_class_members correctly filters by file when multiple classes exist."""
        # Class definition mock
        class_sym = MagicMock(spec=Symbol)
        class_sym.configure_mock(
            file_path="src/target.py",
            line=10,
            kind="class"
        )
        
        mock_ctags_index.find_symbol.return_value = [class_sym]
        
        # Members checks
        m1 = MagicMock(spec=Symbol)
        m1.configure_mock(
            name="method1",
            file_path="src/target.py",
            kind="method",
            line=11,
            signature="def method1()",
            access="public"
        )
        
        m2 = MagicMock(spec=Symbol)
        m2.configure_mock(
            name="method2",
            file_path="src/other.py",
            kind="method",
            line=20,
            signature="def method2()",
            access="public"
        )
        
        mock_ctags_index.get_class_members.return_value = [m1, m2]
        
        result = executor._get_class_members("MyClass")
        
        assert result.success is True
        assert result.data["found"] is True
        # Should filter to only include members from src/target.py
        assert result.data["member_count"] == 1
        assert result.data["methods"][0]["name"] == "method1"

    def test_get_class_members_not_found(self, executor, mock_ctags_index):
        """Test _get_class_members when class doesn't exist."""
        mock_ctags_index.find_symbol.return_value = []
        mock_ctags_index.get_class_members.return_value = []
        
        result = executor._get_class_members("GhostClass")
        
        assert result.success is True
        assert result.data["found"] is False
        assert result.data.get("member_count") is None or result.data.get("members") == []

    def test_get_index_stats_indexing(self, executor, mock_ctags_index):
        """Test _get_index_stats when indexing is in progress."""
        # Override ready check to false
        executor._is_ctags_ready.return_value = False
        # Mock is_indexing on the ctags_index instance
        type(mock_ctags_index).is_indexing = PropertyMock(return_value=True)
        
        result = executor._get_index_stats()
        
        assert result.success is True
        assert result.data["status"] == "indexing_in_progress"

    def test_get_index_stats_ready(self, executor, mock_ctags_index):
        """Test _get_index_stats when ready."""
        type(mock_ctags_index).is_indexing = PropertyMock(return_value=False)
        mock_ctags_index.get_stats.return_value = {"files": 10, "symbols": 100}
        
        result = executor._get_index_stats()
        
        assert result.success is True
        assert result.data["files"] == 10
        assert result.data["symbols"] == 100

    def test_get_index_stats_exception(self, executor, mock_ctags_index):
        """Test _get_index_stats handles failures."""
        type(mock_ctags_index).is_indexing = PropertyMock(return_value=False)
        mock_ctags_index.get_stats.side_effect = Exception("Stat error")
        
        result = executor._get_index_stats()
        
        assert result.success is False
        assert "Error getting index stats" in result.error

    def test_not_ready_checks(self, executor, mock_ctags_index):
        """Test that all tools check for readiness."""
        executor._is_ctags_ready.return_value = False
        type(mock_ctags_index).is_indexing = PropertyMock(return_value=False)
        # Ensure index_error is None/False so we don't hit the error branch
        mock_ctags_index.index_error = None
        
        # Test a few tools
        r1 = executor._find_definition("X", None)
        assert r1.data["status"] == "not_indexed"
        
        r2 = executor._list_symbols("f", None)
        assert r2.data["status"] == "not_indexed"
        
        r3 = executor._get_class_members("C")
        assert r3.data["status"] == "not_indexed"
