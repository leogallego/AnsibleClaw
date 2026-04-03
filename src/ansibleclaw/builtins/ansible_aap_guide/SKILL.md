---
name: ansible-aap-guide
description: >-
  Guide for using Ansible Automation Platform (AAP) as the production execution backend.
  Use when AAP_CONTROLLER_URL is set and you need to run Ansible modules through governed,
  auditable execution instead of direct CLI commands.
---

# Ansible Automation Platform (AAP) Guide

Route Ansible execution through AAP Controller for enterprise governance, RBAC, audit logging,
and centralized credential management. Compatible with both AWX (free upstream) and
Red Hat AAP Controller (commercial) -- they share the same REST API.

## When to Use AAP Mode

Use AAP mode when:

- **Production environments** -- all changes should be tracked and auditable
- **RBAC is required** -- execution must respect role-based access controls
- **Credentials are centralized** -- SSH keys and secrets live in AAP, not on the agent machine
- **Approval workflows** -- changes may require human approval before execution
- **Compliance** -- your organization requires all automation to flow through AAP

Use direct CLI mode (the default) when:

- **Development/testing** -- rapid iteration on a local or lab environment
- **AAP is not available** -- no controller configured
- **Local-only tasks** -- targeting localhost with no governance requirements

## How to Detect Which Mode to Use

Check for the `AAP_CONTROLLER_URL` environment variable:

When AAP is configured, generated skills ship with baked AAP defaults (URL, inventory, credential, project). Check the **"Execution Mode -- READ THIS FIRST"** section at the top of each skill's SKILL.md:

- **AAP mode**: The skill will say "AAP mode is active" with pre-filled `aap_run.py` commands
- **CLI mode**: The skill will say "CLI mode is active" with `ansible` CLI commands

If AAP mode is active, you MUST use `scripts/aap_run.py` for all execution. The only required environment variable is `AAP_CONTROLLER_TOKEN` -- all other AAP settings are baked into the generated scripts.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AAP_CONTROLLER_URL` | yes | Base URL (e.g. `https://aap.example.com`) |
| `AAP_CONTROLLER_TOKEN` | yes | OAuth2 bearer token from AAP |
| `AAP_VERIFY_SSL` | no | Set to `false` for self-signed certs (default: `true`) |
| `AAP_DEFAULT_INVENTORY` | no | Default inventory name or ID for ad-hoc commands |
| `AAP_DEFAULT_CREDENTIAL` | no | Default machine credential name or ID |

### Getting a Token

Generate a personal access token in AAP:

1. Log into the AAP/AWX web UI
2. Navigate to **Users** > your user > **Tokens**
3. Click **Add** and create a token with appropriate scope
4. Set `export AAP_CONTROLLER_TOKEN="<token>"`

Or via the API:

```bash
curl -s -X POST "https://aap.example.com/api/v2/tokens/" \
  -u "admin:password" \
  -H "Content-Type: application/json" \
  -d '{"scope": "write"}'
```

## Key AAP Concepts

### Inventories

Collections of hosts that AAP manages. List available inventories:

```bash
curl -s -H "Authorization: Bearer ${AAP_CONTROLLER_TOKEN}" \
  "${AAP_CONTROLLER_URL}/api/v2/inventories/" | python3 -m json.tool
```

### Credentials

Machine credentials (SSH keys, passwords) stored securely in AAP. The agent never sees
the actual secrets -- AAP injects them at execution time.

```bash
curl -s -H "Authorization: Bearer ${AAP_CONTROLLER_TOKEN}" \
  "${AAP_CONTROLLER_URL}/api/v2/credentials/?credential_type__name=Machine" | python3 -m json.tool
```

### Job Templates

Pre-configured playbook runs with inventory, credentials, and variables already attached.
These are the primary execution mechanism for playbook-based operations.

```bash
curl -s -H "Authorization: Bearer ${AAP_CONTROLLER_TOKEN}" \
  "${AAP_CONTROLLER_URL}/api/v2/job_templates/" | python3 -m json.tool
```

### Ad-Hoc Commands

One-off module executions (equivalent to `ansible <hosts> -m <module> -a "<args>"`).
Useful for quick operations that don't warrant a full job template.

```bash
curl -s -X POST "${AAP_CONTROLLER_URL}/api/v2/ad_hoc_commands/" \
  -H "Authorization: Bearer ${AAP_CONTROLLER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "inventory": 1,
    "credential": 1,
    "module_name": "ansible.builtin.ping",
    "module_args": "",
    "become_enabled": false
  }'
```

## The aap_run.py Helper

Every generated skill includes `scripts/aap_run.py` -- a Python 3 stdlib-only helper
that wraps the AAP API. It handles launching, polling, and output retrieval.

### Ad-Hoc Command

```bash
python3 scripts/aap_run.py adhoc "name=nginx state=present" \
  --inventory "Production" --credential "SSH Key"
```

### Launch Job Template

```bash
python3 scripts/aap_run.py launch "deploy-webservers" \
  --extra-vars '{"version": "2.0"}' --limit "web1.example.com"
```

### Check Job Status

```bash
python3 scripts/aap_run.py status 42
```

All commands output structured JSON for easy parsing by AI agents.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `SSL: CERTIFICATE_VERIFY_FAILED` | Set `AAP_VERIFY_SSL=false` for self-signed certs |
| `HTTP 401` | Token is invalid or expired -- regenerate it |
| `HTTP 403` | Token lacks permissions -- check RBAC roles in AAP |
| Inventory not found | List inventories to find the correct name/ID |
| Job stays in `pending` | AAP may lack capacity -- check instance groups |
