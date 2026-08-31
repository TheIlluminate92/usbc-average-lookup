from usbc_average_lookup.services import auth
from usbc_average_lookup.services.auth import (
    SignInBrowser,
    _bearer_token_from_headers,
    _bearer_token_from_storage_values,
    _single_sign_in_page,
    available_sign_in_browsers,
)


def test_extracts_bearer_token_case_insensitively() -> None:
    assert _bearer_token_from_headers({"Authorization": "Bearer secret-value"}) == "secret-value"


def test_rejects_missing_or_non_bearer_authorization() -> None:
    assert _bearer_token_from_headers({}) == ""
    assert _bearer_token_from_headers({"authorization": "Basic abc"}) == ""


def test_extracts_oidc_access_token_from_browser_storage() -> None:
    values = [
        "ordinary preference",
        '{"profile":{"name":"Erik"},"access_token":"secret-value"}',
    ]

    assert _bearer_token_from_storage_values(values) == "secret-value"


def test_supported_browser_channels_and_profile_names() -> None:
    assert SignInBrowser.EDGE.channel == "msedge"
    assert SignInBrowser.EDGE.profile_name == "browser-profile"
    assert SignInBrowser.CHROME.channel == "chrome"
    assert SignInBrowser.CHROME.profile_name == "browser-profile-chrome"
    assert SignInBrowser.BRAVE.channel is None
    assert SignInBrowser.BRAVE.profile_name == "browser-profile-brave"


def test_available_browsers_filters_missing_installations(monkeypatch) -> None:
    monkeypatch.setattr(
        auth,
        "_browser_is_installed",
        lambda browser: browser is SignInBrowser.CHROME,
    )

    assert available_sign_in_browsers() == [SignInBrowser.CHROME]


def test_forget_saved_login_removes_only_selected_profile(tmp_path) -> None:
    selected_profile = tmp_path / "browser-profile"
    other_profile = tmp_path / "browser-profile-brave"
    selected_profile.mkdir()
    other_profile.mkdir()
    (selected_profile / "saved-session").write_text("private", encoding="utf-8")

    auth.BrowserAuthenticator(selected_profile).forget_saved_login()

    assert not selected_profile.exists()
    assert other_profile.exists()


def test_sign_in_reuses_blank_page_and_closes_restored_tabs() -> None:
    class FakePage:
        def __init__(self, url: str) -> None:
            self.url = url
            self.closed = False

        def close(self) -> None:
            self.closed = True

    restored = FakePage("https://webapps.bowl.com/USBCFindA/Home/Welcome")
    blank = FakePage("about:blank")
    context = type("FakeContext", (), {"pages": [restored, blank]})()

    selected = _single_sign_in_page(context)

    assert selected is blank
    assert restored.closed is True
    assert blank.closed is False
