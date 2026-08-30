import pytest

from usbc_average_lookup.models import LookupResult, LookupStatus


def test_found_result_requires_average() -> None:
    with pytest.raises(ValueError, match="require an average"):
        LookupResult("John Smith", LookupStatus.FOUND)


def test_error_result_cannot_contain_average() -> None:
    with pytest.raises(ValueError, match="Only Found"):
        LookupResult("Jane Doe", LookupStatus.API_ERROR, average=170)
