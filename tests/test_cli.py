"""Tests for ansibleclaw.cli."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ansibleclaw.cli import (
    _build_example_args,
    _collection_fqcn,
    _extract_example_values,
    _module_to_skill_name,
)


class TestModuleToSkillName:
    def test_builtin_module(self):
        assert _module_to_skill_name("ansible.builtin.package") == "ansible_package"

    def test_community_module(self):
        assert _module_to_skill_name("community.general.redis") == "ansible_general_redis"

    def test_deeply_nested_module(self):
        assert _module_to_skill_name("community.docker.docker_container") == "ansible_docker_docker_container"

    def test_ansible_posix_not_treated_as_builtin(self):
        assert _module_to_skill_name("ansible.posix.acl") == "ansible_posix_acl"

    def test_no_collision_across_collections(self):
        builtin = _module_to_skill_name("ansible.builtin.copy")
        community = _module_to_skill_name("community.general.copy")
        assert builtin != community
        assert builtin == "ansible_copy"
        assert community == "ansible_general_copy"


class TestCollectionFqcn:
    def test_builtin_returns_empty(self):
        assert _collection_fqcn("ansible.builtin.package") == ""

    def test_community_collection(self):
        assert _collection_fqcn("community.general.redis") == "community.general"

    def test_ansible_posix(self):
        assert _collection_fqcn("ansible.posix.acl") == "ansible.posix"

    def test_short_name_returns_empty(self):
        assert _collection_fqcn("package") == ""


class TestExtractExampleValues:
    def test_extracts_from_yaml(self):
        yaml = (
            "- name: Install ntpdate\n"
            "  ansible.builtin.package:\n"
            "    name: ntpdate\n"
            "    state: present\n"
        )
        values = _extract_example_values(yaml)
        assert values["name"] == "ntpdate"
        assert values["state"] == "present"

    def test_skips_comments_and_task_names(self):
        yaml = (
            "# This is a comment\n"
            "- name: Some task\n"
            "  ansible.builtin.package:\n"
            "    name: nginx\n"
        )
        values = _extract_example_values(yaml)
        assert "name" in values
        assert values["name"] == "nginx"

    def test_first_value_wins(self):
        yaml = (
            "    name: first\n"
            "    name: second\n"
        )
        values = _extract_example_values(yaml)
        assert values["name"] == "first"

    def test_empty_string(self):
        assert _extract_example_values("") == {}


class TestBuildExampleArgs:
    def test_required_params_with_concrete_values(self):
        params = [
            {"name": "name", "required": True, "choices": None, "type": "str", "default": None},
            {"name": "state", "required": True, "choices": ["present", "absent"], "type": "str", "default": None},
        ]
        examples = "    name: nginx\n    state: present\n"
        result = _build_example_args(params, examples)
        assert "name=nginx" in result
        assert "state=present" in result

    def test_fallback_to_choices(self):
        params = [
            {"name": "state", "required": True, "choices": ["present", "absent"], "type": "str", "default": None},
        ]
        result = _build_example_args(params, "")
        assert result == "state=present"

    def test_fallback_to_placeholder(self):
        params = [
            {"name": "src", "required": True, "choices": None, "type": "str", "default": None},
        ]
        result = _build_example_args(params, "")
        assert result == "src=<src>"


class TestCmdGenerate:
    def _mock_resolve(self, sample_module_doc):
        """Return a mock for resolve_module_doc returning local docs."""
        return patch(
            "ansibleclaw.cli.resolve_module_doc",
            return_value=(sample_module_doc, {"doc_source": "local"}),
        )

    def test_end_to_end(self, tmp_path, sample_module_doc):
        """Full generate pipeline with mocked resolve_module_doc."""
        from ansibleclaw.cli import cmd_generate
        import argparse

        with self._mock_resolve(sample_module_doc):
            args = argparse.Namespace(
                module="ansible.builtin.package",
                install=None,
                output=str(tmp_path),
                auto_install=False,
                collection_version=None,
            )
            cmd_generate(args)

        skill_dir = tmp_path / "ansible_package"
        skill_file = skill_dir / "SKILL.md"
        assert skill_file.exists()

        content = skill_file.read_text()
        assert "name: ansible-package" in content
        assert "ansible.builtin.package" in content
        assert "name=ntpdate" in content
        assert "state=present" in content
        assert "## Parameters" in content
        assert "## Inventory" in content

    def test_generates_aap_run_script(self, tmp_path, sample_module_doc):
        """Generate pipeline produces scripts/aap_run.py."""
        from ansibleclaw.cli import cmd_generate
        import argparse

        with self._mock_resolve(sample_module_doc):
            args = argparse.Namespace(
                module="ansible.builtin.package",
                install=None,
                output=str(tmp_path),
                auto_install=False,
                collection_version=None,
            )
            cmd_generate(args)

        skill_dir = tmp_path / "ansible_package"
        aap_script = skill_dir / "scripts" / "aap_run.py"
        assert aap_script.exists()

        content = aap_script.read_text()
        assert 'MODULE = "ansible.builtin.package"' in content
        assert "ad_hoc_commands" in content
        assert "job_templates" in content
        assert aap_script.stat().st_mode & 0o111, "aap_run.py should be executable"

    def test_skill_md_has_aap_section(self, tmp_path, sample_module_doc):
        """Generated SKILL.md includes the AAP production execution section."""
        from ansibleclaw.cli import cmd_generate
        import argparse

        with self._mock_resolve(sample_module_doc):
            args = argparse.Namespace(
                module="ansible.builtin.package",
                install=None,
                output=str(tmp_path),
                auto_install=False,
                collection_version=None,
            )
            cmd_generate(args)

        skill_dir = tmp_path / "ansible_package"
        content = (skill_dir / "SKILL.md").read_text()
        assert "## Production Execution (AAP)" in content
        assert "## Local Execution (CLI)" in content
        assert "AAP_CONTROLLER_URL" in content

    def test_builtin_no_collection_requirement(self, tmp_path, sample_module_doc):
        """Builtin modules should not have a Collection Requirement section."""
        from ansibleclaw.cli import cmd_generate
        import argparse

        with self._mock_resolve(sample_module_doc):
            args = argparse.Namespace(
                module="ansible.builtin.package",
                install=None,
                output=str(tmp_path),
                auto_install=False,
                collection_version=None,
            )
            cmd_generate(args)

        content = (tmp_path / "ansible_package" / "SKILL.md").read_text()
        assert "## Collection Requirement" not in content

    def test_install_flag(self, tmp_path, sample_module_doc):
        """Generate with --install writes to the platform directory."""
        from ansibleclaw.cli import cmd_generate
        import argparse

        with self._mock_resolve(sample_module_doc), \
             patch("ansibleclaw.cli.INSTALL_PATHS", {"testplatform": tmp_path}):
            args = argparse.Namespace(
                module="ansible.builtin.package",
                install="testplatform",
                output=None,
                auto_install=False,
                collection_version=None,
            )
            cmd_generate(args)

        skill_file = tmp_path / "ansible_package" / "SKILL.md"
        assert skill_file.exists()
