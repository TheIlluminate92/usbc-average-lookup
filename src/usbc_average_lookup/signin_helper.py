from __future__ import annotations

import json
import sys
from time import monotonic, sleep

import webview

from usbc_average_lookup.services.auth import (
    AUTH_MESSAGE_PREFIX,
    _bearer_token_from_storage_values,
)


def _send(payload: dict[str, str]) -> None:
    print(f"{AUTH_MESSAGE_PREFIX}{json.dumps(payload, separators=(',', ':'))}", flush=True)


def run_private_sign_in(timeout_seconds: int) -> None:
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
                _send({"token": token})
                sent = True
                target_window.destroy()
                return
            sleep(0.5)
        _send({"error": "BOWL.com sign-in timed out"})
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
            _send({"error": "The sign-in window was closed"})
    except Exception as error:
        _send({"error": f"Could not open the private sign-in window: {error}"})


def main() -> None:
    try:
        timeout_seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    except ValueError:
        timeout_seconds = 300
    run_private_sign_in(max(1, timeout_seconds))


if __name__ == "__main__":
    main()
