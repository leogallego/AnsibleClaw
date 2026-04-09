"""Tests for ansibleclaw compose (composite skill generation)."""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from ansibleclaw.cli import (
    _collection_fqcn,
    _composite_template_context,
    _parse_recipe,
    _render_composite_skill,
    _write_composite_skill_package,
    cmd_compose,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PACKAGE_DOC = {
    "ansible.builtin.package": {
        "doc": {
            "module": "ansible.builtin.package",
            "short_description": "Generic OS package manager",
            "description": ["Installs, upgrades, removes packages."],
            "options": {
                "name": {
                    "description": ["Package name."],
                    "type": "str",
                    "required": True,
                },
                "state": {
                    "description": ["Desired state."],
                    "type": "str",
                    "required": True,
                    "choices": ["present", "absent", "latest"],
                },
            },
        },
        "examples": "- name: Install nginx\n  ansible.builtin.package:\n    name: nginx\n    state: present\n",
    }
}

SAMPLE_SERVICE_DOC = {
    "ansible.builtin.service": {
        "doc": {
            "module": "ansible.builtin.service",
            "short_description": "Manage services",
            "description": ["Controls services on remote hosts."],
            "options": {
                "name": {
                    "description": ["Name of the service."],
                    "type": "str",
                    "required": True,
                },
                "state": {
                    "description": ["Service state."],
                    "type": "str",
                    "required": False,
                    "choices": ["started", "stopped", "restarted"],
                },
                "enabled": {
                    "description": ["Whether the service is enabled at boot."],
                    "type": "bool",
                    "required": False,
                },
            },
        },
        "examples": "",
    }
}

SAMPLE_FIREWALLD_DOC = {
    "ansible.posix.firewalld": {
        "doc": {
            "module": "ansible.posix.firewalld",
            "short_description": "Manage arbitrary ports/services with firewalld",
            "description": ["Manage firewalld rules."],
            "options": {
                "service": {
                    "description": ["Name of the service."],
                    "type": "str",
                    "required": False,
                },
                "permanent": {
                    "description": ["Persist across reboots."],
                    "type": "bool",
                    "required": False,
                },
                "state": {
                    "description": ["Enable or disable rule."],
                    "type": "str",
                    "required": True,
                    "choices": ["enabled", "disabled"],
                },
            },
        },
        "examples": "",
    }
}


def _mock_resolve(module_name, **kwargs):
    """Return appropriate sample doc based on module name."""
    docs = {
        "ansible.builtin.package": SAMPLE_PACKAGE_DOC,
        "ansible.builtin.service": SAMPLE_SERVICE_DOC,
        "ansible.posix.firewalld": SAMPLE_FIREWALLD_DOC,
    }
    doc = docs.get(module_name)
    if doc is None:
        from ansibleclaw.core.parser import AnsibleDocError
        raise AnsibleDocError(f"Module {module_name} not found")
    return doc, {"doc_source": "local"}


@pytest.fixture
def modules_metadata():
    """Pre-extracted metadata for three test modules."""
    from ansibleclaw.core.parser import extract_module_metadata

    result = []
    for doc in (SAMPLE_PACKAGE_DOC, SAMPLE_SERVICE_DOC, SAMPLE_FIREWALLD_DOC):
        result.append(extract_module_metadata(doc))
    return result


# ---------------------------------------------------------------------------
# Recipe parsing
# ---------------------------------------------------------------------------

class TestParseRecipe:
    def test_simple_format(self, tmp_path):
        recipe = tmp_path / "recipe.yml"
        recipe.write_text(yaml.dump({
            "name": "web-setup",
            "description": "Set up a web server",
            "modules": [
                "ansible.builtin.package",
                "ansible.builtin.service",
            ],
        }))
        result = _parse_recipe(recipe)
        assert result["name"] == "web-setup"
        assert result["description"] == "Set up a web server"
        assert len(result["modules"]) == 2
        assert result["modules"][0] == {"name": "ansible.builtin.package", "vars": None}
        assert result["modules"][1] == {"name": "ansible.builtin.service", "vars": None}

    def test_extended_format_with_vars(self, tmp_path):
        recipe = tmp_path / "recipe.yml"
        recipe.write_text(yaml.dump({
            "name": "nginx-deploy",
            "description": "Deploy Nginx",
            "modules": [
                {"name": "ansible.builtin.package", "vars": {"name": "nginx", "state": "present"}},
                {"name": "ansible.builtin.service", "vars": {"name": "nginx", "state": "started"}},
            ],
        }))
        result = _parse_recipe(recipe)
        assert len(result["modules"]) == 2
        assert result["modules"][0]["vars"] == {"name": "nginx", "state": "present"}
        assert result["modules"][1]["vars"] == {"name": "nginx", "state": "started"}

    def test_mixed_format(self, tmp_path):
        recipe = tmp_path / "recipe.yml"
        recipe.write_text(yaml.dump({
            "name": "mixed",
            "modules": [
                "ansible.builtin.package",
                {"name": "ansible.builtin.service", "vars": {"name": "nginx"}},
            ],
        }))
        result = _parse_recipe(recipe)
        assert result["modules"][0]["vars"] is None
        assert result["modules"][1]["vars"] == {"name": "nginx"}

    def test_missing_name_raises(self, tmp_path):
        recipe = tmp_path / "recipe.yml"
        recipe.write_text(yaml.dump({"modules": ["ansible.builtin.package"]}))
        with pytest.raises(ValueError, match="name"):
            _parse_recipe(recipe)

    def test_empty_modules_raises(self, tmp_path):
        recipe = tmp_path / "recipe.yml"
        recipe.write_text(yaml.dump({"name": "test", "modules": []}))
        with pytest.raises(ValueError, match="modules"):
            _parse_recipe(recipe)

    def test_not_a_dict_raises(self, tmp_path):
        recipe = tmp_path / "recipe.yml"
        recipe.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="mapping"):
            _parse_recipe(recipe)


