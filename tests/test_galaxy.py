"""Tests for ansibleclaw.core.galaxy."""

import json
from unittest.mock import patch, MagicMock

import pytest

from ansibleclaw.core.galaxy import (
    GalaxyDocProvider,
    GalaxyError,
    _parse_fqcn,
    detect_pinned_version,
)


SAMPLE_VERSIONS_RESPONSE = {
    "data": [{"version": "9.2.0"}],
}

SAMPLE_DOCS_BLOB = {
    "docs_blob": {
        "contents": [
            {
                "content_name": "redis",
                "content_type": "module",
                "doc_strings": {
                    "doc": {
                        "short_description": "Various redis commands",
                        "description": ["Manage redis instances."],
                        "options": [
                            {
                                "name": "command",
                                "type": "str",
                                "required": True,
                                "description": ["The redis command to run."],
                            },
                            {
                                "name": "login_host",
                                "type": "str",
                                "required": False,
                                "default": "localhost",
                                "description": ["The host running the redis database."],
                            },
                        ],
                        "author": ["test"],
                        "notes": [],
                        "version_added": "1.0.0",
                    },
                    "examples": "- name: Run redis ping\n  community.general.redis:\n    command: ping\n",
                    "return": [],
                    "metadata": {},
                },
            },
            {
                "content_name": "some_other",
                "content_type": "module",
                "doc_strings": {"doc": {"short_description": "Other"}},
            },
        ],
        "collection_readme": {"html": "", "name": "README.md"},
        "documentation_files": [],
    }
}


class TestParseFqcn:
    def test_valid_fqcn(self):
        ns, name, module = _parse_fqcn("community.general.redis")
        assert ns == "community"
        assert name == "general"
        assert module == "redis"

    def test_invalid_short_name(self):
        with pytest.raises(GalaxyError, match="not a fully-qualified"):
            _parse_fqcn("redis")


class TestGalaxyDocProvider:
    def _mock_api_get(self, provider, responses):
        """Patch _api_get to return responses in order."""
        call_count = [0]
        def side_effect(path):
            idx = min(call_count[0], len(responses) - 1)
            call_count[0] += 1
            return responses[idx]
        provider._api_get = MagicMock(side_effect=side_effect)

    def test_fetch_module_doc_with_explicit_version(self):
        provider = GalaxyDocProvider(base_url="https://galaxy.example.com")
        self._mock_api_get(provider, [SAMPLE_DOCS_BLOB])

        doc, meta = provider.fetch_module_doc(
            "community.general.redis", version="9.2.0"
        )

        assert "community.general.redis" in doc
        assert doc["community.general.redis"]["doc"]["short_description"] == "Various redis commands"
        assert meta["doc_source"] == "galaxy"
        assert meta["doc_version"] == "9.2.0"
        assert "doc_warning" not in meta

    def test_fetch_module_doc_latest_includes_warning(self):
        provider = GalaxyDocProvider(base_url="https://galaxy.example.com")
        self._mock_api_get(provider, [SAMPLE_VERSIONS_RESPONSE, SAMPLE_DOCS_BLOB])

        doc, meta = provider.fetch_module_doc("community.general.redis")

        assert meta["doc_source"] == "galaxy"
        assert meta["doc_version"] == "9.2.0"
        assert "doc_warning" in meta
        assert "may differ" in meta["doc_warning"]

    def test_options_converted_to_dict(self):
        provider = GalaxyDocProvider(base_url="https://galaxy.example.com")
        self._mock_api_get(provider, [SAMPLE_DOCS_BLOB])

        doc, _ = provider.fetch_module_doc(
            "community.general.redis", version="9.2.0"
        )

        options = doc["community.general.redis"]["doc"]["options"]
        assert isinstance(options, dict)
        assert "command" in options
        assert "login_host" in options
        assert options["command"]["type"] == "str"
        assert options["command"]["required"] is True

    def test_module_not_found(self):
        provider = GalaxyDocProvider(base_url="https://galaxy.example.com")
        self._mock_api_get(provider, [SAMPLE_DOCS_BLOB])

        with pytest.raises(GalaxyError, match="not found"):
            provider.fetch_module_doc(
                "community.general.nonexistent", version="9.2.0"
            )

    def test_no_versions_available(self):
        provider = GalaxyDocProvider(base_url="https://galaxy.example.com")
        self._mock_api_get(provider, [{"data": []}])

        with pytest.raises(GalaxyError, match="No versions found"):
            provider.fetch_module_doc("community.general.redis")


class TestDetectPinnedVersion:
    def test_reads_requirements_yml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        req = tmp_path / "requirements.yml"
        req.write_text(
            "collections:\n"
            "  - name: community.general\n"
            "    version: '8.5.0'\n"
        )
        result = detect_pinned_version("community.general.redis")
        assert result == "8.5.0"

    def test_reads_ee_definition(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ee = tmp_path / "execution-environment.yml"
        ee.write_text(
            "dependencies:\n"
            "  galaxy:\n"
            "    collections:\n"
            "      - name: community.general\n"
            "        version: '7.0.0'\n"
        )
        result = detect_pinned_version("community.general.redis")
        assert result == "7.0.0"

    def test_returns_none_when_no_pin(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = detect_pinned_version("community.general.redis")
        assert result is None

    def test_returns_none_for_unpinned_collection(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        req = tmp_path / "requirements.yml"
        req.write_text(
            "collections:\n"
            "  - name: community.general\n"
        )
        result = detect_pinned_version("community.general.redis")
        assert result is None
