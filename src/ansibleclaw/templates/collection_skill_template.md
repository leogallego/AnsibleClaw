---
name: ansible-{{ collection_name | replace('_', '-') }}
description: >-
  Collection skill for {{ collection_fqcn }}.
  Use this skill to choose the right module from the {{ collection_fqcn }} collection
  when managing resources on remote hosts via Ansible.
---

# {{ collection_fqcn }} Collection

This skill provides a reference for all {{ modules | length }} modules in the `{{ collection_fqcn }}` collection.
Use it to identify which module to invoke, then refer to the module's individual skill (if generated) for detailed parameters and examples.

## Collection Requirement

This collection must be available before any of its modules can be used.

**CLI mode** (local execution):

```bash
ansible-galaxy collection install {{ collection_fqcn }}
```

**AAP mode** (Execution Environments):
Collections are bundled into Execution Environments (EEs). If this collection is unavailable
in your EE, update your `execution-environment.yml` and rebuild:

```yaml
dependencies:
  galaxy:
    collections:
      - name: {{ collection_fqcn }}
```

```bash
ansible-builder build -t my-ee:latest
```

## When to Use This Skill

Use this skill as a **router** to decide which module from `{{ collection_fqcn }}` best fits the task.
Once you identify the right module, either:

1. Use its dedicated per-module skill (if generated) for full parameter reference and execution scripts
2. Or use the quick-reference below to construct an ad-hoc command or playbook task directly

## Module Catalog

| Module | Description |
|--------|-------------|
{% for m in modules -%}
| `{{ m.module_name }}` | {{ m.short_description | truncate(100) }} |
{% endfor %}

{% for m in modules %}
### {{ m.module_name }}

{{ m.short_description }}

{% if m.params %}
**Key parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
{% for p in m.params[:8] -%}
| `{{ p.name }}` | {{ p.type }} | {{ "yes" if p.required else "no" }} | {{ p.description | truncate(80) }} |
{% endfor %}
{% if m.params | length > 8 -%}
*...and {{ m.params | length - 8 }} more parameter(s). Generate the dedicated skill for the full reference.*
{% endif %}
{% endif %}

**Quick example:**

```bash
ansible <hosts> -m {{ m.module_name }} -a "{% for p in m.params if p.required %}{{ p.name }}=<{{ p.name }}>{{ " " if not loop.last }}{% endfor %}" -b --check --diff
```

{% endfor %}

## Execution Patterns

### CLI -- Ad-Hoc

```bash
ansible <host-pattern> -m {{ collection_fqcn }}.<module> -a "<key=value>" -b --check --diff
```

### CLI -- Playbook

```yaml
- hosts: all
  collections:
    - {{ collection_fqcn }}
  tasks:
    - name: Example task
      <module_short_name>:
        <param>: <value>
```

### AAP -- Ad-Hoc Command

```bash
curl -s -X POST "${AAP_CONTROLLER_URL}/api/v2/ad_hoc_commands/" \
  -H "Authorization: Bearer ${AAP_CONTROLLER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "inventory": 1,
    "credential": 1,
    "module_name": "{{ collection_fqcn }}.<module>",
    "module_args": "<key=value>",
    "become_enabled": true
  }'
```

### AAP -- Job Template

For production workloads, create a Job Template in AAP that references a playbook using modules from this collection. The Execution Environment must include `{{ collection_fqcn }}`.

## Safety

- **Always dry-run first**: Use `--check --diff` before applying destructive changes
- **Become/sudo**: Most system-level modules require `-b`
- **Idempotency**: All modules in this collection are idempotent -- running them multiple times with the same arguments produces the same result
