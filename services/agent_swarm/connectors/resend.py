"""
Resend ESP connector — wraps Resend REST API using requests.
Handles domain verification, email sending, and Svix webhook verification.
"""
import hashlib
import hmac
import time
import requests
from typing import Optional


class ResendConnector:
    BASE = "https://api.resend.com"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    def _get(self, path: str) -> dict:
        r = self.session.get(f"{self.BASE}{path}", timeout=15)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        r = self.session.post(f"{self.BASE}{path}", json=body, timeout=15)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str) -> bool:
        r = self.session.delete(f"{self.BASE}{path}", timeout=15)
        return r.ok

    # ── Domain management ────────────────────────────────────────────────────

    def list_domains(self) -> list:
        """GET /domains — returns list of domain objects."""
        return self._get("/domains").get("data", [])

    def create_domain(self, name: str) -> dict:
        """
        POST /domains — creates domain or fetches existing one if already registered.
        Returns {id, name, status, records: [{type, name, value, ttl, priority?}]}
        """
        r = self.session.post(f"{self.BASE}/domains", json={"name": name}, timeout=15)
        if r.ok:
            return r.json()
        # 403 = domain already exists in this Resend account; fetch it
        if r.status_code == 403:
            for d in self.list_domains():
                if d.get("name", "").lower() == name.lower():
                    return self.get_domain(d["id"])
        r.raise_for_status()
        return r.json()

    def get_domain(self, domain_id: str) -> dict:
        """
        GET /domains/{id}
        Returns {id, name, status, records: [...]}
        status: "not_started" | "pending" | "verified" | "failure"
        """
        return self._get(f"/domains/{domain_id}")

    def verify_domain(self, domain_id: str) -> dict:
        """
        POST /domains/{id}/verify — triggers Resend to re-check DNS records.
        Returns updated domain object with new status.
        """
        # Trigger the re-check (don't use _post — response body may be empty or vary)
        self.session.post(f"{self.BASE}/domains/{domain_id}/verify", timeout=15)
        # Always read the freshest status
        return self.get_domain(domain_id)

    def delete_domain(self, domain_id: str) -> bool:
        return self._delete(f"/domains/{domain_id}")

    # ── Email sending ────────────────────────────────────────────────────────

    def send_email(
        self,
        to: str,
        from_: str,
        subject: str,
        html: str,
        text: Optional[str] = None,
        reply_to: Optional[str] = None,
        headers: Optional[dict] = None,
    ) -> str:
        """
        POST /emails
        Returns the Resend message_id (str).
        """
        payload: dict = {
            "from":    from_,
            "to":      [to],
            "subject": subject,
            "html":    html,
        }
        if text:
            payload["text"] = text
        if reply_to:
            payload["reply_to"] = reply_to
        if headers:
            payload["headers"] = headers

        data = self._post("/emails", payload)
        return data.get("id", "")

    # ── Webhook verification (Svix) ──────────────────────────────────────────

    @staticmethod
    def verify_webhook(
        body: bytes,
        svix_id: str,
        svix_timestamp: str,
        svix_signature: str,
        secret: str,
    ) -> bool:
        """
        Verify Resend webhook using Svix signing.
        secret must be the raw webhook secret (starts with "whsec_").
        Strip the "whsec_" prefix and base64-decode to get the key bytes.
        """
        import base64
        try:
            # Strip prefix and decode key
            raw_secret = secret
            if raw_secret.startswith("whsec_"):
                raw_secret = raw_secret[len("whsec_"):]
            key = base64.b64decode(raw_secret)

            # Reject if timestamp is older than 5 minutes
            ts = int(svix_timestamp)
            if abs(time.time() - ts) > 300:
                return False

            # Signed content = "{svix_id}.{svix_timestamp}.{body}"
            signed = f"{svix_id}.{svix_timestamp}.".encode() + body
            expected = base64.b64encode(
                hmac.new(key, signed, hashlib.sha256).digest()
            ).decode()

            # svix_signature may contain multiple space-separated "v1,<sig>" entries
            for sig_entry in svix_signature.split(" "):
                if "," in sig_entry:
                    _, sig_val = sig_entry.split(",", 1)
                    if hmac.compare_digest(sig_val, expected):
                        return True
            return False
        except Exception:
            return False
