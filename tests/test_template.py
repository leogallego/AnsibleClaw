"""Tests for skill template rendering."""

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

from ansibleclaw.config import TEMPLATE_DIR, TEMPLATE_PATH


@pytest.fixture
def render_template():
    """Helper to render the skill template with given context."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(TEMPLATE_PATH.name)

    def _render(**kwargs):
        return template.render(**kwargs)

    return _render


class TestSkillTemplate:
    def test_renders_frontmatter(self, render_template):
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Generic OS package manager",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "name: ansible-package" in result
        assert "Generic OS package manager" in result

    def test_renders_parameters_table(self, render_template):
        params = [
            {
                "name": "name",
                "type": "str",
                "required": True,
                "default": None,
                "choices": None,
                "description": "Package name",
                "aliases": [],
            },
            {
                "name": "state",
                "type": "str",
                "required": True,
                "default": None,
                "choices": ["present", "absent"],
                "description": "Whether to install or remove",
                "aliases": [],
            },
        ]
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Generic OS package manager",
            params=params,
            examples="",
            example_args="name=nginx state=present",
        )
        assert "| `name` |" in result
        assert "| `state` |" in result
        assert "| yes |" in result

    def test_renders_choices_section(self, render_template):
        params = [
            {
                "name": "state",
                "type": "str",
                "required": True,
                "default": None,
                "choices": ["present", "absent", "latest"],
                "description": "Desired state",
                "aliases": [],
            },
        ]
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=params,
            examples="",
            example_args="state=present",
        )
        assert "present, absent, latest" in result

    def test_renders_examples_section(self, render_template):
        examples_yaml = "- name: Install nginx\n  ansible.builtin.package:\n    name: nginx\n"
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples=examples_yaml,
            example_args="name=nginx",
        )
        assert "Examples from Ansible Documentation" in result
        assert "Install nginx" in result

    def test_no_examples_section_when_empty(self, render_template):
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx",
        )
        assert "Examples from Ansible Documentation" not in result

    def test_renders_inventory_section(self, render_template):
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx",
        )
        assert "## Inventory" in result
        assert "-i /path/to/inventory.yml" in result
        assert "ANSIBLE_INVENTORY" in result
        assert "/etc/ansible/hosts" in result

    def test_renders_safety_section(self, render_template):
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx",
        )
        assert "## Safety" in result
        assert "--check --diff" in result
        assert "idempotent" in result

    def test_renders_json_output_section(self, render_template):
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx",
        )
        assert "ANSIBLE_STDOUT_CALLBACK=json" in result

    def test_renders_aap_section(self, render_template):
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "## Production Execution (AAP)" in result
        assert "AAP_CONTROLLER_URL" in result
        assert "AAP_CONTROLLER_TOKEN" in result
        assert "aap_run.py" in result

    def test_aap_section_contains_adhoc_example(self, render_template):
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "aap_run.py adhoc" in result
        assert "name=nginx state=present" in result

    def test_aap_section_contains_job_template_launch(self, render_template):
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "aap_run.py launch" in result

    def test_aap_section_contains_status_check(self, render_template):
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx",
        )
        assert "aap_run.py status" in result

    def test_cli_section_renamed(self, render_template):
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx",
        )
        assert "## Local Execution (CLI)" in result

    def test_aap_module_name_interpolated(self, render_template):
        result = render_template(
            module_name="community.general.redis",
            skill_name="redis",
            short_description="Redis commands",
            params=[],
            examples="",
            example_args="name=mykey",
            collection_fqcn="community.general",
        )
        assert "community.general" in result
        assert "aap_run.py adhoc" in result

    def test_collection_requirement_for_non_builtin(self, render_template):
        result = render_template(
            module_name="community.general.redis",
            skill_name="redis",
            short_description="Redis commands",
            params=[],
            examples="",
            example_args="name=mykey",
            collection_fqcn="community.general",
        )
        assert "## Collection Requirement" in result
        assert "community.general" in result
        assert "ansible-galaxy collection install community.general" in result
        assert "execution-environment.yml" in result
        assert "ansible-builder" in result

    def test_no_collection_requirement_for_builtin(self, render_template):
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Generic OS package manager",
            params=[],
            examples="",
            example_args="name=nginx",
            collection_fqcn="",
        )
        assert "## Collection Requirement" not in result

    def test_ansible_posix_shows_collection_requirement(self, render_template):
        result = render_template(
            module_name="ansible.posix.acl",
            skill_name="acl",
            short_description="Set and retrieve file ACL information",
            params=[],
            examples="",
            example_args="path=/etc/foo",
            collection_fqcn="ansible.posix",
        )
        assert "## Collection Requirement" in result
        assert "ansible.posix" in result

    def test_galaxy_doc_warning_shown(self, render_template):
        result = render_template(
            module_name="community.general.redis",
            skill_name="redis",
            short_description="Redis commands",
            params=[],
            examples="",
            example_args="name=mykey",
            collection_fqcn="community.general",
            doc_warning="Documentation sourced from Galaxy (community.general 9.2.0). Your installed version may differ.",
        )
        assert "Documentation sourced from Galaxy" in result


class TestAAPRunTemplate:
    """Tests for the aap_run.py.j2 template."""

    @pytest.fixture
    def render_aap_template(self):
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env.get_template("aap_run.py.j2")

        def _render(**kwargs):
            return template.render(**kwargs)

        return _render

    def test_renders_module_name(self, render_aap_template):
        result = render_aap_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Generic OS package manager",
        )
        assert 'MODULE = "ansible.builtin.package"' in result

    def test_contains_adhoc_subcommand(self, render_aap_template):
        result = render_aap_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
        )
        assert "def cmd_adhoc" in result
        assert "ad_hoc_commands" in result

    def test_contains_launch_subcommand(self, render_aap_template):
        result = render_aap_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
        )
        assert "def cmd_launch" in result
        assert "job_templates" in result

    def test_contains_status_subcommand(self, render_aap_template):
        result = render_aap_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
        )
        assert "def cmd_status" in result

    def test_uses_stdlib_only(self, render_aap_template):
        result = render_aap_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
        )
        assert "import urllib.request" in result
        assert "import json" in result
        assert "import requests" not in result

    def test_reads_env_vars(self, render_aap_template):
        result = render_aap_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
        )
        assert "AAP_CONTROLLER_URL" in result
        assert "AAP_CONTROLLER_TOKEN" in result
        assert "AAP_VERIFY_SSL" in result
