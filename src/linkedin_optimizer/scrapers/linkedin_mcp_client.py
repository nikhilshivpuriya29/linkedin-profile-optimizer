"""LinkedIn MCP Client adapter for communicating with linkedin-mcp-server.

This module provides an adapter that abstracts the MCP protocol communication
with the stickerdaniel/linkedin-mcp-server. Communication is done via JSON-RPC
over stdio, with the MCP server launched as a subprocess using `uvx`.

MCP Tools Available:
- get_person_profile: Retrieves a LinkedIn profile by URL
- get_my_profile: Retrieves the authenticated user's profile
- get_feed: Retrieves LinkedIn feed posts
"""

import asyncio
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# --- Custom Exceptions ---


class MCPConnectionError(Exception):
    """Raised when the MCP server cannot be started or communication fails.

    This covers scenarios like:
    - uvx not installed or not in PATH
    - MCP server process fails to start
    - Subprocess stdin/stdout communication errors
    - JSON-RPC protocol errors (malformed responses)
    """

    pass


class MCPToolError(Exception):
    """Raised when an MCP tool call returns an error response.

    This covers scenarios like:
    - Tool returns an error result (e.g., profile not found, auth failure)
    - Tool execution times out
    - Invalid parameters passed to a tool
    """

    def __init__(self, message: str, tool_name: str = "", error_code: Optional[int] = None):
        super().__init__(message)
        self.tool_name = tool_name
        self.error_code = error_code


