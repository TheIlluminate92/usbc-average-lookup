from usbc_average_lookup.services.auth import _bearer_token_from_headers


def test_extracts_bearer_token_case_insensitively() -> None:
    assert _bearer_token_from_headers({"Authorization": "Bearer secret-value"}) == "secret-value"


def test_rejects_missing_or_non_bearer_authorization() -> None:
    assert _bearer_token_from_headers({}) == ""
    assert _bearer_token_from_headers({"authorization": "Basic abc"}) == ""

