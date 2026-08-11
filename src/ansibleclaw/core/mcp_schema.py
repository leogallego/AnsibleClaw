"""MCP tool schema reader and metadata converter.

Reads MCP server tool definitions from static JSON files or live
servers (via JSON-RPC over stdio), then converts them to the same
param-dict format used by parser.extract_module_metadata().
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


class McpSchemaError(Exception):
    """Raised when MCP schema loading or parsing fails."""


# JSON Schema type → Ansible argument_spec type
_TYPE_MAP: dict[str, str] = {
    "string": "str",
    "number": "float",
    "integer": "int",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}


def sanitize_tool_name(name: str) -> str:
    """Convert an MCP tool name to a valid Python/Ansible module name.

    Lowercases, replaces hyphens and dots with underscores, strips
    any remaining non-alphanumeric/underscore characters.
    """
    name = name.lower()
    name = re.sub(r"[-.]", "_", name)
    name = re.sub(r"[^a-z0-9_]", "", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def load_tools_from_file(path: Path) -> list[dict[str, Any]]:
    """Load MCP tool definitions from a static JSON file.

    Accepts either the raw tools/list response (with a ``tools`` key)
    or a bare list of tool objects.
    """
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise McpSchemaError(f"Failed to read MCP schema file: {exc}")

    if isinstance(data, dict) and "tools" in data:
        tools = data["tools"]
    elif isinstance(data, list):
        tools = data
    else:
        raise McpSchemaError(
            "Expected a JSON array of tools or an object with a 'tools' key."
        )

    if not tools:
        raise McpSchemaError("No tools found in schema file.")

    for tool in tools:
        if "name" not in tool:
            raise McpSchemaError(f"Tool missing required 'name' field: {tool}")

    return tools


def load_tools_from_server(
    command: str,
    timeout: int = 30,
    env: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Query a live MCP server for its tool definitions.

    Starts the server as a subprocess (stdio transport), sends
    JSON-RPC ``initialize`` and ``tools/list`` requests, then
    returns the tool list.

    The MCP stdio transport uses newline-delimited JSON messages.
    """
    import shlex

    cmd_parts = shlex.split(command)

    try:
        proc = subprocess.Popen(
            cmd_parts,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
    except FileNotFoundError:
        raise McpSchemaError(f"MCP server command not found: {cmd_parts[0]}")

    try:
        initialize_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "ansibleclaw", "version": "0.1.0"},
            },
        }

        initialized_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }

        tools_list_req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        }

        messages = [
            json.dumps(initialize_req),
            json.dumps(initialized_notification),
            json.dumps(tools_list_req),
        ]
        stdin_data = "\n".join(messages) + "\n"

        stdout, stderr = proc.communicate(input=stdin_data, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise McpSchemaError(f"MCP server timed out after {timeout}s")
    finally:
        if proc.poll() is None:
            proc.kill()

    responses = _parse_jsonrpc_responses(stdout)

    tools_response = None
    for resp in responses:
        if resp.get("id") == 2:
            tools_response = resp
            break

    if not tools_response:
        raise McpSchemaError(
            f"No tools/list response received from MCP server. "
            f"Stderr: {stderr.strip()}"
        )

    if "error" in tools_response:
        err = tools_response["error"]
        raise McpSchemaError(
            f"MCP server returned error: {err.get('message', err)}"
        )

    result = tools_response.get("result", {})
    tools = result.get("tools", [])

    if not tools:
        raise McpSchemaError("MCP server returned no tools.")

    return tools


def _parse_jsonrpc_responses(raw: str) -> list[dict[str, Any]]:
    """Parse JSON-RPC responses from stdout.

    Handles both newline-delimited JSON and Content-Length framed
    (LSP-style) messages.
    """
    responses: list[dict[str, Any]] = []

    if "Content-Length:" in raw:
        parts = raw.split("Content-Length:")
        for part in parts[1:]:
            try:
                header_end = part.index("\r\n\r\n")
                body = part[header_end + 4 :]
                length = int(part[:header_end].strip())
                obj = json.loads(body[:length])
                if "id" in obj:
                    responses.append(obj)
            except (ValueError, json.JSONDecodeError):
                continue
    else:
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and "id" in obj:
                    responses.append(obj)
            except json.JSONDecodeError:
                continue

    return responses


def mcp_tool_to_metadata(
    tool: dict[str, Any],
    namespace: str,
    collection_name: str,
) -> dict[str, Any]:
    """Convert an MCP tool definition to the metadata format used by templates.

    Returns a dict compatible with ``parser.extract_module_metadata()``
    output, with extra fields for MCP-specific context.
    """
    tool_name = tool["name"]
    module_name = sanitize_tool_name(tool_name)
    description = tool.get("description", "")
    input_schema = tool.get("inputSchema", {})
    annotations = tool.get("annotations", {})

    params = _extract_params_from_schema(input_schema)

    is_read_only = annotations.get("readOnlyHint", False)
    is_destructive = annotations.get("destructiveHint", False)

    return {
        "module_name": module_name,
        "tool_name": tool_name,
        "short_description": description,
        "params": params,
        "examples": "",
        "is_api_module": True,
        "is_read_only": is_read_only,
        "is_destructive": is_destructive,
        "namespace": namespace,
        "collection_name": collection_name,
    }


def _extract_params_from_schema(
    schema: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract parameter list from a JSON Schema object."""
    if not schema or schema.get("type") != "object":
        return []

    properties = schema.get("properties", {})
    required_set = set(schema.get("required", []))

    params: list[dict[str, Any]] = []
    for param_name, prop in properties.items():
        json_type = prop.get("type", "string")
        if isinstance(json_type, list):
            json_type = next((t for t in json_type if t != "null"), "string")

        params.append({
            "name": param_name,
            "type": _TYPE_MAP.get(json_type, "raw"),
            "required": param_name in required_set,
            "default": prop.get("default"),
            "choices": prop.get("enum"),
            "description": prop.get("description", ""),
            "aliases": [],
        })

    params.sort(key=lambda p: (not p["required"], p["name"]))
    return params
