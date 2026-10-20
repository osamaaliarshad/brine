from pathlib import Path

import pytest

from app.config import ConfigError, load_config, parse_config

EXAMPLE = Path(__file__).resolve().parents[2] / "config.example.yaml"
EXAMPLE_ENV = {
    "SALT_API_PASSWORD": "s3cret",
    "OIDC_CLIENT_ID": "client-id",
    "OIDC_CLIENT_SECRET": "client-secret",
}

MINIMAL = """
salt_api:
  url: https://salt.test:8000
  username: svc
  password: ${PW}
auth:
  provider: none
"""


def test_example_config_is_valid() -> None:
    settings = load_config(EXAMPLE, EXAMPLE_ENV)
    assert settings.salt_api.password.get_secret_value() == "s3cret"
    assert [c.grain for c in settings.fleet.columns] == ["app_version", "firmware_version"]
    assert settings.roles.viewer == ["*@example.com"]


def test_defaults_fill_optional_sections() -> None:
    settings = parse_config(MINIMAL, {"PW": "x"})
    assert settings.salt_api.eauth == "pam"
    assert settings.salt_api.verify_tls is True
    assert settings.fleet.stale_after_minutes == 15
    assert settings.fleet.columns == []
    assert settings.database == "sqlite:///data/brine.db"


def test_missing_env_var_is_reported_by_name() -> None:
    with pytest.raises(ConfigError, match="PW"):
        parse_config(MINIMAL, {})


def test_placeholder_default_is_used_when_var_unset() -> None:
    text = MINIMAL.replace("${PW}", "${PW:-fallback}")
    assert parse_config(text, {}).salt_api.password.get_secret_value() == "fallback"


def test_placeholders_in_comments_are_ignored() -> None:
    settings = parse_config("# set ${NOT_SET} here\n" + MINIMAL, {"PW": "x"})
    assert settings.salt_api.username == "svc"


def test_env_values_cannot_inject_yaml_structure() -> None:
    settings = parse_config(MINIMAL, {"PW": "a: b\nusername: evil"})
    assert settings.salt_api.password.get_secret_value() == "a: b\nusername: evil"
    assert settings.salt_api.username == "svc"


def test_env_override_sets_nested_keys_with_yaml_types() -> None:
    env = {
        "PW": "x",
        "BRINE__SALT_API__VERIFY_TLS": "false",
        "BRINE__FLEET__STALE_AFTER_MINUTES": "5",
        "BRINE__AUTH__ALLOWED_DOMAINS": "[a.com, b.com]",
    }
    settings = parse_config(MINIMAL, env)
    assert settings.salt_api.verify_tls is False
    assert settings.fleet.stale_after_minutes == 5
    assert settings.auth.allowed_domains == ["a.com", "b.com"]


def test_env_override_wins_over_file_value() -> None:
    settings = parse_config(MINIMAL, {"PW": "from-file", "BRINE__SALT_API__PASSWORD": "from-env"})
    assert settings.salt_api.password.get_secret_value() == "from-env"


def test_secrets_are_not_shown_in_repr() -> None:
    settings = parse_config(MINIMAL, {"PW": "hunter2"})
    assert "hunter2" not in repr(settings)
    assert "hunter2" not in settings.model_dump_json()


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ConfigError, match="verify_tsl"):
        parse_config(MINIMAL + "  verify_tsl: false\n", {"PW": "x"})


def test_invalid_values_are_rejected() -> None:
    with pytest.raises(ConfigError, match="stale_after_minutes"):
        parse_config(MINIMAL + "fleet:\n  stale_after_minutes: 0\n", {"PW": "x"})


def test_non_mapping_yaml_is_rejected() -> None:
    with pytest.raises(ConfigError, match="mapping"):
        parse_config("- just\n- a list\n", {})


def test_missing_file_explains_how_to_fix(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="BRINE_CONFIG"):
        load_config(tmp_path / "nope.yaml", {})


def test_path_comes_from_env(tmp_path: Path) -> None:
    cfg = tmp_path / "custom.yaml"
    cfg.write_text(MINIMAL, encoding="utf-8")
    settings = load_config(env={"BRINE_CONFIG": str(cfg), "PW": "x"})
    assert settings.salt_api.username == "svc"
