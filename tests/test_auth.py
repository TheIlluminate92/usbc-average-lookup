from usbc_average_lookup.services.auth import (
    _bearer_token_from_headers,
    _bearer_token_from_storage_values,
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
