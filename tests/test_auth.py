from usbc_average_lookup.services import auth
from usbc_average_lookup.services.auth import (
    SignInBrowser,
    _bearer_token_from_headers,
    _bearer_token_from_storage_values,
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


def test_available_browsers_filters_missing_installations(monkeypatch) -> None:
    monkeypatch.setattr(
        auth,
        "_browser_is_installed",
        lambda browser: browser is SignInBrowser.CHROME,
    )

    assert available_sign_in_browsers() == [SignInBrowser.CHROME]
