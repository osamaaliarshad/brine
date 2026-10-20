from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import parse_config
from app.main import create_app

SETTINGS = parse_config(
    "salt_api: {url: 'https://salt.test:8000', username: svc, password: x}\n", {}
)


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<html>brine</html>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('hi')", encoding="utf-8")
    return tmp_path


def test_healthz() -> None:
    with TestClient(create_app(SETTINGS, frontend_dist=Path("/nonexistent"))) as client:
        resp = client.get("/api/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_serves_frontend_assets(dist: Path) -> None:
    with TestClient(create_app(SETTINGS, frontend_dist=dist)) as client:
        assert client.get("/app.js").text == "console.log('hi')"
        assert "brine" in client.get("/").text


def test_client_routes_fall_back_to_index(dist: Path) -> None:
    with TestClient(create_app(SETTINGS, frontend_dist=dist)) as client:
        resp = client.get("/jobs/20261019123456789")
    assert resp.status_code == 200
    assert "brine" in resp.text


def test_unknown_api_paths_stay_404(dist: Path) -> None:
    with TestClient(create_app(SETTINGS, frontend_dist=dist)) as client:
        assert client.get("/api/nope").status_code == 404
