from app.states import parse_state_return

STATE_OUTPUT = {
    "file_|-/etc/motd_|-/etc/motd_|-managed": {
        "result": True,
        "comment": "File /etc/motd updated",
        "name": "/etc/motd",
        "changes": {"diff": "..."},
        "__sls__": "motd",
        "__run_num__": 1,
        "duration": 11.1,
        "__id__": "/etc/motd",
    },
    "pkg_|-curl_|-curl_|-installed": {
        "result": False,
        "comment": "No such package",
        "name": "curl",
        "changes": {},
        "__sls__": "base",
        "__run_num__": 0,
        "duration": 2,
    },
    "cmd_|-check_|-true_|-run": {
        "result": None,
        "comment": "Would run",
        "name": "true",
        "changes": {},
        "__run_num__": 2,
    },
}


def test_parses_states_in_run_order() -> None:
    states = parse_state_return(STATE_OUTPUT)
    assert states is not None
    assert [s.id for s in states] == ["curl", "/etc/motd", "check"]
    curl, motd, check = states
    assert (curl.function, curl.result, curl.changed, curl.sls) == (
        "pkg.installed",
        False,
        False,
        "base",
    )
    assert (motd.function, motd.result, motd.changed, motd.duration_ms) == (
        "file.managed",
        True,
        True,
        11.1,
    )
    assert check.result is None and check.duration_ms is None


def test_compile_errors_become_a_failed_state() -> None:
    states = parse_state_return(["Rendering SLS 'base:motd' failed: bad yaml"])
    assert states is not None and len(states) == 1
    assert states[0].result is False and "bad yaml" in states[0].comment


def test_non_state_output_is_none() -> None:
    assert parse_state_return(True) is None
    assert parse_state_return({}) is None
    assert parse_state_return({"os": "Debian"}) is None
    assert parse_state_return({"a_|-b_|-c_|-d": "not a dict"}) is None
