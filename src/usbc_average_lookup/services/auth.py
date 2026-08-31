from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from os import environ
from pathlib import Path
from shutil import rmtree
from typing import Any

AUTH_MESSAGE_PREFIX = "AVERAGE_ASSISTANT_AUTH:"


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

    The WebView runs in a dedicated helper executable because pywebview needs to
    own that process's main GUI thread. Only the temporary bearer token crosses
    the helper's in-memory output pipe. ``private_mode=True`` prevents cookies
    and browser storage from being retained after the sign-in window closes.
    """

    def __init__(self, timeout_seconds: int = 300) -> None:
        self._timeout_seconds = timeout_seconds
        self._process: subprocess.Popen[str] | None = None

    def sign_in(self) -> AuthSession:
        self.sign_out()
        process = subprocess.Popen(
            _sign_in_helper_command(self._timeout_seconds),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._process = process
        try:
            try:
                output, error_output = process.communicate(timeout=self._timeout_seconds + 15)
            except subprocess.TimeoutExpired as error:
                _stop_process(process)
                raise TimeoutError("BOWL.com sign-in timed out") from error
            try:
                payload = _payload_from_helper_output(output)
            except RuntimeError:
                detail = _safe_helper_error(error_output)
                if detail:
                    raise RuntimeError(f"The private sign-in window failed: {detail}") from None
                raise
            return _session_from_payload(payload)
        finally:
            _stop_process(process)
            if self._process is process:
                self._process = None

    def sign_out(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        _stop_process(process)


def clear_legacy_sign_in_data(base_path: Path | None = None) -> None:
    """Remove app-owned browser profiles left by versions before 0.3.0."""

    root = base_path or Path(environ.get("LOCALAPPDATA", Path.home())) / "Average Assistant"
    for profile_name in (
        "browser-profile",
        "browser-profile-chrome",
        "browser-profile-brave",
    ):
        rmtree(root / profile_name, ignore_errors=True)


def _sign_in_helper_command(timeout_seconds: int) -> list[str]:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        helper = Path(bundle_root) / "Average-Assistant-SignIn.exe"
        if not helper.is_file():
            raise RuntimeError("The private sign-in helper is missing from this installation")
        return [str(helper), str(timeout_seconds)]
    return [
        sys.executable,
        "-m",
        "usbc_average_lookup.signin_helper",
        str(timeout_seconds),
    ]


def _payload_from_helper_output(output: str) -> Any:
    for line in reversed(output.splitlines()):
        if line.startswith(AUTH_MESSAGE_PREFIX):
            try:
                return json.loads(line.removeprefix(AUTH_MESSAGE_PREFIX))
            except json.JSONDecodeError as error:
                raise RuntimeError("The sign-in helper returned an invalid response") from error
    raise RuntimeError("The private sign-in window closed unexpectedly")


def _safe_helper_error(error_output: str) -> str:
    lines = [line.strip() for line in error_output.splitlines() if line.strip()]
    return lines[-1][:300] if lines else ""


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


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
