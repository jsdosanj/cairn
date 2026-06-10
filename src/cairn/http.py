"""Shared HTTP plumbing: retrying sessions, HTTPS enforcement, OAuth2 tokens.

Every provider talks to a REST API over flaky networks. Centralizing retry,
backoff, timeout, and TLS enforcement here means a new provider gets production
hardening for free and we enforce "HTTPS only" in exactly one place.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

try:  # urllib3 v1/v2 compatibility
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover
    from requests.packages.urllib3.util.retry import Retry  # type: ignore

logger = logging.getLogger(__name__)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_TIMEOUT = 30


class HttpError(Exception):
    """Raised for non-retryable HTTP failures after retries are exhausted."""


def require_https(url: str, name: str) -> None:
    """Refuse plaintext to anything but localhost. Credentials ride these URLs."""
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return
    if parsed.scheme in ("http", "") and parsed.hostname in _LOCAL_HOSTS:
        return
    raise ValueError(f"{name} must use HTTPS: {url}")


def build_session(
    retries: int = 3,
    backoff: float = 0.5,
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504),
    headers: Optional[dict[str, str]] = None,
) -> requests.Session:
    """A requests.Session with automatic retry/backoff and TLS verification on."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff,
        status_forcelist=status_forcelist,
        allowed_methods=frozenset(["GET", "POST", "PUT", "PATCH", "DELETE"]),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.verify = True
    session.headers.update({"Accept": "application/json"})
    if headers:
        session.headers.update(headers)
    return session


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    **kwargs: Any,
) -> Any:
    """Make a request and return parsed JSON, raising HttpError on failure."""
    resp = session.request(method, url, timeout=timeout, **kwargs)
    if resp.status_code >= 400:
        body = (resp.text or "")[:300]
        raise HttpError(f"{method} {url} -> {resp.status_code}: {body}")
    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError as e:
        raise HttpError(f"{method} {url} returned non-JSON body") from e


class OAuth2ClientCredentials:
    """Client-credentials token manager with in-memory caching + early refresh.

    Intune, CrowdStrike, Sophos, and Defender all use OAuth2 client-credentials.
    This caches the bearer token and refreshes ~60s before expiry so long fleet
    pulls never fail mid-stream on an expired token.
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        *,
        scope: Optional[str] = None,
        extra_data: Optional[dict[str, str]] = None,
        auth_in_header: bool = False,
        session: Optional[requests.Session] = None,
    ):
        require_https(token_url, "OAuth token_url")
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.extra_data = extra_data or {}
        self.auth_in_header = auth_in_header
        self.session = session or build_session()
        self._token: Optional[str] = None
        self._expires_at: float = 0.0

    def _fetch(self) -> None:
        data = {"grant_type": "client_credentials"}
        if self.scope:
            data["scope"] = self.scope
        data.update(self.extra_data)
        kwargs: dict[str, Any] = {"data": data}
        if self.auth_in_header:
            kwargs["auth"] = (self.client_id, self.client_secret)
        else:
            data["client_id"] = self.client_id
            data["client_secret"] = self.client_secret
        payload = request_json(self.session, "POST", self.token_url, **kwargs)
        token = payload.get("access_token")
        if not token:
            raise HttpError(f"Token endpoint returned no access_token: {payload}")
        self._token = token
        expires_in = int(payload.get("expires_in", 1800))
        self._expires_at = time.time() + max(expires_in - 60, 30)

    def token(self) -> str:
        if not self._token or time.time() >= self._expires_at:
            self._fetch()
        assert self._token is not None
        return self._token

    def bearer_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}"}
