import pytest

from usbc_average_lookup.services import auth
from usbc_average_lookup.services.auth import (
    AuthState,
    WebViewAuthenticator,
    _bearer_token_from_headers,
    _bearer_token_from_storage_values,
    _session_from_payload,
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


def test_authenticator_closes_pipe_and_joins_finished_webview(monkeypatch) -> None:
    class FakeReceive:
        closed = False

        def poll(self, _timeout: int) -> bool:
            return True

        def recv(self):
            return {"token": "secret-value"}

        def close(self) -> None:
            self.closed = True

    class FakeSend:
        closed = False

        def close(self) -> None:
            self.closed = True

    class FakeProcess:
        joined = False
        terminated = False

        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def is_alive(self) -> bool:
            return False

        def join(self, timeout: int) -> None:
            assert timeout == 5
            self.joined = True

        def terminate(self) -> None:
            self.terminated = True

    receive = FakeReceive()
    send = FakeSend()
    processes: list[FakeProcess] = []

    def make_process(**kwargs):
        process = FakeProcess(**kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(auth, "Pipe", lambda duplex: (receive, send))
    monkeypatch.setattr(auth, "Process", make_process)

    session = WebViewAuthenticator(timeout_seconds=1).sign_in()

    assert session.state is AuthState.SIGNED_IN
    assert receive.closed and send.closed
    assert processes[0].joined
    assert not processes[0].terminated


def test_sign_out_terminates_and_joins_active_webview() -> None:
    class FakeProcess:
        terminated = False
        joined = False

        def is_alive(self) -> bool:
            return True

        def terminate(self) -> None:
            self.terminated = True

        def join(self, timeout: int) -> None:
            assert timeout == 5
            self.joined = True

    authenticator = WebViewAuthenticator()
    process = FakeProcess()
    authenticator._process = process

    authenticator.sign_out()

    assert process.terminated
    assert process.joined
    assert authenticator._process is None


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
