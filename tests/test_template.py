"""Tests for skill template rendering."""

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

from ansibleclaw.config import TEMPLATE_DIR, TEMPLATE_PATH

# Default AAP context for CLI-mode tests (no AAP configured)
_CLI_CTX = {
    "aap_configured": False,
    "aap_url": "",
    "aap_verify_ssl": "true",
    "aap_inventory": "",
    "aap_credential": "",
    "aap_project": "",
    "aap_ee": "",
    "aap_organization": "Default",
    "aap_scm_url": "",
}

# AAP context for AAP-mode tests
_AAP_CTX = {
    "aap_configured": True,
    "aap_url": "https://aap.example.com",
    "aap_verify_ssl": "false",
    "aap_inventory": "Demo Inventory",
    "aap_credential": "Machine Cred",
    "aap_project": "AnsibleClaw",
    "aap_ee": "Default execution environment",
    "aap_organization": "Default",
    "aap_scm_url": "",
}


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
        ctx = {**_CLI_CTX, **kwargs}
        return template.render(**ctx)

    return _render


@pytest.fixture
def render_aap_mode(render_template):
    """Render the skill template with AAP configured."""

    def _render(**kwargs):
        ctx = {**_AAP_CTX, **kwargs}
        return render_template(**ctx)

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

    def test_cli_mode_has_inventory_section(self, render_template):
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx",
        )
        assert "Inventory" in result
        assert "-i /path/to/inventory.yml" in result
        assert "ANSIBLE_INVENTORY" in result

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
        assert "idempotent" in result

    def test_cli_mode_has_json_output(self, render_template):
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx",
        )
        assert "ANSIBLE_STDOUT_CALLBACK=json" in result

    def test_cli_mode_section_heading(self, render_template):
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx",
        )
        assert "## How to Execute (CLI)" in result

    def test_cli_mode_shows_cli_mode_active(self, render_template):
        result = render_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx",
        )
        assert "CLI mode is active" in result
        assert "AAP mode is active" not in result

    def test_collection_requirement_cli_mode(self, render_template):
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
        assert "ansible-galaxy collection install community.general" in result

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


class TestSkillTemplateAAPMode:
    """Tests for the AAP-configured mode of the skill template."""

    def test_aap_mode_active_message(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "AAP mode is active" in result
        assert "CLI mode is active" not in result

    def test_aap_mode_references_publish_script(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "publish_playbook.sh" in result

    def test_baked_aap_url_shown(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "https://aap.example.com" in result

    def test_baked_inventory_shown(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "Demo Inventory" in result

    def test_baked_credential_shown(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "Machine Cred" in result

    def test_aap_section_heading(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "## How to Execute (AAP)" in result

    def test_aap_adhoc_marked_diagnostics_only(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "Optional: ad-hoc" in result
        assert "diagnostics only" in result

    def test_aap_quick_start_prefers_jt_over_adhoc(self, render_aap_mode):
        """Quick Start should keep JT guidance and avoid ad-hoc commands."""
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        qs = result.find("### Quick Start")
        end = result.find("## When to Use", qs)
        assert qs != -1 and end != -1
        chunk = result[qs:end]
        assert "#### Optional: ad-hoc" in chunk
        assert "aap_run.py create-jt" in chunk
        assert "aap_run.py adhoc" not in chunk

    def test_how_to_execute_jt_before_adhoc(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        sec = result.find("## How to Execute (AAP)")
        jt = result.find("### Job Templates", sec)
        ad = result.find("### Optional: ad-hoc", sec)
        assert jt != -1 and ad != -1 and jt < ad

    def test_package_module_warns_about_adhoc_restrictions(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "many Controllers reject ad-hoc usage of `package`" in result

    def test_aap_launch_example(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "aap_run.py launch" in result

    def test_aap_create_jt_example(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "aap_run.py create-jt" in result

    def test_aap_scm_url_hint_rendered_when_set(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
            aap_scm_url="https://git.example.com/org/repo.git",
        )
        assert "https://git.example.com/org/repo.git" in result
        assert "SCM URL hint" in result

    def test_aap_status_example(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx",
        )
        assert "aap_run.py status" in result

    def test_imperative_language(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "You MUST use" in result
        assert "Do NOT" in result

    def test_no_cli_section_in_aap_mode(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx state=present",
        )
        assert "## How to Execute (CLI)" not in result

    def test_collection_requirement_aap_mode(self, render_aap_mode):
        result = render_aap_mode(
            module_name="community.general.redis",
            skill_name="redis",
            short_description="Redis commands",
            params=[],
            examples="",
            example_args="name=mykey",
            collection_fqcn="community.general",
        )
        assert "## Collection Requirement" in result
        assert "Execution Environments" in result
        assert "ansible-galaxy collection install" not in result

    def test_token_not_baked(self, render_aap_mode):
        result = render_aap_mode(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            params=[],
            examples="",
            example_args="name=nginx",
        )
        assert "AAP_CONTROLLER_TOKEN" in result
        assert "required only for Controller API calls" in result


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
            ctx = {**_CLI_CTX, **kwargs}
            return template.render(**ctx)

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

    def test_contains_create_jt_subcommand(self, render_aap_template):
        result = render_aap_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
        )
        assert "def cmd_create_jt" in result
        assert "create-jt" in result

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

    def test_baked_defaults_present(self, render_aap_template):
        result = render_aap_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            **_AAP_CTX,
        )
        assert '_BAKED_URL = "https://aap.example.com"' in result
        assert '_BAKED_INVENTORY = "Demo Inventory"' in result
        assert '_BAKED_CREDENTIAL = "Machine Cred"' in result
        assert '_BAKED_PROJECT = "AnsibleClaw"' in result

    def test_no_token_baked(self, render_aap_template):
        result = render_aap_template(
            module_name="ansible.builtin.package",
            skill_name="package",
            short_description="Test",
            **_AAP_CTX,
        )
        assert "_BAKED_TOKEN" not in result