# ---------------------------------------------------------------------------
# Composite template context
# ---------------------------------------------------------------------------

class TestCompositeTemplateContext:
    def test_basic_context(self, modules_metadata):
        ctx = _composite_template_context(
            "web-setup", "Deploy a web server", modules_metadata
        )
        assert ctx["skill_name"] == "web-setup"
        assert ctx["description"] == "Deploy a web server"
        assert len(ctx["modules"]) == 3
        assert "ansible.posix" in ctx["collection_fqcns"]
        assert "aap_configured" in ctx

    def test_builtin_only_no_collections(self):
        from ansibleclaw.core.parser import extract_module_metadata
        meta = [
            extract_module_metadata(SAMPLE_PACKAGE_DOC),
            extract_module_metadata(SAMPLE_SERVICE_DOC),
        ]
        ctx = _composite_template_context("builtins-only", "Test", meta)
        assert ctx["collection_fqcns"] == []

    def test_deduplicates_collections(self, modules_metadata):
        ctx = _composite_template_context("test", "Test", modules_metadata)
        assert len(ctx["collection_fqcns"]) == len(set(ctx["collection_fqcns"]))


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

class TestRenderCompositeSkill:
    def test_renders_skill_md(self, modules_metadata):
        result = _render_composite_skill("web-setup", "Deploy a web server", modules_metadata)
        assert "name: ansible-web-setup" in result
        assert "## Module Reference" in result
        assert "ansible.builtin.package" in result
        assert "ansible.builtin.service" in result
        assert "ansible.posix.firewalld" in result
        assert "## Safety" in result

    def test_contains_execution_mode(self, modules_metadata):
        result = _render_composite_skill("test", "Test skill", modules_metadata)
        assert "## Execution Mode" in result

    def test_contains_collection_requirements(self, modules_metadata):
        result = _render_composite_skill("test", "Test", modules_metadata)
        assert "## Collection Requirements" in result
        assert "ansible.posix" in result


