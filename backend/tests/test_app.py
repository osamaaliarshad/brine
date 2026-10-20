from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, parse_config
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return parse_config(
        "salt_api: {url: 'https://salt.test:8000', username: svc, password: x}\n"
        "auth: {provider: none, anonymous_role: admin}\n"
        f"database: 'sqlite:///{(tmp_path / 'brine.db').as_posix()}'\n",
        {},
    )


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>brine</html>", encoding="utf-8")
    (dist / "app.js").write_text("console.log('hi')", encoding="utf-8")
    return dist


def client(settings: Settings, dist: Path | None = None) -> TestClient:
    return TestClient(
        create_app(settings, frontend_dist=dist or Path("/nonexistent"), run_collector=False)
    )


def test_healthz(settings: Settings) -> None:
    with client(settings) as c:
        resp = c.get("/api/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_startup_creates_the_database(settings: Settings, tmp_path: Path) -> None:
    with client(settings) as c:
        assert c.get("/api/fleet").json()["minions"] == []
    assert (tmp_path / "brine.db").is_file()


def test_serves_frontend_assets(settings: Settings, dist: Path) -> None:
    with client(settings, dist) as c:
        assert c.get("/app.js").text == "console.log('hi')"
        assert "brine" in c.get("/").text


def test_client_routes_fall_back_to_index(settings: Settings, dist: Path) -> None:
    with client(settings, dist) as c:
        resp = c.get("/jobs/20261019123456789")
    assert resp.status_code == 200
    assert "brine" in resp.text


def test_unknown_api_paths_stay_404(settings: Settings, dist: Path) -> None:
    with client(settings, dist) as c:
        assert c.get("/api/nope").status_code == 404
