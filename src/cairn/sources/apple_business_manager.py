"""Apple Business Manager source via the modern ABM API (2024+).

Targets Apple's *modern* Apple Business Manager API (introduced 2024), which
speaks JSON:API and authenticates with OAuth2 client-credentials using a signed
client assertion (ES256 JWT). Devices come from the org devices endpoint
(`/v1/orgDevices`).

This source needs the `[apple]` extra (PyJWT + cryptography):

    pip install 'cairn-sync[apple]'

Auth flow: we sign a short-lived client-assertion JWT (ES256) with the ABM API
private key, exchange it at the token endpoint for a bearer access token, cache
it until shortly before expiry, then page through `/v1/orgDevices` following the
JSON:API `links.next` cursor.
"""

from __future__ import annotations

import logging
import time
from typing import Iterable, Optional

from ..models import NormalizedDevice
from ..http import build_session, request_json
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)

_API_BASE = "https://api-business.apple.com"
_TOKEN_URL = "https://account.apple.com/auth/oauth2/token"
_TOKEN_AUD = "https://account.apple.com/auth/oauth2/v1/token"
_SCOPE = "business.api"
_CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
_PAGE_SIZE = 100

# productFamily / deviceType -> normalized OS name.
_OS_BY_FAMILY = {
    "Mac": "macOS",
    "iPhone": "iOS",
    "iPad": "iPadOS",
    "AppleTV": "tvOS",
}
# productFamily / deviceType -> normalized asset_type.
_ASSET_BY_FAMILY = {
    "Mac": "computer",
    "iPhone": "mobile",
    "iPad": "mobile",
}


class AppleBusinessManagerSource(DeviceSource):
    key = "apple_bm"
    display_name = "Apple Business Manager"

    def validate_config(self) -> None:
        missing = []
        if not self.config.get("client_id"):
            missing.append("client_id")
        if not self.config.get("key_id"):
            missing.append("key_id")
        if not (self.config.get("private_key") or self.config.get("private_key_file")):
            missing.append("private_key (or private_key_file)")
        if missing:
            raise SourceConfigError(
                f"{self.display_name} missing required config: {', '.join(missing)}"
            )

    def setup(self) -> None:
        self.client_id = self.config["client_id"]
        self.key_id = self.config["key_id"]

        key = self.config.get("private_key")
        if not key:
            path = self.config["private_key_file"]
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    key = fh.read()
            except OSError as e:
                raise SourceConfigError(
                    f"{self.display_name}: could not read private_key_file "
                    f"{path!r}: {e}"
                ) from e
        self.private_key = key

        self.api_base = (self.config.get("api_base") or _API_BASE).rstrip("/")
        self.token_url = self.config.get("token_url") or _TOKEN_URL
        self.scope = self.config.get("scope") or _SCOPE

        self.session = build_session()
        self._token: Optional[str] = None
        self._expires_at: float = 0.0

    # --- auth ------------------------------------------------------------
    def _get_access_token(self) -> str:
        """Mint (and cache) a bearer token via a signed ES256 client assertion.

        Kept deliberately small and side-effect-light so tests can monkeypatch
        it without standing up a real Apple token endpoint.
        """
        if self._token and time.time() < self._expires_at:
            return self._token

        try:
            import jwt  # PyJWT
        except ImportError as e:
            raise SourceConfigError(
                "Apple Business Manager needs PyJWT + cryptography: "
                "pip install 'cairn-sync[apple]'"
            ) from e

        now = int(time.time())
        claims = {
            "iss": self.client_id,
            "sub": self.client_id,
            "aud": _TOKEN_AUD,
            "iat": now,
            "exp": now + 1200,
            # Deterministic unique id; uuid/random aren't available here.
            "jti": f"{now}-{self.key_id}",
        }
        assertion = jwt.encode(
            claims,
            self.private_key,
            algorithm="ES256",
            headers={"alg": "ES256", "kid": self.key_id},
        )

        payload = request_json(
            self.session,
            "POST",
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_assertion_type": _CLIENT_ASSERTION_TYPE,
                "client_assertion": assertion,
                "scope": self.scope,
            },
        )
        token = (payload or {}).get("access_token")
        if not token:
            raise SourceConfigError(
                f"{self.display_name}: token endpoint returned no access_token"
            )
        expires_in = int((payload or {}).get("expires_in", 3600))
        self._token = token
        self._expires_at = now + max(expires_in - 60, 30)
        return token

    def _bearer_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_access_token()}"}

    # --- mapping ---------------------------------------------------------
    def _to_device(self, item: dict) -> Optional[NormalizedDevice]:
        """Map one JSON:API orgDevices resource to a NormalizedDevice."""
        if not isinstance(item, dict):
            logger.warning("Apple Business Manager: skipping non-dict device record")
            return None

        attrs = item.get("attributes")
        if not isinstance(attrs, dict):
            attrs = {}

        source_id = item.get("id")
        serial = attrs.get("serialNumber") or source_id
        if not serial:
            logger.warning(
                "Apple Business Manager: skipping device with no serial or id"
            )
            return None

        family = attrs.get("productFamily") or attrs.get("deviceType")
        os_name = _OS_BY_FAMILY.get(family)
        asset_type = _ASSET_BY_FAMILY.get(family, "computer")

        last_seen = attrs.get("addedToOrgDateTime") or attrs.get("updatedDateTime")

        return NormalizedDevice(
            serial=serial,
            source="apple_bm",
            source_id=source_id,
            asset_type=asset_type,
            os_name=os_name,
            model=attrs.get("deviceModel") or attrs.get("model"),
            manufacturer="Apple",
            last_seen=last_seen,
            extra={"abm": attrs},
            raw=item,
        )

    # --- data access -----------------------------------------------------
    def fetch_all(self) -> Iterable[NormalizedDevice]:
        url: Optional[str] = f"{self.api_base}/v1/orgDevices?limit={_PAGE_SIZE}"
        while url:
            payload = request_json(
                self.session, "GET", url, headers=self._bearer_header()
            )
            payload = payload or {}

            for item in payload.get("data", []) or []:
                device = self._to_device(item)
                if device is not None:
                    yield device

            links = payload.get("links")
            url = links.get("next") if isinstance(links, dict) else None
