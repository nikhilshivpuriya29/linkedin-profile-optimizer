"""Unit tests for LinkedInMCPClient."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linkedin_optimizer.scrapers.linkedin_mcp_client import (
    LinkedInMCPClient,
    MCPConnectionError,
    MCPToolError,
)


@pytest.fixture
def mcp_config():
    """Standard MCP server configuration for tests."""
    return {
        "command": "uvx",
        "args": ["linkedin-mcp-server"],
        "timeout": 10,
    }


@pytest.fixture
def client(mcp_config):
    """Create a LinkedInMCPClient instance."""
    return LinkedInMCPClient(mcp_config)


class TestLinkedInMCPClientInit:
    """Tests for LinkedInMCPClient initialization."""

    def test_default_config(self):
        """Client uses sensible defaults when minimal config provided."""
        client = LinkedInMCPClient({})
        assert client._command == "uvx"
        assert client._args == ["linkedin-mcp-server"]
        assert client._timeout == 30
        assert client._process is None
        assert client._initialized is False

    def test_custom_config(self):
        """Client respects custom configuration values."""
        config = {
            "command": "/usr/local/bin/uvx",
            "args": ["linkedin-mcp-server", "--debug"],
            "timeout": 60,
            "env": {"SOME_VAR": "value"},
        }
        client = LinkedInMCPClient(config)
        assert client._command == "/usr/local/bin/uvx"
        assert client._args == ["linkedin-mcp-server", "--debug"]
        assert client._timeout == 60
        assert client._env == {"SOME_VAR": "value"}


class TestMCPExceptions:
    """Tests for custom exception classes."""

    def test_mcp_connection_error(self):
        """MCPConnectionError stores message correctly."""
        err = MCPConnectionError("Server failed to start")
        assert str(err) == "Server failed to start"

    def test_mcp_tool_error_basic(self):
        """MCPToolError stores message correctly."""
        err = MCPToolError("Profile not found")
        assert str(err) == "Profile not found"
        assert err.tool_name == ""
        assert err.error_code is None

    def test_mcp_tool_error_with_details(self):
        """MCPToolError stores tool_name and error_code."""
        err = MCPToolError("Auth failed", tool_name="get_person_profile", error_code=-32600)
        assert str(err) == "Auth failed"
        assert err.tool_name == "get_person_profile"
        assert err.error_code == -32600


class TestStartServer:
    """Tests for MCP server process management."""

    @pytest.mark.asyncio
    async def test_start_server_command_not_found(self, client):
        """Raises MCPConnectionError if uvx is not installed."""
        client._command = "/nonexistent/command"
        with pytest.raises(MCPConnectionError, match="Command not found"):
            await client._start_server()

    @pytest.mark.asyncio
    async def test_close_when_no_process(self, client):
        """close() is a no-op when no process is running."""
        await client.close()  # Should not raise


class TestGetPersonProfile:
    """Tests for get_person_profile method."""

    @pytest.mark.asyncio
    async def test_invalid_empty_url(self, client):
        """Raises MCPToolError for empty profile URL."""
        with pytest.raises(MCPToolError, match="non-empty string"):
            await client.get_person_profile("")

    @pytest.mark.asyncio
    async def test_invalid_none_url(self, client):
        """Raises MCPToolError for None profile URL."""
        with pytest.raises(MCPToolError, match="non-empty string"):
            await client.get_person_profile(None)

    @pytest.mark.asyncio
    async def test_successful_profile_fetch(self, client):
        """Successfully fetches profile data via MCP tool call."""
        mock_profile = {
            "headline": "Software Engineer",
            "about": "Building things",
            "experience": [{"title": "Engineer", "company": "Acme"}],
        }

        client._call_tool = AsyncMock(return_value=mock_profile)
        client._ensure_initialized = AsyncMock()

        result = await client.get_person_profile("https://linkedin.com/in/testuser")
        assert result == mock_profile
        client._call_tool.assert_called_once_with(
            tool_name="get_person_profile",
            arguments={"profile_url": "https://linkedin.com/in/testuser"},
        )

    @pytest.mark.asyncio
    async def test_connection_error_propagates(self, client):
        """MCPConnectionError propagates from _call_tool."""
        client._call_tool = AsyncMock(
            side_effect=MCPConnectionError("Server down")
        )
        client._ensure_initialized = AsyncMock()

        with pytest.raises(MCPConnectionError, match="Server down"):
            await client.get_person_profile("https://linkedin.com/in/testuser")

    @pytest.mark.asyncio
    async def test_tool_error_propagates(self, client):
        """MCPToolError propagates from _call_tool."""
        client._call_tool = AsyncMock(
            side_effect=MCPToolError("Profile not found", tool_name="get_person_profile")
        )
        client._ensure_initialized = AsyncMock()

        with pytest.raises(MCPToolError, match="Profile not found"):
            await client.get_person_profile("https://linkedin.com/in/nobody")


class TestGetMyProfile:
    """Tests for get_my_profile method."""

    @pytest.mark.asyncio
    async def test_successful_my_profile_fetch(self, client):
        """Successfully fetches authenticated user's profile."""
        mock_profile = {
            "headline": "My Profile",
            "about": "About me",
        }

        client._call_tool = AsyncMock(return_value=mock_profile)
        client._ensure_initialized = AsyncMock()

        result = await client.get_my_profile()
        assert result == mock_profile
        client._call_tool.assert_called_once_with(
            tool_name="get_my_profile",
            arguments={},
        )