class LinkedInMCPClient:
    """Adapter for linkedin-mcp-server MCP tools via subprocess communication.

    The MCP server is invoked via `uvx linkedin-mcp-server` and communicates
    using the JSON-RPC 2.0 protocol over stdio (stdin/stdout).

    MCP Protocol Flow:
    1. Start the MCP server subprocess
    2. Send `initialize` request to establish capabilities
    3. Send `tools/call` requests to invoke specific tools
    4. Parse JSON-RPC responses for results or errors

    Usage:
        config = {"command": "uvx", "args": ["linkedin-mcp-server"]}
        client = LinkedInMCPClient(config)
        profile = await client.get_person_profile("https://linkedin.com/in/someone")
    """

    def __init__(self, mcp_server_config: dict):
        """Configure the MCP client connection settings.

        Args:
            mcp_server_config: Configuration dict with keys:
                - command: The command to run (default: "uvx")
                - args: Arguments for the command (default: ["linkedin-mcp-server"])
                - env: Optional environment variables for the subprocess
                - timeout: Request timeout in seconds (default: 30)
        """
        self._command = mcp_server_config.get("command", "uvx")
        self._args = mcp_server_config.get("args", ["linkedin-mcp-server"])
        self._env = mcp_server_config.get("env", None)
        self._timeout = mcp_server_config.get("timeout", 30)
        self._request_id = 0
        self._process: Optional[asyncio.subprocess.Process] = None
        self._initialized = False

    async def _start_server(self) -> None:
        """Start the MCP server subprocess.

        Launches the linkedin-mcp-server via uvx and establishes stdio communication.

        Raises:
            MCPConnectionError: If the server cannot be started.
        """
        try:
            self._process = await asyncio.create_subprocess_exec(
                self._command,
                *self._args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env,
            )
            logger.info(
                "MCP server started: %s %s (pid=%s)",
                self._command,
                " ".join(self._args),
                self._process.pid,
            )
        except FileNotFoundError:
            raise MCPConnectionError(
                f"Command not found: '{self._command}'. "
                "Ensure uvx is installed (pip install uv) and available in PATH."
            )
        except OSError as e:
            raise MCPConnectionError(
                f"Failed to start MCP server subprocess: {e}"
            )

    async def _ensure_initialized(self) -> None:
        """Ensure the MCP server is started and initialized.

        Performs the MCP initialization handshake if not already done.

        Raises:
            MCPConnectionError: If initialization fails.
        """
        if self._initialized and self._process is not None:
            return

        await self._start_server()
        await self._send_initialize()
        self._initialized = True

    async def _send_initialize(self) -> dict:
        """Send the MCP initialize request to establish the session.

        Returns:
            The server's capabilities response.

        Raises:
            MCPConnectionError: If the initialization handshake fails.
        """
        response = await self._send_request(
            method="initialize",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "linkedin-optimizer",
                    "version": "1.0.0",
                },
            },
        )

        # Send initialized notification (no response expected)
        await self._send_notification("notifications/initialized", params={})

        return response

    async def _send_request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and wait for a response.

        Args:
            method: The JSON-RPC method to call.
            params: Parameters for the method.

        Returns:
            The result field from the JSON-RPC response.

        Raises:
            MCPConnectionError: If communication fails.
            MCPToolError: If the server returns an error response.
        """
        if self._process is None or self._process.stdin is None:
            raise MCPConnectionError("MCP server process is not running.")

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        request_bytes = json.dumps(request).encode("utf-8") + b"\n"

        try:
            self._process.stdin.write(request_bytes)
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            raise MCPConnectionError(
                f"Failed to write to MCP server stdin: {e}"
            )

        # Read response
        response = await self._read_response()
        return response

    async def _send_notification(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no response expected).

        Args:
            method: The notification method.
            params: Parameters for the notification.

        Raises:
            MCPConnectionError: If communication fails.
        """
        if self._process is None or self._process.stdin is None:
            raise MCPConnectionError("MCP server process is not running.")

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        notification_bytes = json.dumps(notification).encode("utf-8") + b"\n"

        try:
            self._process.stdin.write(notification_bytes)
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            raise MCPConnectionError(
                f"Failed to send notification to MCP server: {e}"
            )

    async def _read_response(self) -> dict:
        """Read and parse a JSON-RPC response from the server's stdout.

        Returns:
            The result field from the JSON-RPC response.

        Raises:
            MCPConnectionError: If reading or parsing fails.
            MCPToolError: If the response contains an error.
        """
        if self._process is None or self._process.stdout is None:
            raise MCPConnectionError("MCP server process is not running.")

        try:
            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            raise MCPConnectionError(
                f"Timeout waiting for MCP server response (>{self._timeout}s)."
            )

        if not line:
            # Read stderr for diagnostic info
            stderr_output = ""
            if self._process.stderr:
                try:
                    stderr_data = await asyncio.wait_for(
                        self._process.stderr.read(4096),
                        timeout=2.0,
                    )
                    stderr_output = stderr_data.decode("utf-8", errors="replace")
                except asyncio.TimeoutError:
                    pass
            raise MCPConnectionError(
                f"MCP server closed connection unexpectedly. stderr: {stderr_output}"
            )

        try:
            response = json.loads(line.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise MCPConnectionError(
                f"Failed to parse MCP server response as JSON: {e}. "
                f"Raw response: {line[:200]}"
            )

        # Check for JSON-RPC error
        if "error" in response:
            error = response["error"]
            error_code = error.get("code", -1)
            error_message = error.get("message", "Unknown MCP error")
            raise MCPToolError(
                message=f"MCP error ({error_code}): {error_message}",
                error_code=error_code,
            )

        return response.get("result", {})

    async def _call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Call an MCP tool and return the result.

        Args:
            tool_name: Name of the MCP tool to call.
            arguments: Arguments to pass to the tool.

        Returns:
            The tool's result data.

        Raises:
            MCPConnectionError: If communication with the server fails.
            MCPToolError: If the tool returns an error.
        """
        await self._ensure_initialized()

        result = await self._send_request(
            method="tools/call",
            params={
                "name": tool_name,
                "arguments": arguments,
            },
        )

        # MCP tool results are typically in result.content[0].text
        if isinstance(result, dict):
            content = result.get("content", [])

            # Check if there's an isError flag first
            if result.get("isError", False):
                error_text = ""
                if content and isinstance(content, list):
                    error_text = content[0].get("text", "") if content[0] else ""
                raise MCPToolError(
                    message=f"Tool '{tool_name}' returned an error: {error_text}",
                    tool_name=tool_name,
                )

            if content and isinstance(content, list):
                first_content = content[0]
                if isinstance(first_content, dict) and "text" in first_content:
                    text = first_content["text"]
                    # Try to parse as JSON
                    try:
                        return json.loads(text)
                    except (json.JSONDecodeError, TypeError):
                        return text

        return result

    async def get_person_profile(self, profile_url: str) -> dict:
        """Retrieve a LinkedIn profile by URL.

        Calls the MCP tool `get_person_profile` which extracts profile data
        from the given LinkedIn profile URL using the authenticated browser session.

        Args:
            profile_url: Full LinkedIn profile URL
                (e.g., "https://www.linkedin.com/in/username").

        Returns:
            Dict containing profile data with sections like headline, about,
            experience, skills, education, etc.

        Raises:
            MCPConnectionError: If the MCP server cannot be reached.
            MCPToolError: If profile extraction fails (invalid URL, private profile, etc).
        """
        if not profile_url or not isinstance(profile_url, str):
            raise MCPToolError(
                message="profile_url must be a non-empty string",
                tool_name="get_person_profile",
            )

        logger.info("Fetching LinkedIn profile: %s", profile_url)

        try:
            result = await self._call_tool(
                tool_name="linkedin_get_member_profile",
                arguments={"member_urn": profile_url},
            )
        except MCPConnectionError:
            raise
        except MCPToolError:
            raise
        except Exception as e:
            raise MCPConnectionError(
                f"Unexpected error calling get_person_profile: {e}"
            )

        logger.info("Successfully fetched profile for: %s", profile_url)
        return result

    async def get_my_profile(self) -> dict:
        """Retrieve the authenticated user's LinkedIn profile.

        Calls the MCP tool `get_my_profile` which returns the profile data
        of the currently logged-in LinkedIn user.

        Returns:
            Dict containing the authenticated user's profile data.

        Raises:
            MCPConnectionError: If the MCP server cannot be reached.
            MCPToolError: If profile retrieval fails.
        """
        logger.info("Fetching authenticated user's LinkedIn profile")

        try:
            result = await self._call_tool(
                tool_name="linkedin_get_my_profile",
                arguments={},
            )
        except MCPConnectionError:
            raise
        except MCPToolError:
            raise
        except Exception as e:
            raise MCPConnectionError(
                f"Unexpected error calling get_my_profile: {e}"
            )

        logger.info("Successfully fetched authenticated user profile")
        return result

    async def get_feed(self, count: int = 10) -> list[dict]:
        """Retrieve LinkedIn feed posts.

        Calls the MCP tool `get_feed` to retrieve recent posts from the
        user's LinkedIn feed for engagement analysis.

        Args:
            count: Number of feed posts to retrieve (default: 10).

        Returns:
            List of dicts, each representing a feed post with engagement metrics.

        Raises:
            MCPConnectionError: If the MCP server cannot be reached.
            MCPToolError: If feed retrieval fails.
        """
        if count < 1:
            raise MCPToolError(
                message="count must be a positive integer",
                tool_name="get_feed",
            )

        logger.info("Fetching LinkedIn feed (count=%d)", count)

        try:
            result = await self._call_tool(
                tool_name="linkedin_get_recent_posts",
                arguments={"count": count},
            )
        except MCPConnectionError:
            raise
        except MCPToolError:
            raise
        except Exception as e:
            raise MCPConnectionError(
                f"Unexpected error calling get_feed: {e}"
            )

        # Ensure result is a list
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and "posts" in result:
            return result["posts"]
        else:
            logger.warning("Unexpected feed response format, wrapping in list")
            return [result] if result else []

    async def close(self) -> None:
        """Shut down the MCP server subprocess gracefully.

        Sends a terminate signal and waits for the process to exit.
        """
        if self._process is not None:
            logger.info("Shutting down MCP server (pid=%s)", self._process.pid)
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("MCP server did not exit gracefully, killing")
                self._process.kill()
                await self._process.wait()
            except ProcessLookupError:
                pass  # Process already exited
            finally:
                self._process = None
                self._initialized = False

    async def __aenter__(self) -> "LinkedInMCPClient":
        """Support async context manager usage."""
        await self._ensure_initialized()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Ensure cleanup on context manager exit."""
        await self.close()