# ---------------------------------------------------------------------------
# Package writer
# ---------------------------------------------------------------------------

class TestWriteCompositeSkillPackage:
    def test_creates_all_files(self, tmp_path, modules_metadata):
        output_dir = tmp_path / "ansible_web_setup"
        _write_composite_skill_package(output_dir, "web_setup", "Deploy web server", modules_metadata)

        assert (output_dir / "SKILL.md").exists()
        assert (output_dir / "scripts" / "run.sh").exists()
        assert (output_dir / "scripts" / "check.sh").exists()
        assert (output_dir / "scripts" / "publish_playbook.sh").exists()
        assert (output_dir / "scripts" / "aap_run.py").exists()
        assert (output_dir / "assets" / "playbook.yml").exists()
        assert (output_dir / "assets" / "requirements.yml").exists()

    def test_skill_md_content(self, tmp_path, modules_metadata):
        output_dir = tmp_path / "ansible_test"
        _write_composite_skill_package(output_dir, "test", "A test skill", modules_metadata)

        content = (output_dir / "SKILL.md").read_text()
        assert "name: ansible-test" in content
        assert "composite skill" in content.lower()
        assert "ansible.builtin.package" in content

    def test_playbook_content(self, tmp_path, modules_metadata):
        output_dir = tmp_path / "ansible_test"
        _write_composite_skill_package(output_dir, "test", "A test skill", modules_metadata)

        content = (output_dir / "assets" / "playbook.yml").read_text()
        assert "ansible.builtin.package" in content
        assert "ansible.builtin.service" in content
        assert "ansible.posix.firewalld" in content
        assert "ansible.posix" in content

    def test_requirements_content(self, tmp_path, modules_metadata):
        output_dir = tmp_path / "ansible_test"
        _write_composite_skill_package(output_dir, "test", "Test", modules_metadata)

        content = (output_dir / "assets" / "requirements.yml").read_text()
        assert "ansible.posix" in content

    def test_scripts_are_executable(self, tmp_path, modules_metadata):
        output_dir = tmp_path / "ansible_test"
        _write_composite_skill_package(output_dir, "test", "Test", modules_metadata)

        for script in ("run.sh", "check.sh", "publish_playbook.sh", "aap_run.py"):
            path = output_dir / "scripts" / script
            assert path.stat().st_mode & 0o111, f"{script} should be executable"

    def test_no_requirements_for_builtins_only(self, tmp_path):
        from ansibleclaw.core.parser import extract_module_metadata
        meta = [
            extract_module_metadata(SAMPLE_PACKAGE_DOC),
            extract_module_metadata(SAMPLE_SERVICE_DOC),
        ]
        output_dir = tmp_path / "ansible_test"
        _write_composite_skill_package(output_dir, "test", "Test", meta)

        assert not (output_dir / "assets" / "requirements.yml").exists()

    def test_aap_run_is_playbook_oriented(self, tmp_path, modules_metadata):
        output_dir = tmp_path / "ansible_test"
        _write_composite_skill_package(output_dir, "test", "Test", modules_metadata)

        content = (output_dir / "scripts" / "aap_run.py").read_text()
        assert "SKILL_NAME" in content
        assert "cmd_launch" in content
        assert "cmd_create_jt" in content
        assert "cmd_adhoc" not in content


# ---------------------------------------------------------------------------
# CLI cmd_compose
# ---------------------------------------------------------------------------