class TestGetFeed:
    """Tests for get_feed method."""

    @pytest.mark.asyncio
    async def test_invalid_count_zero(self, client):
        """Raises MCPToolError for count < 1."""
        with pytest.raises(MCPToolError, match="positive integer"):
            await client.get_feed(count=0)

    @pytest.mark.asyncio
    async def test_invalid_count_negative(self, client):
        """Raises MCPToolError for negative count."""
        with pytest.raises(MCPToolError, match="positive integer"):
            await client.get_feed(count=-5)

    @pytest.mark.asyncio
    async def test_successful_feed_fetch_list(self, client):
        """Successfully fetches feed when result is a list."""
        mock_posts = [
            {"text": "Post 1", "reactions": 10},
            {"text": "Post 2", "reactions": 20},
        ]

        client._call_tool = AsyncMock(return_value=mock_posts)
        client._ensure_initialized = AsyncMock()

        result = await client.get_feed(count=5)
        assert result == mock_posts
        client._call_tool.assert_called_once_with(
            tool_name="get_feed",
            arguments={"count": 5},
        )

    @pytest.mark.asyncio
    async def test_feed_dict_with_posts_key(self, client):
        """Extracts posts from dict response with 'posts' key."""
        mock_response = {
            "posts": [{"text": "Post 1"}, {"text": "Post 2"}],
            "total": 2,
        }

        client._call_tool = AsyncMock(return_value=mock_response)
        client._ensure_initialized = AsyncMock()

        result = await client.get_feed(count=5)
        assert result == [{"text": "Post 1"}, {"text": "Post 2"}]

    @pytest.mark.asyncio
    async def test_feed_default_count(self, client):
        """Uses default count of 10 when not specified."""
        client._call_tool = AsyncMock(return_value=[])
        client._ensure_initialized = AsyncMock()

        await client.get_feed()
        client._call_tool.assert_called_once_with(
            tool_name="get_feed",
            arguments={"count": 10},
        )


class TestCallTool:
    """Tests for the internal _call_tool method."""

    @pytest.mark.asyncio
    async def test_parses_content_text_as_json(self, client):
        """Parses JSON text from MCP content response."""
        client._ensure_initialized = AsyncMock()
        client._send_request = AsyncMock(
            return_value={
                "content": [
                    {"type": "text", "text": '{"headline": "Engineer"}'}
                ]
            }
        )

        result = await client._call_tool("get_my_profile", {})
        assert result == {"headline": "Engineer"}

    @pytest.mark.asyncio
    async def test_returns_raw_text_if_not_json(self, client):
        """Returns raw text when content is not valid JSON."""
        client._ensure_initialized = AsyncMock()
        client._send_request = AsyncMock(
            return_value={
                "content": [
                    {"type": "text", "text": "Some plain text response"}
                ]
            }
        )

        result = await client._call_tool("get_my_profile", {})
        assert result == "Some plain text response"

    @pytest.mark.asyncio
    async def test_raises_tool_error_on_is_error_flag(self, client):
        """Raises MCPToolError when isError is True in response."""
        client._ensure_initialized = AsyncMock()
        client._send_request = AsyncMock(
            return_value={
                "content": [{"type": "text", "text": "Authentication required"}],
                "isError": True,
            }
        )

        with pytest.raises(MCPToolError, match="returned an error"):
            await client._call_tool("get_person_profile", {"profile_url": "test"})


class TestReadResponse:
    """Tests for _read_response parsing."""

    @pytest.mark.asyncio
    async def test_parses_valid_json_rpc_response(self, client):
        """Correctly parses a valid JSON-RPC response."""
        mock_process = MagicMock()
        mock_stdout = AsyncMock()
        response_data = {"jsonrpc": "2.0", "id": 1, "result": {"data": "value"}}
        mock_stdout.readline = AsyncMock(
            return_value=json.dumps(response_data).encode("utf-8") + b"\n"
        )
        mock_process.stdout = mock_stdout
        client._process = mock_process

        result = await client._read_response()
        assert result == {"data": "value"}

    @pytest.mark.asyncio
    async def test_raises_on_json_rpc_error(self, client):
        """Raises MCPToolError for JSON-RPC error response."""
        mock_process = MagicMock()
        mock_stdout = AsyncMock()
        response_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": "Method not found"},
        }
        mock_stdout.readline = AsyncMock(
            return_value=json.dumps(response_data).encode("utf-8") + b"\n"
        )
        mock_process.stdout = mock_stdout
        client._process = mock_process

        with pytest.raises(MCPToolError, match="Method not found"):
            await client._read_response()

    @pytest.mark.asyncio
    async def test_raises_on_empty_response(self, client):
        """Raises MCPConnectionError when server closes connection."""
        mock_process = MagicMock()
        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(return_value=b"")
        mock_stderr = AsyncMock()
        mock_stderr.read = AsyncMock(return_value=b"server crashed")
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        client._process = mock_process

        with pytest.raises(MCPConnectionError, match="closed connection"):
            await client._read_response()

    @pytest.mark.asyncio
    async def test_raises_on_invalid_json(self, client):
        """Raises MCPConnectionError for non-JSON response."""
        mock_process = MagicMock()
        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(return_value=b"not json at all\n")
        mock_process.stdout = mock_stdout
        client._process = mock_process

        with pytest.raises(MCPConnectionError, match="Failed to parse"):
            await client._read_response()
