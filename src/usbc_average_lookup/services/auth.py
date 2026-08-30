from dataclasses import dataclass
from enum import StrEnum


class AuthState(StrEnum):
    SIGNED_OUT = "Not signed in"
    SIGNED_IN = "Signed in"
    EXPIRED = "Session expired"


@dataclass(frozen=True, slots=True)
class AuthSession:
    state: AuthState
    display_name: str = ""


class BrowserAuthenticator:
    """Boundary for a future browser-based BOWL.com login flow.

    The implementation must send credentials only to BOWL.com, support MFA,
    retain no password, and expose only the session material needed by the API
    client. Persistent cookie storage requires a separate security review.
    """

    def sign_in(self) -> AuthSession:
        raise NotImplementedError("Browser-based BOWL.com sign-in is not configured yet")

    def sign_out(self) -> None:
        raise NotImplementedError("Browser-based BOWL.com sign-out is not configured yet")

