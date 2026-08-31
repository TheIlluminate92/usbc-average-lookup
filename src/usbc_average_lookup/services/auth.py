import json
from dataclasses import dataclass, field
from enum import StrEnum
from os import environ
from pathlib import Path
from shutil import rmtree, which
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
    BRAVE = "Brave"

    @property
    def channel(self) -> str | None:
        if self is SignInBrowser.EDGE:
            return "msedge"
        if self is SignInBrowser.CHROME:
            return "chrome"
        return None

    @property
    def profile_name(self) -> str:
        return {
            SignInBrowser.EDGE: "browser-profile",
            SignInBrowser.CHROME: "browser-profile-chrome",
            SignInBrowser.BRAVE: "browser-profile-brave",
        }[self]


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
            # Check a remembered BOWL.com session without showing a browser first.
            # This avoids the visible open-and-immediately-close flash when the
            # saved session is still valid.
            captured_token = self._existing_token(playwright)
            if captured_token:
                return AuthSession(AuthState.SIGNED_IN, bearer_token=captured_token)

            context = self._launch_context(playwright, headless=False)
            self._context = context
            try:
                context.on("request", observe_request)
                page = _single_sign_in_page(context)
                page.bring_to_front()
                page.goto(self.MEMBER_URL, wait_until="domcontentloaded")
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

    def _launch_context(self, playwright, *, headless: bool):
        options = {
            "headless": headless,
            "reduced_motion": "reduce",
            "no_viewport": True,
        }
        if self.browser.channel:
            options["channel"] = self.browser.channel
        else:
            executable = _browser_executable_path(self.browser)
            if executable is None:
                raise RuntimeError(f"{self.browser.value} is not installed")
            options["executable_path"] = str(executable)
        return playwright.chromium.launch_persistent_context(
            str(self._profile_path),
            **options,
        )

    def _existing_token(self, playwright) -> str:
        context = self._launch_context(playwright, headless=True)
        captured_token = ""

        def observe_request(request: "Request") -> None:
            nonlocal captured_token
            if request.url.startswith(self.API_PREFIX):
                captured_token = _bearer_token_from_headers(request.all_headers())

        try:
            context.on("request", observe_request)
            page = _single_sign_in_page(context)
            page.goto(self.MEMBER_URL, wait_until="domcontentloaded", timeout=30_000)
            # OIDC redirects and the first authorized API request can take more
            # than five seconds on a cold browser profile. Keep that work hidden
            # rather than falling back to a briefly visible browser too early.
            deadline = monotonic() + 15
            while monotonic() < deadline:
                token = captured_token or _token_from_browser_storage(context)
                if token:
                    return token
                page.wait_for_timeout(250)
            return ""
        except Exception:
            # A failed quiet check should not prevent a normal interactive sign-in.
            return ""
        finally:
            context.close()

    def sign_out(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None

    def forget_saved_login(self) -> None:
        """Remove only this app's profile for the selected browser."""

        self.sign_out()
        if self._profile_path.exists():
            rmtree(self._profile_path)


def available_sign_in_browsers() -> list[SignInBrowser]:
    """Return installed supported browsers in the preferred display order."""

    return [browser for browser in SignInBrowser if _browser_is_installed(browser)]


def _browser_is_installed(browser: SignInBrowser) -> bool:
    return _browser_executable_path(browser) is not None


def _browser_executable_path(browser: SignInBrowser) -> Path | None:
    executable, relative = {
        SignInBrowser.EDGE: (
            "msedge.exe",
            Path("Microsoft") / "Edge" / "Application" / "msedge.exe",
        ),
        SignInBrowser.CHROME: (
            "chrome.exe",
            Path("Google") / "Chrome" / "Application" / "chrome.exe",
        ),
        SignInBrowser.BRAVE: (
            "brave.exe",
            Path("BraveSoftware") / "Brave-Browser" / "Application" / "brave.exe",
        ),
    }[browser]
    discovered = which(executable)
    if discovered:
        return Path(discovered)
    roots = [
        environ.get("PROGRAMFILES"),
        environ.get("PROGRAMFILES(X86)"),
        environ.get("LOCALAPPDATA"),
    ]
    return next(
        (Path(root) / relative for root in roots if root and (Path(root) / relative).is_file()),
        None,
    )


def _single_sign_in_page(context):
    """Keep one predictable page instead of restoring tabs plus about:blank."""

    pages = list(context.pages)
    if not pages:
        return context.new_page()
    page = next(
        (candidate for candidate in reversed(pages) if candidate.url == "about:blank"),
        pages[-1],
    )
    for extra in pages:
        if extra is page:
            continue
        try:
            extra.close()
        except Exception:
            # A restored tab may already be closing during browser startup.
            pass
    return page


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
