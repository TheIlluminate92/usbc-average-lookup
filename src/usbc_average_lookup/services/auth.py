import json
from dataclasses import dataclass, field
from enum import StrEnum
from os import environ
from pathlib import Path
from shutil import which
from threading import Event
from time import monotonic, sleep
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Request


class AuthState(StrEnum):
    SIGNED_OUT = "Not signed in"
    SIGNED_IN = "Signed in"
    EXPIRED = "Session expired"


class SignInBrowser(StrEnum):
    EDGE = "Microsoft Edge"
    CHROME = "Google Chrome"

    @property
    def channel(self) -> str:
        return "msedge" if self is SignInBrowser.EDGE else "chrome"

    @property
    def profile_name(self) -> str:
        return "browser-profile" if self is SignInBrowser.EDGE else "browser-profile-chrome"


@dataclass(frozen=True, slots=True)
class AuthSession:
    state: AuthState
    display_name: str = ""
    bearer_token: str = field(default="", repr=False)


class BrowserAuthenticator:
    """Open the genuine login page and capture an API session in memory.

    Playwright drives the Microsoft Edge installation already present on normal
    Windows 10/11 systems. Credentials are entered only into BOWL.com. The app
    observes the bearer header that the signed-in site sends to its own API and
    never persists or logs it.
    """

    MEMBER_URL = "https://webapps.bowl.com/USBCFindA/Home/Member"
    API_PREFIX = "https://apps1.bowl.com/Mobile/api/v1/"

    def __init__(
        self,
        profile_path: Path,
        browser: SignInBrowser = SignInBrowser.EDGE,
        timeout_seconds: int = 300,
    ) -> None:
        self._profile_path = profile_path
        self.browser = browser
        self._timeout_seconds = timeout_seconds
        self._context = None

    def sign_in(self) -> AuthSession:
        from playwright.sync_api import sync_playwright

        token_ready = Event()
        captured_token = ""

        def observe_request(request: "Request") -> None:
            nonlocal captured_token
            if not request.url.startswith(self.API_PREFIX):
                return
            token = _bearer_token_from_headers(request.all_headers())
            if token:
                captured_token = token
                token_ready.set()

        self._profile_path.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(self._profile_path),
                channel=self.browser.channel,
                headless=False,
                reduced_motion="reduce",
                no_viewport=True,
            )
            self._context = context
            try:
                page = context.pages[0] if context.pages else context.new_page()
                context.on("request", observe_request)
                page.goto(self.MEMBER_URL, wait_until="domcontentloaded")
                page.bring_to_front()
                deadline = monotonic() + self._timeout_seconds
                while not token_ready.is_set() and monotonic() < deadline:
                    stored_token = _token_from_browser_storage(context)
                    if stored_token:
                        captured_token = stored_token
                        token_ready.set()
                        break
                    page.wait_for_timeout(1000)
                if not token_ready.is_set():
                    raise TimeoutError("BOWL.com sign-in was not completed")
                # Avoid a jarring open/close flash immediately after the final redirect.
                sleep(0.75)
            finally:
                if self._context is context:
                    context.close()
                    self._context = None
        return AuthSession(AuthState.SIGNED_IN, bearer_token=captured_token)

    def sign_out(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None


def available_sign_in_browsers() -> list[SignInBrowser]:
    """Return installed supported browsers in the preferred display order."""

    return [browser for browser in SignInBrowser if _browser_is_installed(browser)]


def _browser_is_installed(browser: SignInBrowser) -> bool:
    executable = "msedge.exe" if browser is SignInBrowser.EDGE else "chrome.exe"
    if which(executable):
        return True
    relative = (
        Path("Microsoft") / "Edge" / "Application" / "msedge.exe"
        if browser is SignInBrowser.EDGE
        else Path("Google") / "Chrome" / "Application" / "chrome.exe"
    )
    roots = [
        environ.get("PROGRAMFILES"),
        environ.get("PROGRAMFILES(X86)"),
        environ.get("LOCALAPPDATA"),
    ]
    return any((Path(root) / relative).is_file() for root in roots if root)


def _bearer_token_from_headers(headers: dict[str, str]) -> str:
    authorization = next(
        (value for key, value in headers.items() if key.casefold() == "authorization"), ""
    )
    scheme, separator, token = authorization.partition(" ")
    if separator and scheme.casefold() == "bearer" and token.strip():
        return token.strip()
    return ""


def _token_from_browser_storage(context) -> str:
    """Find an OIDC access token in the app-owned browser profile.

    BOWL.com currently stores its signed-in OIDC session in browser storage.
    Reading that session lets the desktop app notice a completed sign-in without
    requiring the user to run a member search. Values are inspected in memory
    and are never logged or persisted by this application.
    """

    values: list[object] = []
    try:
        for origin in context.storage_state().get("origins", []):
            values.extend(item.get("value", "") for item in origin.get("localStorage", []))
    except Exception:
        pass
    for page in context.pages:
        try:
            values.extend(
                page.evaluate(
                    """() => [
                        ...Object.values(localStorage),
                        ...Object.values(sessionStorage)
                    ]"""
                )
            )
        except Exception:
            continue
    return _bearer_token_from_storage_values(values)


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