class TestCmdCompose:
    def test_compose_with_modules_flag(self, tmp_path):
        with patch("ansibleclaw.cli.resolve_module_doc", side_effect=_mock_resolve):
            args = argparse.Namespace(
                name="web-setup",
                description="Deploy web server",
                modules="ansible.builtin.package,ansible.builtin.service",
                file=None,
                install=None,
                output=str(tmp_path),
                zip=False,
                auto_install=False,
                collection_version=None,
            )
            cmd_compose(args)

        skill_dir = tmp_path / "ansible_web_setup"
        assert (skill_dir / "SKILL.md").exists()
        content = (skill_dir / "SKILL.md").read_text()
        assert "ansible.builtin.package" in content
        assert "ansible.builtin.service" in content

    def test_compose_with_recipe_file(self, tmp_path):
        recipe = tmp_path / "recipe.yml"
        recipe.write_text(yaml.dump({
            "name": "nginx-stack",
            "description": "Deploy Nginx",
            "modules": [
                "ansible.builtin.package",
                "ansible.builtin.service",
            ],
        }))

        with patch("ansibleclaw.cli.resolve_module_doc", side_effect=_mock_resolve):
            args = argparse.Namespace(
                name=None,
                description=None,
                modules=None,
                file=str(recipe),
                install=None,
                output=str(tmp_path),
                zip=False,
                auto_install=False,
                collection_version=None,
            )
            cmd_compose(args)

        skill_dir = tmp_path / "ansible_nginx_stack"
        assert (skill_dir / "SKILL.md").exists()
        assert (skill_dir / "assets" / "playbook.yml").exists()

    def test_compose_recipe_with_vars(self, tmp_path):
        recipe = tmp_path / "recipe.yml"
        recipe.write_text(yaml.dump({
            "name": "prefilled",
            "modules": [
                {"name": "ansible.builtin.package", "vars": {"name": "nginx", "state": "present"}},
            ],
        }))

        with patch("ansibleclaw.cli.resolve_module_doc", side_effect=_mock_resolve):
            args = argparse.Namespace(
                name=None,
                description=None,
                modules=None,
                file=str(recipe),
                install=None,
                output=str(tmp_path),
                zip=False,
                auto_install=False,
                collection_version=None,
            )
            cmd_compose(args)

        playbook = (tmp_path / "ansible_prefilled" / "assets" / "playbook.yml").read_text()
        assert "nginx" in playbook

    def test_compose_requires_name_with_modules(self, tmp_path):
        with pytest.raises(SystemExit):
            args = argparse.Namespace(
                name=None,
                description=None,
                modules="ansible.builtin.package",
                file=None,
                install=None,
                output=str(tmp_path),
                zip=False,
                auto_install=False,
                collection_version=None,
            )
            cmd_compose(args)

    def test_compose_requires_modules_or_file(self, tmp_path):
        with pytest.raises(SystemExit):
            args = argparse.Namespace(
                name="test",
                description=None,
                modules=None,
                file=None,
                install=None,
                output=str(tmp_path),
                zip=False,
                auto_install=False,
                collection_version=None,
            )
            cmd_compose(args)

    def test_compose_install_flag(self, tmp_path):
        with patch("ansibleclaw.cli.resolve_module_doc", side_effect=_mock_resolve), \
             patch("ansibleclaw.cli.INSTALL_PATHS", {"testplatform": tmp_path}):
            args = argparse.Namespace(
                name="test",
                description="Test",
                modules="ansible.builtin.package,ansible.builtin.service",
                file=None,
                install="testplatform",
                output=None,
                zip=False,
                auto_install=False,
                collection_version=None,
            )
            cmd_compose(args)

        assert (tmp_path / "ansible_test" / "SKILL.md").exists()

    def test_compose_with_cross_collection_modules(self, tmp_path):
        with patch("ansibleclaw.cli.resolve_module_doc", side_effect=_mock_resolve):
            args = argparse.Namespace(
                name="cross-collection",
                description="Cross-collection test",
                modules="ansible.builtin.package,ansible.builtin.service,ansible.posix.firewalld",
                file=None,
                install=None,
                output=str(tmp_path),
                zip=False,
                auto_install=False,
                collection_version=None,
            )
            cmd_compose(args)

        skill_dir = tmp_path / "ansible_cross_collection"
        content = (skill_dir / "SKILL.md").read_text()
        assert "ansible.posix" in content
        assert "Collection Requirements" in content

        req = (skill_dir / "assets" / "requirements.yml").read_text()
        assert "ansible.posix" in req
