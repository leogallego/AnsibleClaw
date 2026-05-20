"""Shared test fixtures for AnsibleClaw."""

import json

import pytest

SAMPLE_MODULE_DOC = {
    "ansible.builtin.package": {
        "doc": {
            "module": "ansible.builtin.package",
            "short_description": "Generic OS package manager",
            "description": ["Installs, upgrades, removes packages using the OS package manager."],
            "options": {
                "name": {
                    "description": [
                        "Package name, or package specifier with version."
                    ],
                    "type": "str",
                    "required": True,
                },
                "state": {
                    "description": [
                        "Whether to install (present), or remove (absent) a package."
                    ],
                    "type": "str",
                    "required": True,
                    "choices": ["present", "absent", "latest"],
                },
                "use": {
                    "description": [
                        "The required package manager module to use."
                    ],
                    "type": "str",
                    "required": False,
                    "default": "auto",
                    "choices": ["auto", "apt", "dnf", "yum"],
                },
            },
        },
        "examples": (
            "- name: Install ntpdate\n"
            "  ansible.builtin.package:\n"
            "    name: ntpdate\n"
            "    state: present\n"
        ),
    }
}

SAMPLE_MODULE_LIST = {
    "ansible.builtin.package": "Generic OS package manager",
    "ansible.builtin.apt": "Manages apt-packages",
    "ansible.builtin.yum": "Manages packages with the yum package manager",
    "community.general.redis": "Various redis commands, replica and flush",
}


@pytest.fixture
def sample_module_doc():
    return SAMPLE_MODULE_DOC


@pytest.fixture
def sample_module_doc_json():
    return json.dumps(SAMPLE_MODULE_DOC)


@pytest.fixture
def sample_module_list():
    return SAMPLE_MODULE_LIST


@pytest.fixture
def sample_module_list_json():
    return json.dumps(SAMPLE_MODULE_LIST)


SAMPLE_MCP_TOOLS = [
    {
        "name": "create_repository",
        "description": "Create a new GitHub repository",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Repository name"},
                "private": {"type": "boolean", "description": "Whether repo should be private"},
                "description": {"type": "string", "description": "Repository description"},
                "organization": {"type": "string", "description": "Organization to create in"},
                "autoInit": {"type": "boolean", "description": "Initialize with README"},
            },
            "required": ["name"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    {
        "name": "list_issues",
        "description": "List issues in a GitHub repository",
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repository owner"},
                "repo": {"type": "string", "description": "Repository name"},
                "state": {
                    "type": "string",
                    "description": "Filter by state",
                    "enum": ["OPEN", "CLOSED"],
                },
                "perPage": {
                    "type": "integer",
                    "description": "Results per page",
                    "default": 30,
                },
            },
            "required": ["owner", "repo"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "search-code",
        "description": "Search for code across repositories",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
]


SAMPLE_MCP_TOOLS_RESPONSE = {
    "tools": SAMPLE_MCP_TOOLS,
}


@pytest.fixture
def sample_mcp_tools():
    return SAMPLE_MCP_TOOLS


@pytest.fixture
def sample_mcp_tools_json(tmp_path):
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(SAMPLE_MCP_TOOLS))
    return path


@pytest.fixture
def sample_mcp_tools_response_json(tmp_path):
    path = tmp_path / "tools_response.json"
    path.write_text(json.dumps(SAMPLE_MCP_TOOLS_RESPONSE))
    return path
