"""Tests for MCP schema reader and metadata converter."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from ansibleclaw.core.mcp_schema import (
    McpSchemaError,
    load_tools_from_file,
    load_tools_from_server,
    mcp_tool_to_metadata,
    sanitize_tool_name,
    _extract_params_from_schema,
    _parse_jsonrpc_responses,
)


class TestSanitizeToolName:

    def test_lowercase(self):
        assert sanitize_tool_name("CreateRepository") == "createrepository"

    def test_hyphens_to_underscores(self):
        assert sanitize_tool_name("search-code") == "search_code"

    def test_dots_to_underscores(self):
        assert sanitize_tool_name("aws.ec2.describe") == "aws_ec2_describe"

    def test_strips_invalid_chars(self):
        assert sanitize_tool_name("get@file!") == "getfile"

    def test_collapses_underscores(self):
        assert sanitize_tool_name("a--b..c") == "a_b_c"

    def test_strips_leading_trailing_underscores(self):
        assert sanitize_tool_name("-name-") == "name"

    def test_simple_name_unchanged(self):
        assert sanitize_tool_name("list_issues") == "list_issues"


class TestExtractParamsFromSchema:

    def test_basic_params(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "A name"},
                "count": {"type": "integer", "description": "A count"},
            },
            "required": ["name"],
        }
        params = _extract_params_from_schema(schema)
        assert len(params) == 2
        assert params[0]["name"] == "name"
        assert params[0]["required"] is True
        assert params[0]["type"] == "str"
        assert params[1]["name"] == "count"
        assert params[1]["required"] is False
        assert params[1]["type"] == "int"

    def test_type_mapping(self):
        schema = {
            "type": "object",
            "properties": {
                "s": {"type": "string"},
                "n": {"type": "number"},
                "i": {"type": "integer"},
                "b": {"type": "boolean"},
                "a": {"type": "array"},
                "o": {"type": "object"},
            },
        }
        params = _extract_params_from_schema(schema)
        type_map = {p["name"]: p["type"] for p in params}
        assert type_map == {
            "s": "str", "n": "float", "i": "int",
            "b": "bool", "a": "list", "o": "dict",
        }

    def test_enum_becomes_choices(self):
        schema = {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "enum": ["OPEN", "CLOSED"],
                    "description": "Filter by state",
                },
            },
        }
        params = _extract_params_from_schema(schema)
        assert params[0]["choices"] == ["OPEN", "CLOSED"]

    def test_default_value(self):
        schema = {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "default": 30},
            },
        }
        params = _extract_params_from_schema(schema)
        assert params[0]["default"] == 30

    def test_nullable_type(self):
        schema = {
            "type": "object",
            "properties": {
                "value": {"type": ["string", "null"]},
            },
        }
        params = _extract_params_from_schema(schema)
        assert params[0]["type"] == "str"

    def test_empty_schema(self):
        assert _extract_params_from_schema({}) == []
        assert _extract_params_from_schema({"type": "string"}) == []

    def test_no_properties(self):
        schema = {"type": "object"}
        assert _extract_params_from_schema(schema) == []

    def test_sorted_required_first(self):
        schema = {
            "type": "object",
            "properties": {
                "z_optional": {"type": "string"},
                "a_required": {"type": "string"},
            },
            "required": ["a_required"],
        }
        params = _extract_params_from_schema(schema)
        assert params[0]["name"] == "a_required"
        assert params[1]["name"] == "z_optional"


class TestMcpToolToMetadata:

    def test_basic_conversion(self, sample_mcp_tools):
        tool = sample_mcp_tools[0]
        meta = mcp_tool_to_metadata(tool, "community", "github_mcp")

        assert meta["module_name"] == "create_repository"
        assert meta["tool_name"] == "create_repository"
        assert meta["short_description"] == "Create a new GitHub repository"
        assert meta["is_api_module"] is True
        assert meta["is_read_only"] is False
        assert meta["namespace"] == "community"
        assert meta["collection_name"] == "github_mcp"
        assert len(meta["params"]) == 5

    def test_read_only_tool(self, sample_mcp_tools):
        tool = sample_mcp_tools[1]
        meta = mcp_tool_to_metadata(tool, "community", "github_mcp")
        assert meta["is_read_only"] is True

    def test_tool_name_sanitized(self, sample_mcp_tools):
        tool = sample_mcp_tools[2]
        meta = mcp_tool_to_metadata(tool, "community", "github_mcp")
        assert meta["module_name"] == "search_code"
        assert meta["tool_name"] == "search-code"

    def test_no_annotations(self, sample_mcp_tools):
        tool = sample_mcp_tools[2]
        meta = mcp_tool_to_metadata(tool, "community", "github_mcp")
        assert meta["is_read_only"] is False
        assert meta["is_destructive"] is False

    def test_required_params_first(self, sample_mcp_tools):
        tool = sample_mcp_tools[0]
        meta = mcp_tool_to_metadata(tool, "community", "github_mcp")
        assert meta["params"][0]["name"] == "name"
        assert meta["params"][0]["required"] is True


class TestLoadToolsFromFile:

    def test_bare_list(self, sample_mcp_tools_json):
        tools = load_tools_from_file(sample_mcp_tools_json)
        assert len(tools) == 3
        assert tools[0]["name"] == "create_repository"

    def test_wrapped_response(self, sample_mcp_tools_response_json):
        tools = load_tools_from_file(sample_mcp_tools_response_json)
        assert len(tools) == 3

    def test_missing_file(self, tmp_path):
        with pytest.raises(McpSchemaError, match="Failed to read"):
            load_tools_from_file(tmp_path / "nonexistent.json")

    def test_invalid_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        with pytest.raises(McpSchemaError, match="Failed to read"):
            load_tools_from_file(bad)

    def test_wrong_structure(self, tmp_path):
        bad = tmp_path / "wrong.json"
        bad.write_text(json.dumps({"other": "data"}))
        with pytest.raises(McpSchemaError, match="Expected a JSON array"):
            load_tools_from_file(bad)

    def test_empty_tools(self, tmp_path):
        empty = tmp_path / "empty.json"
        empty.write_text(json.dumps([]))
        with pytest.raises(McpSchemaError, match="No tools found"):
            load_tools_from_file(empty)

    def test_tool_missing_name(self, tmp_path):
        bad = tmp_path / "noname.json"
        bad.write_text(json.dumps([{"description": "no name"}]))
        with pytest.raises(McpSchemaError, match="missing required 'name'"):
            load_tools_from_file(bad)


class TestLoadToolsFromServer:

    def test_successful_query(self, sample_mcp_tools):
        tools_response = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": sample_mcp_tools},
        })
        init_response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": "2025-03-26"},
        })
        stdout = init_response + "\n" + tools_response + "\n"

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (stdout, "")
        mock_proc.poll.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            tools = load_tools_from_server("fake-server")

        assert len(tools) == 3
        assert tools[0]["name"] == "create_repository"

    def test_server_not_found(self):
        with patch("subprocess.Popen", side_effect=FileNotFoundError):
            with pytest.raises(McpSchemaError, match="not found"):
                load_tools_from_server("nonexistent-server")

    def test_server_timeout(self):
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired("cmd", 30)
        mock_proc.poll.return_value = None

        with patch("ansibleclaw.core.mcp_schema.subprocess.Popen", return_value=mock_proc):
            with pytest.raises(McpSchemaError, match="timed out"):
                load_tools_from_server("slow-server", timeout=1)

    def test_server_error_response(self):
        error_response = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -1, "message": "Internal error"},
        })
        stdout = error_response + "\n"

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (stdout, "")
        mock_proc.poll.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            with pytest.raises(McpSchemaError, match="returned error"):
                load_tools_from_server("bad-server")

    def test_no_response(self):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "some error")
        mock_proc.poll.return_value = 1

        with patch("subprocess.Popen", return_value=mock_proc):
            with pytest.raises(McpSchemaError, match="No tools/list response"):
                load_tools_from_server("silent-server")


class TestParseJsonrpcResponses:

    def test_newline_delimited(self):
        lines = (
            '{"jsonrpc":"2.0","id":1,"result":{}}\n'
            '{"jsonrpc":"2.0","method":"notification"}\n'
            '{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}\n'
        )
        responses = _parse_jsonrpc_responses(lines)
        assert len(responses) == 2
        assert responses[0]["id"] == 1
        assert responses[1]["id"] == 2

    def test_content_length_framed(self):
        msg1 = '{"jsonrpc":"2.0","id":1,"result":{}}'
        msg2 = '{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}'
        raw = (
            f"Content-Length: {len(msg1)}\r\n\r\n{msg1}"
            f"Content-Length: {len(msg2)}\r\n\r\n{msg2}"
        )
        responses = _parse_jsonrpc_responses(raw)
        assert len(responses) == 2

    def test_empty_input(self):
        assert _parse_jsonrpc_responses("") == []

    def test_invalid_json_skipped(self):
        lines = 'not json\n{"jsonrpc":"2.0","id":1,"result":{}}\n'
        responses = _parse_jsonrpc_responses(lines)
        assert len(responses) == 1
