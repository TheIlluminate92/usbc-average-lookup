import json

import pytest

from usbc_average_lookup.services import auth
from usbc_average_lookup.services.auth import (
    AUTH_MESSAGE_PREFIX,
    AuthState,
    WebViewAuthenticator,
    _bearer_token_from_headers,
    _bearer_token_from_storage_values,
    _payload_from_helper_output,
    _session_from_payload,
    _stop_process,
    clear_legacy_sign_in_data,
)


def test_extracts_bearer_token_case_insensitively() -> None:
    assert _bearer_token_from_headers({"Authorization": "Bearer secret-value"}) == "secret-value"


def test_rejects_missing_or_non_bearer_authorization() -> None:
    assert _bearer_token_from_headers({}) == ""
    assert _bearer_token_from_headers({"authorization": "Basic abc"}) == ""


def test_extracts_oidc_access_token_from_private_webview_storage() -> None:
    values = [
        "ordinary preference",
        '{"profile":{"name":"Erik"},"access_token":"secret-value"}',
    ]

    assert _bearer_token_from_storage_values(values) == "secret-value"


def test_builds_session_from_private_webview_payload_without_exposing_token() -> None:
    session = _session_from_payload({"token": " secret-value "})

    assert session.state is AuthState.SIGNED_IN
    assert session.bearer_token == "secret-value"
    assert "secret-value" not in repr(session)


def test_clears_only_legacy_app_owned_browser_profiles(tmp_path) -> None:
    old_edge = tmp_path / "browser-profile"
    old_brave = tmp_path / "browser-profile-brave"
    unrelated = tmp_path / "rosters"
    old_edge.mkdir()
    old_brave.mkdir()
    unrelated.mkdir()

    clear_legacy_sign_in_data(tmp_path)

    assert not old_edge.exists()
    assert not old_brave.exists()
    assert unrelated.exists()


def test_authenticator_reads_session_from_finished_helper(monkeypatch) -> None:
    class FakeProcess:
        terminated = False

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def communicate(self, timeout: int):
            assert timeout == 16
            return (f'{AUTH_MESSAGE_PREFIX}{{"token":"secret-value"}}\n', "")

        def poll(self):
            return 0

        def terminate(self) -> None:
            self.terminated = True

    processes: list[FakeProcess] = []

    def make_process(*args, **kwargs):
        process = FakeProcess(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(auth.subprocess, "Popen", make_process)

    session = WebViewAuthenticator(timeout_seconds=1).sign_in()

    assert session.state is AuthState.SIGNED_IN
    assert not processes[0].terminated


def test_sign_out_terminates_and_joins_active_webview() -> None:
    class FakeProcess:
        terminated = False
        waited = False

        def poll(self):
            return None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: int) -> None:
            assert timeout == 5
            self.waited = True

    authenticator = WebViewAuthenticator()
    process = FakeProcess()
    authenticator._process = process

    authenticator.sign_out()

    assert process.terminated
    assert process.waited
    assert authenticator._process is None


def test_parses_only_prefixed_helper_payload() -> None:
    output = f"diagnostic line\n{AUTH_MESSAGE_PREFIX}{json.dumps({'token': 'secret-value'})}\n"

    assert _payload_from_helper_output(output) == {"token": "secret-value"}


def test_force_kills_helper_that_does_not_stop() -> None:
    class StuckProcess:
        terminated = False
        killed = False
        waits = 0

        def poll(self):
            return None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: int) -> None:
            assert timeout == 5
            self.waits += 1
            if self.waits == 1:
                raise auth.subprocess.TimeoutExpired("helper", timeout)

        def kill(self) -> None:
            self.killed = True

    process = StuckProcess()

    _stop_process(process)

    assert process.terminated
    assert process.killed
    assert process.waits == 2


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"error": "The sign-in window was closed"}, "window was closed"),
        ({}, "did not return a session"),
        ("invalid", "invalid response"),
    ],
)
def test_rejects_failed_or_invalid_private_webview_payload(payload, message: str) -> None:
    with pytest.raises(RuntimeError, match=message):
        _session_from_payload(payload)
