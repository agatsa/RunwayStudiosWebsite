"""
Apple App Store Connect API connector.
Uses JWT (ES256) for authentication.
Docs: https://developer.apple.com/documentation/appstoreconnectapi
"""
import time
import json
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

ASC_BASE = "https://api.appstoreconnect.apple.com/v1"

try:
    import jwt as pyjwt
    HAS_JWT = True
except ImportError:
    HAS_JWT = False
    pyjwt = None


class AppStoreConnectError(Exception):
    pass


class AppStoreConnectAPI:
    def __init__(self, key_id: str, issuer_id: str, private_key_pem: str):
        """
        key_id:           Key ID from App Store Connect (e.g. ABC123XYZ)
        issuer_id:        Issuer ID (UUID format)
        private_key_pem:  Contents of .p8 file (with or without headers)
        """
        self.key_id = key_id
        self.issuer_id = issuer_id
        self.private_key_pem = private_key_pem.strip()
        self._token: Optional[str] = None
        self._token_exp: float = 0

    def _get_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_exp - 60:
            return self._token
        if not HAS_JWT:
            raise AppStoreConnectError("PyJWT not installed — run: pip install PyJWT cryptography")

        pem = self.private_key_pem
        # Normalise escaped newlines (sometimes pasted as \\n)
        if "\\n" in pem:
            pem = pem.replace("\\n", "\n")
        # Add PEM headers if missing
        if "-----BEGIN" not in pem:
            pem = f"-----BEGIN PRIVATE KEY-----\n{pem}\n-----END PRIVATE KEY-----"

        payload = {
            "iss": self.issuer_id,
            "iat": int(now),
            "exp": int(now) + 1200,  # 20 min max allowed by Apple
            "aud": "appstoreconnect-v1",
        }
        token = pyjwt.encode(
            payload,
            pem,
            algorithm="ES256",
            headers={"kid": self.key_id, "typ": "JWT"},
        )
        self._token = token
        self._token_exp = now + 1200
        return token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    def fetch_reviews(self, app_id: str, limit: int = 200) -> list:
        """
        Fetch customer reviews for an app.
        Returns list of normalised review dicts.
        """
        url = f"{ASC_BASE}/apps/{app_id}/customerReviews"
        params: dict = {"limit": min(limit, 200), "sort": "-createdDate"}
        reviews = []

        while url and len(reviews) < limit:
            try:
                r = requests.get(url, headers=self._headers(), params=params, timeout=30)
                r.raise_for_status()
                data = r.json()
            except requests.HTTPError as e:
                raise AppStoreConnectError(f"ASC API error: {e.response.status_code} {e.response.text[:200]}")

            for item in data.get("data", []):
                attrs = item.get("attributes", {})
                # Check if already replied
                reply_body = ""
                rel = item.get("relationships", {})
                resp = rel.get("response", {}).get("data")
                reviews.append({
                    "review_id": item["id"],
                    "author": attrs.get("reviewerNickname", "Anonymous"),
                    "rating": attrs.get("rating", 5),
                    "title": attrs.get("title", ""),
                    "body": attrs.get("body", ""),
                    "version": attrs.get("territoryCode", ""),
                    "review_date": attrs.get("createdDate"),
                    "store": "appstore",
                    "has_reply": resp is not None,
                })

            # Pagination — next page URL replaces params
            next_url = data.get("links", {}).get("next")
            url = next_url
            params = {}

        return reviews[:limit]

    def post_reply(self, review_id: str, reply_text: str) -> bool:
        """Post a developer reply to a customer review."""
        url = f"{ASC_BASE}/customerReviewResponses"
        body = {
            "data": {
                "type": "customerReviewResponses",
                "attributes": {"responseBody": reply_text[:5000]},
                "relationships": {
                    "review": {"data": {"type": "customerReviews", "id": review_id}}
                },
            }
        }
        try:
            r = requests.post(url, headers=self._headers(), json=body, timeout=30)
            r.raise_for_status()
            return True
        except requests.HTTPError as e:
            raise AppStoreConnectError(f"Reply failed: {e.response.status_code} {e.response.text[:200]}")

    def get_app_info(self, app_id: str) -> dict:
        """Fetch basic app metadata (name, bundleId)."""
        url = f"{ASC_BASE}/apps/{app_id}"
        params = {"fields[apps]": "name,bundleId,primaryLocale"}
        try:
            r = requests.get(url, headers=self._headers(), params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            attrs = data.get("data", {}).get("attributes", {})
            return {
                "name": attrs.get("name", ""),
                "bundle_id": attrs.get("bundleId", ""),
                "locale": attrs.get("primaryLocale", ""),
            }
        except requests.HTTPError as e:
            raise AppStoreConnectError(f"App info fetch failed: {e.response.status_code}")
