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

    def test_not_ready_checks(self, executor, mock_ctags_index):
        """Test that tools check for readiness."""
        executor._is_ctags_ready.return_value = False
        type(mock_ctags_index).is_indexing = PropertyMock(return_value=False)
        # Ensure index_error is None/False so we don't hit the error branch
        mock_ctags_index.index_error = None
        
        # Test existing tools
        r1 = executor._find_definition("X", None)
        assert r1.data["status"] == "not_indexed"
        
        r2 = executor._find_symbols("pattern", None)
        assert r2.data["status"] == "not_indexed"
