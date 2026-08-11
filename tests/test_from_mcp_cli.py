"""Tests for the from-mcp CLI subcommand."""

import json
import subprocess
import sys
from unittest.mock import patch

import pytest


class TestFromMcpCli:

    def test_help_text(self):
        result = subprocess.run(
            [sys.executable, "-m", "ansibleclaw.cli", "from-mcp", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--server" in result.stdout
        assert "--schema" in result.stdout
        assert "--namespace" in result.stdout
        assert "--name" in result.stdout

    def test_requires_input_source(self, tmp_path):
        result = subprocess.run(
            [
                sys.executable, "-m", "ansibleclaw.cli", "from-mcp",
                "--namespace", "test", "--name", "test",
                "--output", str(tmp_path),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert "either --server or --schema" in result.stderr

    def test_requires_namespace(self):
        result = subprocess.run(
            [
                sys.executable, "-m", "ansibleclaw.cli", "from-mcp",
                "--schema", "tools.json", "--name", "test",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_requires_name(self):
        result = subprocess.run(
            [
                sys.executable, "-m", "ansibleclaw.cli", "from-mcp",
                "--schema", "tools.json", "--namespace", "test",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_end_to_end_with_schema_file(self, tmp_path, sample_mcp_tools):
        schema_file = tmp_path / "tools.json"
        schema_file.write_text(json.dumps(sample_mcp_tools))

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = subprocess.run(
            [
                sys.executable, "-m", "ansibleclaw.cli", "from-mcp",
                "--schema", str(schema_file),
                "--namespace", "community",
                "--name", "github_mcp",
                "--output", str(output_dir),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "3 MCP tool(s)" in result.stdout
        assert "Collection generated" in result.stdout

        col_dir = output_dir / "community.github_mcp"
        assert (col_dir / "galaxy.yml").exists()
        assert (col_dir / "plugins" / "modules" / "create_repository.py").exists()
        assert (col_dir / "plugins" / "modules" / "list_issues.py").exists()
        assert (col_dir / "plugins" / "modules" / "search_code.py").exists()

    def test_custom_version(self, tmp_path, sample_mcp_tools):
        schema_file = tmp_path / "tools.json"
        schema_file.write_text(json.dumps(sample_mcp_tools))

        result = subprocess.run(
            [
                sys.executable, "-m", "ansibleclaw.cli", "from-mcp",
                "--schema", str(schema_file),
                "--namespace", "test", "--name", "col",
                "--output", str(tmp_path),
                "--version", "2.5.0",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

        content = (tmp_path / "test.col" / "galaxy.yml").read_text()
        assert "version: 2.5.0" in content

    def test_bad_schema_file(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json")

        result = subprocess.run(
            [
                sys.executable, "-m", "ansibleclaw.cli", "from-mcp",
                "--schema", str(bad_file),
                "--namespace", "test", "--name", "col",
                "--output", str(tmp_path),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert "Error" in result.stderr
