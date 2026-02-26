"""
services/agent_swarm/connectors/shopify.py

Shopify public app connector.

Handles:
  - OAuth install URL generation
  - HMAC validation (OAuth callback + webhooks)
  - Authorization code exchange for access_token
  - Admin REST API product fetching (paginated)
  - Webhook registration
"""

import base64
import hashlib
import hmac as _hmac
import re
import urllib.parse
from typing import Optional

import requests as _requests


SHOPIFY_API_VERSION = "2024-01"


class ShopifyConnector:
    """Stateless helper — pass shop_domain + access_token per call."""

    # ── OAuth ──────────────────────────────────────────────────────────────

    @staticmethod
    def build_install_url(
        shop_domain: str,
        api_key: str,
        scopes: str,
        redirect_uri: str,
        state: str,
    ) -> str:
        """
        Build the Shopify OAuth authorization URL.
        Merchant is redirected here to grant permission to the app.
        """
        shop = _normalize_shop(shop_domain)
        params = urllib.parse.urlencode({
            "client_id": api_key,
            "scope":     scopes,
            "redirect_uri": redirect_uri,
            "state":     state,
            "grant_options[]": "per-user",
        })
        return f"https://{shop}/admin/oauth/authorize?{params}"

    @staticmethod
    def validate_oauth_hmac(params: dict, api_secret: str) -> bool:
        """
        Validate the HMAC on the OAuth callback query params.
        Shopify signs all params except 'hmac' itself.
        """
        received = params.get("hmac", "")
        # Build the message: sorted key=value pairs joined by &, excluding hmac
        sorted_params = "&".join(
            f"{k}={v}"
            for k, v in sorted(params.items())
            if k != "hmac"
        )
        expected = _hmac.new(
            api_secret.encode("utf-8"),
            sorted_params.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return _hmac.compare_digest(expected, received)

    @staticmethod
    def exchange_code(
        shop_domain: str,
        code: str,
        api_key: str,
        api_secret: str,
        redirect_uri: str,
    ) -> dict:
        """
        Exchange authorization code for a permanent access token.
        Returns: {access_token, scope}
        """
        shop = _normalize_shop(shop_domain)
        r = _requests.post(
            f"https://{shop}/admin/oauth/access_token",
            json={
                "client_id":     api_key,
                "client_secret": api_secret,
                "code":          code,
            },
            timeout=15,
        )
        r.raise_for_status()
        return r.json()  # {access_token, scope}

    # ── Shop info ──────────────────────────────────────────────────────────

    @staticmethod
    def get_shop_info(shop_domain: str, access_token: str) -> dict:
        """Return {name, email, domain, myshopify_domain} from /admin/api/shop.json"""
        shop = _normalize_shop(shop_domain)
        r = _requests.get(
            f"https://{shop}/admin/api/{SHOPIFY_API_VERSION}/shop.json",
            headers={"X-Shopify-Access-Token": access_token},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("shop", {})

    # ── Products ───────────────────────────────────────────────────────────

    @staticmethod
    def get_all_products(shop_domain: str, access_token: str) -> list[dict]:
        """
        Fetch ALL products from the store using Admin REST API with pagination.
        Uses Link header cursor-based pagination (Shopify standard).
        Returns raw Shopify product dicts (same shape as public /products.json).
        """
        shop = _normalize_shop(shop_domain)
        base_url = f"https://{shop}/admin/api/{SHOPIFY_API_VERSION}/products.json"
        headers = {"X-Shopify-Access-Token": access_token}

        products = []
        url = base_url
        params = {"limit": 250, "status": "active"}

        while url:
            r = _requests.get(url, headers=headers, params=params, timeout=30)
            if not r.ok:
                print(f"Shopify Admin API error {r.status_code}: {r.text[:200]}")
                break
            batch = r.json().get("products", [])
            products.extend(batch)

            # Follow Link header for next page
            url = _parse_next_link(r.headers.get("Link", ""))
            params = {}  # next URL already has params baked in

        print(f"Shopify Admin API: fetched {len(products)} products from {shop}")
        return products

    # ── Webhooks ───────────────────────────────────────────────────────────

    @staticmethod
    def register_webhook(
        shop_domain: str,
        access_token: str,
        topic: str,
        address: str,
    ) -> Optional[str]:
        """
        Register a webhook for a given topic.
        Returns webhook id (string) or None on failure.
        """
        shop = _normalize_shop(shop_domain)
        r = _requests.post(
            f"https://{shop}/admin/api/{SHOPIFY_API_VERSION}/webhooks.json",
            headers={"X-Shopify-Access-Token": access_token},
            json={"webhook": {"topic": topic, "address": address, "format": "json"}},
            timeout=10,
        )
        if r.ok:
            wid = r.json().get("webhook", {}).get("id")
            print(f"Registered Shopify webhook {topic} → {address} (id={wid})")
            return str(wid) if wid else None
        print(f"Shopify webhook registration failed {r.status_code}: {r.text[:200]}")
        return None

    @staticmethod
    def verify_webhook_hmac(raw_body: bytes, hmac_header: str, api_secret: str) -> bool:
        """
        Validate X-Shopify-Hmac-Sha256 on incoming webhook requests.
        raw_body must be the raw request bytes (NOT parsed JSON).
        """
        expected = base64.b64encode(
            _hmac.new(
                api_secret.encode("utf-8"),
                raw_body,
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        return _hmac.compare_digest(expected, hmac_header or "")


# ── Helpers ────────────────────────────────────────────────────────────────

def _normalize_shop(domain: str) -> str:
    """Ensure the domain is a bare host (no https://, no trailing slash)."""
    domain = domain.strip().rstrip("/")
    domain = re.sub(r"^https?://", "", domain)
    return domain


def _parse_next_link(link_header: str) -> Optional[str]:
    """
    Parse the Link header for rel="next" URL.
    Example: <https://...>; rel="next", <https://...>; rel="previous"
    """
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' in part:
            match = re.search(r'<([^>]+)>', part)
            if match:
                return match.group(1)
    return None
