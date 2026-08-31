from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from multiprocessing import Pipe, Process
from multiprocessing.connection import Connection
from os import environ
from pathlib import Path
from shutil import rmtree
from time import monotonic, sleep
from typing import Any


class AuthState(StrEnum):
    SIGNED_OUT = "Not signed in"
    SIGNED_IN = "Signed in"
    EXPIRED = "Session expired"


@dataclass(frozen=True, slots=True)
class AuthSession:
    state: AuthState
    display_name: str = ""
    bearer_token: str = field(default="", repr=False)


class WebViewAuthenticator:
    """Sign in on BOWL.com's real page inside a private app-owned WebView.

    The WebView runs in a child process because pywebview needs to own that
    process's main GUI thread. Only the temporary bearer token crosses the
    in-memory pipe. ``private_mode=True`` prevents cookies and browser storage
    from being retained after the sign-in window closes.
    """

    def __init__(self, timeout_seconds: int = 300) -> None:
        self._timeout_seconds = timeout_seconds
        self._process: Process | None = None

    def sign_in(self) -> AuthSession:
        self.sign_out()
        receive, send = Pipe(duplex=False)
        process = Process(
            target=_run_private_sign_in,
            args=(send, self._timeout_seconds),
            name="Average Assistant sign-in",
            daemon=True,
        )
        self._process = process
        process.start()
        send.close()
        try:
            if not receive.poll(self._timeout_seconds + 15):
                raise TimeoutError("BOWL.com sign-in timed out")
            try:
                payload = receive.recv()
            except EOFError as error:
                raise RuntimeError("The private sign-in window closed unexpectedly") from error
            return _session_from_payload(payload)
        finally:
            receive.close()
            # Give WebView2 time to close cleanly and release its native resources.
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            if self._process is process:
                self._process = None

    def sign_out(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)


def clear_legacy_sign_in_data(base_path: Path | None = None) -> None:
    """Remove app-owned browser profiles left by versions before 0.3.0."""

    root = base_path or Path(environ.get("LOCALAPPDATA", Path.home())) / "Average Assistant"
    for profile_name in (
        "browser-profile",
        "browser-profile-chrome",
        "browser-profile-brave",
    ):
        rmtree(root / profile_name, ignore_errors=True)


def _run_private_sign_in(send: Connection, timeout_seconds: int) -> None:
    """Child-process entry point for the private WebView2 window."""

    import webview

    sent = False
    window = webview.create_window(
        "Sign in to BOWL.com — Average Assistant",
        "https://webapps.bowl.com/USBCFindA/Home/Member",
        width=1000,
        height=760,
        min_size=(760, 560),
        resizable=True,
        background_color="#13191F",
        text_select=True,
    )

    def watch_for_session(target_window) -> None:
        nonlocal sent
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            try:
                values = target_window.evaluate_js(
                    """(() => [
                        ...Object.values(window.localStorage),
                        ...Object.values(window.sessionStorage)
                    ])()"""
                )
                token = _bearer_token_from_storage_values(values or [])
            except Exception:
                token = ""
            if token:
                _send_payload(send, {"token": token})
                sent = True
                target_window.destroy()
                return
            sleep(0.5)
        _send_payload(send, {"error": "BOWL.com sign-in timed out"})
        sent = True
        target_window.destroy()

    try:
        webview.start(
            watch_for_session,
            args=(window,),
            gui="edgechromium",
            private_mode=True,
        )
        if not sent:
            _send_payload(send, {"error": "The sign-in window was closed"})
    except Exception as error:
        _send_payload(send, {"error": f"Could not open the private sign-in window: {error}"})
    finally:
        send.close()


def _send_payload(send: Connection, payload: dict[str, str]) -> None:
    try:
        send.send(payload)
    except (BrokenPipeError, EOFError, OSError):
        pass


def _session_from_payload(payload: Any) -> AuthSession:
    if not isinstance(payload, dict):
        raise RuntimeError("The sign-in window returned an invalid response")
    token = payload.get("token")
    if isinstance(token, str) and token.strip():
        return AuthSession(AuthState.SIGNED_IN, bearer_token=token.strip())
    message = payload.get("error")
    if isinstance(message, str) and message.strip():
        raise RuntimeError(message.strip())
    raise RuntimeError("BOWL.com sign-in did not return a session")


def _bearer_token_from_headers(headers: dict[str, str]) -> str:
    authorization = next(
        (value for key, value in headers.items() if key.casefold() == "authorization"), ""
    )
    scheme, separator, token = authorization.partition(" ")
    if separator and scheme.casefold() == "bearer" and token.strip():
        return token.strip()
    return ""


def _bearer_token_from_storage_values(values: list[object]) -> str:
    for value in values:
        token = _token_from_value(value)
        if token:
            return token
    return ""


def _token_from_value(value: object) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return ""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).replace("_", "").casefold()
            if normalized in {"accesstoken", "bearertoken"} and isinstance(child, str):
                return child.strip()
        for child in value.values():
            token = _token_from_value(child)
            if token:
                return token
    if isinstance(value, list):
        for child in value:
            token = _token_from_value(child)
            if token:
                return token
    return ""
