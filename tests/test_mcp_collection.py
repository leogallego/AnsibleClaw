"""Tests for MCP collection generator."""

import py_compile

import yaml
import pytest

from ansibleclaw.core.mcp_collection import write_mcp_collection


class TestWriteMcpCollection:

    def test_creates_directory_structure(self, tmp_path, sample_mcp_tools):
        output = tmp_path / "test_ns.test_col"
        write_mcp_collection(output, "test_ns", "test_col", "1.0.0", sample_mcp_tools)

        assert (output / "galaxy.yml").exists()
        assert (output / "README.md").exists()
        assert (output / "LICENSE").exists()
        assert (output / "meta" / "runtime.yml").exists()
        assert (output / "plugins" / "modules" / "__init__.py").exists()
        assert (output / "plugins" / "action" / "_mcp_proxy.py").exists()

    def test_ansible_creator_scaffolding_present(self, tmp_path, sample_mcp_tools):
        output = tmp_path / "test_ns.test_col"
        write_mcp_collection(output, "test_ns", "test_col", "1.0.0", sample_mcp_tools)

        assert (output / "tox-ansible.ini").exists()
        assert (output / "pyproject.toml").exists()
        assert (output / "CHANGELOG.rst").exists()
        assert (output / "changelogs" / "config.yaml").exists()
        assert (output / ".pre-commit-config.yaml").exists()
        assert (output / "tests" / "unit").exists()
        assert (output / "tests" / "integration").exists()

    def test_sample_files_removed(self, tmp_path, sample_mcp_tools):
        output = tmp_path / "test_ns.test_col"
        write_mcp_collection(output, "test_ns", "test_col", "1.0.0", sample_mcp_tools)

        assert not (output / "plugins" / "modules" / "sample_module.py").exists()
        assert not (output / "plugins" / "modules" / "sample_action.py").exists()
        assert not (output / "plugins" / "action" / "sample_action.py").exists()
        assert not (output / "plugins" / "filter" / "sample_filter.py").exists()
        assert not (output / "plugins" / "lookup" / "sample_lookup.py").exists()
        assert not (output / "plugins" / "test" / "sample_test.py").exists()
        assert not (output / "roles" / "run").exists()

    def test_generates_module_per_tool(self, tmp_path, sample_mcp_tools):
        output = tmp_path / "test_ns.test_col"
        write_mcp_collection(output, "test_ns", "test_col", "1.0.0", sample_mcp_tools)

        modules_dir = output / "plugins" / "modules"
        assert (modules_dir / "create_repository.py").exists()
        assert (modules_dir / "list_issues.py").exists()
        assert (modules_dir / "search_code.py").exists()

    def test_module_files_are_valid_python(self, tmp_path, sample_mcp_tools):
        output = tmp_path / "test_ns.test_col"
        write_mcp_collection(output, "test_ns", "test_col", "1.0.0", sample_mcp_tools)

        modules_dir = output / "plugins" / "modules"
        for py_file in modules_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            py_compile.compile(str(py_file), doraise=True)

    def test_action_plugin_is_valid_python(self, tmp_path, sample_mcp_tools):
        output = tmp_path / "test_ns.test_col"
        write_mcp_collection(output, "test_ns", "test_col", "1.0.0", sample_mcp_tools)

        proxy = output / "plugins" / "action" / "_mcp_proxy.py"
        py_compile.compile(str(proxy), doraise=True)

    def test_galaxy_yml_content(self, tmp_path, sample_mcp_tools):
        output = tmp_path / "test_ns.test_col"
        write_mcp_collection(output, "test_ns", "test_col", "2.0.0", sample_mcp_tools)

        data = yaml.safe_load((output / "galaxy.yml").read_text())
        assert data["namespace"] == "test_ns"
        assert data["name"] == "test_col"
        assert data["version"] == "2.0.0"
        assert data["dependencies"] == {"ansible.mcp": "*"}
        assert "mcp" in data["tags"]

    def test_runtime_yml_routes_modules(self, tmp_path, sample_mcp_tools):
        output = tmp_path / "test_ns.test_col"
        write_mcp_collection(output, "test_ns", "test_col", "1.0.0", sample_mcp_tools)

        data = yaml.safe_load((output / "meta" / "runtime.yml").read_text())
        action_routing = data["plugin_routing"]["action"]
        assert "create_repository" in action_routing
        assert "list_issues" in action_routing
        assert "search_code" in action_routing
        assert action_routing["create_repository"]["redirect"] == "test_ns.test_col._mcp_proxy"

    def test_readme_lists_modules(self, tmp_path, sample_mcp_tools):
        output = tmp_path / "test_ns.test_col"
        write_mcp_collection(output, "test_ns", "test_col", "1.0.0", sample_mcp_tools)

        content = (output / "README.md").read_text()
        assert "create_repository" in content
        assert "list_issues" in content
        assert "search_code" in content
        assert "test_ns.test_col" in content

    def test_module_contains_documentation(self, tmp_path, sample_mcp_tools):
        output = tmp_path / "test_ns.test_col"
        write_mcp_collection(output, "test_ns", "test_col", "1.0.0", sample_mcp_tools)

        content = (output / "plugins" / "modules" / "create_repository.py").read_text()
        assert "DOCUMENTATION" in content
        assert "EXAMPLES" in content
        assert "RETURN" in content
        assert "Create a new GitHub repository" in content
        assert "MCP_TOOL_NAME" in content
        assert '"create_repository"' in content

    def test_module_argument_spec(self, tmp_path, sample_mcp_tools):
        output = tmp_path / "test_ns.test_col"
        write_mcp_collection(output, "test_ns", "test_col", "1.0.0", sample_mcp_tools)

        content = (output / "plugins" / "modules" / "create_repository.py").read_text()
        assert 'name=dict(' in content
        assert 'required=True' in content
        assert 'type="str"' in content

    def test_read_only_module_not_changed(self, tmp_path, sample_mcp_tools):
        output = tmp_path / "test_ns.test_col"
        write_mcp_collection(output, "test_ns", "test_col", "1.0.0", sample_mcp_tools)

        content = (output / "plugins" / "modules" / "list_issues.py").read_text()
        assert "changed=False" in content

    def test_mutating_module_changed(self, tmp_path, sample_mcp_tools):
        output = tmp_path / "test_ns.test_col"
        write_mcp_collection(output, "test_ns", "test_col", "1.0.0", sample_mcp_tools)

        content = (output / "plugins" / "modules" / "create_repository.py").read_text()
        assert "changed=True" in content

    def test_returns_module_metadata(self, tmp_path, sample_mcp_tools):
        output = tmp_path / "test_ns.test_col"
        modules = write_mcp_collection(
            output, "test_ns", "test_col", "1.0.0", sample_mcp_tools,
        )
        assert len(modules) == 3
        names = {m["module_name"] for m in modules}
        assert names == {"create_repository", "list_issues", "search_code"}

    def test_idempotent_reruns(self, tmp_path, sample_mcp_tools):
        output = tmp_path / "test_ns.test_col"
        write_mcp_collection(output, "test_ns", "test_col", "1.0.0", sample_mcp_tools)
        write_mcp_collection(output, "test_ns", "test_col", "1.0.0", sample_mcp_tools)

        modules_dir = output / "plugins" / "modules"
        py_files = [f for f in modules_dir.glob("*.py") if f.name != "__init__.py"]
        assert len(py_files) == 3
