"""Smoke tests for the web UI pages."""
import pytest

try:
    from fastapi.testclient import TestClient
    from ansibleclaw.web.app import app
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

pytestmark = pytest.mark.skipif(not HAS_DEPS, reason="UI deps missing")


@pytest.fixture()
def web_client():
    return TestClient(app)


def test_skills_page(web_client):
    resp = web_client.get("/skills")
    assert resp.status_code == 200
    assert "ansible_manager" in resp.text
    assert "Skills Library" in resp.text
    assert "Gemini CLI" in resp.text
    assert "Uninstall" in resp.text


def test_skill_detail_page(web_client):
    resp = web_client.get("/skills/ansible_manager")
    assert resp.status_code == 200


def test_skill_not_found(web_client):
    resp = web_client.get("/skills/nonexistent_skill_xyz")
    assert resp.status_code == 404


def test_search_page(web_client):
    resp = web_client.get("/search")
    assert resp.status_code == 200
    assert "Module Search" in resp.text


def test_generate_page(web_client):
    resp = web_client.get("/generate")
    assert resp.status_code == 200
    assert "Module Name" in resp.text


def test_cannot_delete_builtin_skill(web_client):
    resp = web_client.delete("/skills/ansible_manager")
    assert resp.status_code == 400
    assert "built-in" in resp.text.lower()


def test_uninstall_skill_from_platform(web_client, tmp_path, monkeypatch):
    import ansibleclaw.web.app as webapp

    plat = tmp_path / "plat"
    plat.mkdir()
    merged = dict(webapp.INSTALL_PATHS)
    merged["fixtureplat"] = plat
    monkeypatch.setattr(webapp, "INSTALL_PATHS", merged)

    ins = web_client.post(
        "/skills/ansible_manager/install",
        data={"platform": "fixtureplat"},
    )
    assert ins.status_code == 200
    assert (plat / "ansible_manager" / "SKILL.md").exists()

    rem = web_client.post(
        "/skills/ansible_manager/uninstall",
        data={"platform": "fixtureplat"},
    )
    assert rem.status_code == 200
    assert "\u2713" in rem.text or "Removed" in rem.text
    assert not (plat / "ansible_manager").exists()


def test_uninstall_unknown_platform(web_client):
    resp = web_client.post(
        "/skills/ansible_manager/uninstall",
        data={"platform": "notaplatform"},
    )
    assert resp.status_code == 400


def test_root_redirects_to_skills(web_client):
    resp = web_client.get("/", follow_redirects=False)
    assert resp.status_code == 307
    assert "/skills" in resp.headers["location"]


def test_inventory_page(web_client, tmp_path, monkeypatch):
    inv = tmp_path / "hosts.yml"
    monkeypatch.setenv("ANSIBLECLAW_INVENTORY_FILE", str(inv))
    resp = web_client.get("/inventory")
    assert resp.status_code == 200
    assert "Local Inventory" in resp.text
    assert str(inv) in resp.text


def test_inventory_save_valid(web_client, tmp_path, monkeypatch):
    inv = tmp_path / "hosts.yml"
    monkeypatch.setenv("ANSIBLECLAW_INVENTORY_FILE", str(inv))
    yaml_content = "all:\n  hosts:\n    h1:\n"
    resp = web_client.post("/inventory", data={"content": yaml_content})
    assert resp.status_code == 200
    assert "Inventory saved" in resp.text
    assert inv.read_text() == yaml_content


def test_inventory_save_invalid(web_client, tmp_path, monkeypatch):
    inv = tmp_path / "hosts.yml"
    monkeypatch.setenv("ANSIBLECLAW_INVENTORY_FILE", str(inv))
    bad = "all: ["
    resp = web_client.post("/inventory", data={"content": bad})
    assert resp.status_code == 200
    assert "Invalid YAML" in resp.text
    assert not inv.exists()
