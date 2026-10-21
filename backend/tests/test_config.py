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
    assert [c.grain for c in settings.fleet.columns] == [
        "app_version",
        "firmware_version",
        "@packages:nginx",
    ]
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


def test_inventory_defaults_and_checks() -> None:
    settings = parse_config(MINIMAL, {"PW": "x"})
    assert settings.inventory.refresh_hours == 6
    assert settings.inventory.checks == {}
    text = "inventory: {refresh_hours: 1, checks: {containers: podman ps, rover-cli: x}}\n"
    settings = parse_config(MINIMAL + text, {"PW": "x"})
    assert settings.inventory.refresh_hours == 1
    assert settings.inventory.checks == {"containers": "podman ps", "rover-cli": "x"}


@pytest.mark.parametrize("hours", ["0.1", ".inf", "1000"])
def test_inventory_refresh_hours_are_bounded(hours: str) -> None:
    with pytest.raises(ConfigError, match="refresh_hours"):
        parse_config(MINIMAL + f"inventory: {{refresh_hours: {hours}}}\n", {"PW": "x"})


def test_inventory_refresh_can_be_every_15_minutes() -> None:
    settings = parse_config(MINIMAL + "inventory: {refresh_hours: 0.25}\n", {"PW": "x"})
    assert settings.inventory.refresh_hours == 0.25


# Double-quoted in the YAML, so "\n" is a real newline.
@pytest.mark.parametrize(
    "name", ["packages", "Has Space", "", "a:b", "@x", "-x", "a" * 65, "abc\\n"]
)
def test_inventory_check_names_are_checked(name: str) -> None:
    with pytest.raises(ConfigError, match="check name"):
        parse_config(MINIMAL + f'inventory: {{checks: {{"{name}": "true"}}}}\n', {"PW": "x"})


def test_inventory_check_name_can_be_64_characters() -> None:
    name = "a" * 64
    settings = parse_config(MINIMAL + f"inventory: {{checks: {{{name}: 'true'}}}}\n", {"PW": "x"})
    assert list(settings.inventory.checks) == [name]


def test_inventory_check_needs_a_command() -> None:
    with pytest.raises(ConfigError, match="no command"):
        parse_config(MINIMAL + "inventory: {checks: {containers: '  '}}\n", {"PW": "x"})


def test_inventory_check_command_is_one_line() -> None:
    text = "inventory:\n  checks:\n    containers: |\n      podman ps\n"
    settings = parse_config(MINIMAL + text, {"PW": "x"})
    assert settings.inventory.checks == {"containers": "podman ps"}
    with pytest.raises(ConfigError, match="one line"):
        parse_config(MINIMAL + 'inventory: {checks: {containers: "a\\nb"}}\n', {"PW": "x"})


# Double-quoted in the YAML, so the escapes are real characters.
@pytest.mark.parametrize("command", ["podman\\0ps", "a\\x1bb", "a\\u2028b", "a\\x7fb"])
def test_inventory_check_command_is_printable(command: str) -> None:
    with pytest.raises(ConfigError, match="characters that can't be used"):
        parse_config(MINIMAL + f'inventory: {{checks: {{c: "{command}"}}}}\n', {"PW": "x"})


def test_inventory_check_command_error_names_the_first_bad_character() -> None:
    # The tab is fine; the escape character comes before the NUL.
    text = 'inventory: {checks: {c: "a\\tb\\x1bc\\0"}}\n'
    with pytest.raises(ConfigError, match=r"U\+001B"):
        parse_config(MINIMAL + text, {"PW": "x"})


def test_inventory_check_commands_are_taken_literally() -> None:
    # A ${VAR} in a command is for the minion's shell: brine's own environment isn't put in
    # (it would show in Settings), and one brine doesn't have isn't an error.
    command = "ls ${HOME}/.config ${PW} ${UNSET:-x}"
    text = MINIMAL + f"inventory:\n  refresh_hours: ${{HOURS:-2}}\n  checks: {{c: '{command}'}}\n"
    for env in ({"PW": "x"}, {"PW": "x", "HOME": "/home/brine"}):
        settings = parse_config(text, env)
        assert settings.inventory.checks == {"c": command}
        # Placeholders anywhere else are still filled in, in the inventory section too.
        assert settings.salt_api.password.get_secret_value() == "x"
        assert settings.inventory.refresh_hours == 2


def test_inventory_check_command_may_have_tabs_and_unicode() -> None:
    text = "inventory: {checks: {c: \"printf '%s\\t%s' café x\"}}\n"
    settings = parse_config(MINIMAL + text, {"PW": "x"})
    assert settings.inventory.checks == {"c": "printf '%s\t%s' café x"}


@pytest.mark.parametrize("command", ["LC_ALL=C dpkg-query -W", "a.b-c=1 x", "_X=1"])
def test_inventory_check_command_cant_start_with_a_kwarg(command: str) -> None:
    # The minion would read it as an option to cmd.run_all, so the check would never run.
    with pytest.raises(ConfigError, match="start the command with env"):
        parse_config(MINIMAL + f"inventory: {{checks: {{c: '{command}'}}}}\n", {"PW": "x"})


@pytest.mark.parametrize(
    "command",
    ["env LC_ALL=C dpkg-query -W", "/opt/x=1/run", "1x=2", "podman ps --format '{{.A}}={{.B}}'"],
)
def test_inventory_check_command_may_have_an_equals_sign_later(command: str) -> None:
    quoted = command.replace("'", "''")
    text = f"inventory: {{checks: {{c: '{quoted}'}}}}\n"
    assert parse_config(MINIMAL + text, {"PW": "x"}).inventory.checks == {"c": command}


def test_inventory_checks_run_different_commands() -> None:
    text = "inventory: {checks: {a: podman ps, b: ' podman ps '}}\n"
    with pytest.raises(ConfigError, match="checks 'a' and 'b' run the same command"):
        parse_config(MINIMAL + text, {"PW": "x"})


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
