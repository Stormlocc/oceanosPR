"""In-memory CDSE Keycloak password-grant token client."""

from __future__ import annotations

import netrc
import time
from contextlib import nullcontext
from pathlib import Path

import httpx

from oceanos.domain import FailureCode
from oceanos.ingestion.fetch import AcquisitionError

REFRESH_BELOW_SECONDS = 300


class CdseTokenClient:
    """Read credentials only from netrc and retain access tokens only in memory."""

    def __init__(
        self,
        identity_url: str = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE",
        *,
        netrc_path: str | Path | None = None,
        timeout: float = 30,
        client: httpx.Client | None = None,
    ) -> None:
        self.identity_url = identity_url.rstrip("/")
        self.netrc_path = Path(netrc_path).expanduser() if netrc_path is not None else Path.home() / ".netrc"
        self.timeout = timeout
        self.client = client
        self._token: str | None = None
        self._expires_at = 0.0

    def __call__(self) -> str:
        return self.access_token()

    def access_token(self) -> str:
        """Return a token, refreshing whenever fewer than 300 seconds remain."""
        if self._token is not None and self._expires_at - time.monotonic() >= REFRESH_BELOW_SECONDS:
            return self._token
        try:
            credentials = netrc.netrc(str(self.netrc_path)).authenticators("cdse")
        except (OSError, netrc.NetrcParseError) as exc:
            raise AcquisitionError(FailureCode.AUTH_FAILED, "CDSE credentials could not be read from ~/.netrc") from exc
        if credentials is None or not credentials[0] or not credentials[2]:
            raise AcquisitionError(FailureCode.AUTH_FAILED, "missing ~/.netrc machine cdse credentials")
        username, _, password = credentials
        context = nullcontext(self.client) if self.client is not None else httpx.Client()
        try:
            with context as transport:
                response = transport.post(
                    f"{self.identity_url}/protocol/openid-connect/token",
                    data={
                        "client_id": "cdse-public", "grant_type": "password",
                        "username": username, "password": password,
                    },
                    timeout=self.timeout,
                )
        except httpx.HTTPError as exc:
            raise AcquisitionError(FailureCode.AUTH_FAILED, "CDSE token request failed") from exc
        if response.status_code != 200:
            raise AcquisitionError(FailureCode.AUTH_FAILED, f"CDSE token request rejected with HTTP {response.status_code}")
        try:
            document = response.json()
            token = document["access_token"]
            expires_in = float(document["expires_in"])
            if not isinstance(token, str) or not token or expires_in <= 0:
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise AcquisitionError(FailureCode.AUTH_FAILED, "CDSE token response is malformed") from exc
        self._token = token
        self._expires_at = time.monotonic() + expires_in
        return token
