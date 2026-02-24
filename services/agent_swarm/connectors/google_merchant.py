# services/agent_swarm/connectors/google_merchant.py
"""
Google Merchant Center Connector.

Wraps the Content API v2.1 to push products from our `products` table
into Google Merchant Center for Shopping ads.

Capabilities:
  - Single product upsert (insert/update)
  - Batch upsert for all workspace products
  - Pull approval status back from Merchant Center
  - Identify and report disapproval reasons
  - Sync status to merchant_center_products table
  - Delete (expire) removed products

Google Content API docs:
  https://developers.google.com/shopping-content/reference/rest/v2.1/products
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Internal imports
# ---------------------------------------------------------------------------
from services.agent_swarm.connectors.google import GoogleConnector


CONTENT_API_BASE = "https://shoppingcontent.googleapis.com/content/v2.1"


class MerchantCenterConnector:
    """
    Thin connector around the Google Content API v2.1.

    Constructed from a GoogleConnector (which already handles OAuth2
    token refresh) so we never duplicate credential logic.
    """

    def __init__(self, google_connector: GoogleConnector):
        self.gc = google_connector
        self.merchant_id = (
            google_connector.merchant_id
            or google_connector.connection.get("merchant_id", "")
        )
        if not self.merchant_id:
            raise ValueError(
                "merchant_id is required to use MerchantCenterConnector. "
                "Set it on the google_auth_tokens row or platform_connections."
            )

    # ------------------------------------------------------------------
    # Auth helpers (delegate to GoogleConnector)
    # ------------------------------------------------------------------

    def _headers(self) -> dict:
        token = self.gc._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Product schema builder
    # ------------------------------------------------------------------

    def _build_product_body(self, product: dict) -> dict:
        """
        Convert our `products` table row → Merchant Center product resource.

        Required fields for Shopping:
          offerId, title, description, link, imageLink, price,
          availability, condition, brand, contentLanguage, targetCountry, channel
        """
        price = product.get("price") or product.get("sale_price") or 0
        currency = product.get("currency", "INR")

        # Prefer main image, fall back to first extra image
        image_link = ""
        images = product.get("images") or []
        if isinstance(images, str):
            try:
                images = json.loads(images)
            except Exception:
                images = []
        if images:
            image_link = images[0] if isinstance(images[0], str) else images[0].get("url", "")

        additional_images = []
        for img in images[1:5]:  # Merchant Center allows up to 10 extras
            url = img if isinstance(img, str) else img.get("url", "")
            if url:
                additional_images.append({"link": url})

        # Offer ID: prefer SKU, fall back to UUID
        offer_id = product.get("sku") or str(product.get("id", ""))

        body = {
            "offerId": offer_id,
            "title": product.get("name", ""),
            "description": (
                product.get("description", "") or product.get("short_description", "")
            )[:5000],  # MC limit
            "link": product.get("url", ""),
            "imageLink": image_link,
            "price": {
                "value": str(price),
                "currency": currency,
            },
            "availability": "in stock" if product.get("in_stock", True) else "out of stock",
            "condition": "new",
            "brand": product.get("brand", "") or product.get("workspace_name", ""),
            "contentLanguage": "en",
            "targetCountry": product.get("target_country", "IN"),
            "channel": "online",
            "expirationDate": (
                datetime.now(timezone.utc) + timedelta(days=28)
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),  # Re-sync before 30-day auto-expiry
        }

        if additional_images:
            body["additionalImageLinks"] = [img["link"] for img in additional_images]

        # GTIN / MPN if available
        gtin = product.get("gtin") or product.get("barcode")
        if gtin:
            body["gtin"] = str(gtin)

        mpn = product.get("sku")
        if mpn:
            body["mpn"] = str(mpn)

        # Category (Google product taxonomy ID)
        google_category = product.get("google_product_category")
        if google_category:
            body["googleProductCategory"] = str(google_category)

        # Sale price
        sale_price = product.get("sale_price")
        if sale_price and sale_price < price:
            body["salePrice"] = {
                "value": str(sale_price),
                "currency": currency,
            }

        return body

    # ------------------------------------------------------------------
    # Single product operations
    # ------------------------------------------------------------------

    def upsert_product(self, product: dict) -> dict:
        """
        Insert or update one product in Merchant Center.

        Returns:
            {
              "mc_product_id": "online:en:IN:SKU123",
              "mc_offer_id": "SKU123",
              "status": "pending|approved|disapproved",
              "error": None | "error message",
            }
        """
        body = self._build_product_body(product)
        offer_id = body["offerId"]

        url = f"{CONTENT_API_BASE}/{self.merchant_id}/products"
        try:
            r = requests.post(
                url,
                headers=self._headers(),
                json=body,
                timeout=30,
            )
            if r.ok:
                data = r.json()
                return {
                    "mc_product_id": data.get("id", ""),
                    "mc_offer_id": offer_id,
                    "status": "pending",  # MC reviews async; starts as pending
                    "raw": data,
                    "error": None,
                }
            else:
                err = r.json() if r.content else {"message": r.text}
                return {
                    "mc_product_id": "",
                    "mc_offer_id": offer_id,
                    "status": "error",
                    "raw": err,
                    "error": _extract_mc_error(err),
                }
        except Exception as e:
            return {
                "mc_product_id": "",
                "mc_offer_id": offer_id,
                "status": "error",
                "raw": {},
                "error": str(e),
            }

    def get_product_status(self, mc_product_id: str) -> dict:
        """
        Fetch the current approval status of a product from Merchant Center.

        Returns:
            {
              "status": "approved|disapproved|expiring|pending",
              "disapproval_reasons": [...],
              "destinations": {...},
              "expires_at": "ISO timestamp or None",
            }
        """
        url = f"{CONTENT_API_BASE}/{self.merchant_id}/productstatuses/{mc_product_id}"
        try:
            r = requests.get(url, headers=self._headers(), timeout=20)
            if not r.ok:
                return {"status": "unknown", "disapproval_reasons": [], "destinations": {}}

            data = r.json()
            dest_statuses = data.get("destinationStatuses", [])

            # Aggregate across destinations
            all_approved = all(
                d.get("status") in ("approved", "unaffected")
                for d in dest_statuses
            )
            any_disapproved = any(
                d.get("status") == "disapproved"
                for d in dest_statuses
            )

            if any_disapproved:
                agg_status = "disapproved"
            elif all_approved and dest_statuses:
                agg_status = "approved"
            else:
                agg_status = "pending"

            # Collect disapproval reasons
            disapproval_reasons = []
            item_issues = data.get("itemLevelIssues", [])
            for issue in item_issues:
                disapproval_reasons.append({
                    "code": issue.get("code", ""),
                    "description": issue.get("description", ""),
                    "resolution": issue.get("resolution", ""),
                    "servability": issue.get("servability", ""),
                    "destination": issue.get("destination", ""),
                })

            # Destination map
            destinations = {
                d.get("destination", "unknown"): d.get("status", "unknown")
                for d in dest_statuses
            }

            # Expiry date
            expires_at = None
            if data.get("expirationDate"):
                expires_at = data["expirationDate"]

            return {
                "status": agg_status,
                "disapproval_reasons": disapproval_reasons,
                "destinations": destinations,
                "expires_at": expires_at,
                "raw": data,
            }
        except Exception as e:
            return {
                "status": "error",
                "disapproval_reasons": [],
                "destinations": {},
                "error": str(e),
            }

    def delete_product(self, mc_product_id: str) -> bool:
        """Remove a product from Merchant Center."""
        url = f"{CONTENT_API_BASE}/{self.merchant_id}/products/{mc_product_id}"
        try:
            r = requests.delete(url, headers=self._headers(), timeout=20)
            return r.status_code in (200, 204, 404)  # 404 = already gone = OK
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Batch operations
    # ------------------------------------------------------------------

    def batch_upsert(self, products: list[dict]) -> list[dict]:
        """
        Push up to 1000 products in a single custombatch call.
        Splits into chunks of 250 for safety.

        Returns list of result dicts (one per product), same shape as upsert_product().
        """
        results = []
        chunk_size = 250

        for chunk_start in range(0, len(products), chunk_size):
            chunk = products[chunk_start: chunk_start + chunk_size]
            entries = []
            for i, product in enumerate(chunk):
                body = self._build_product_body(product)
                entries.append({
                    "batchId": chunk_start + i,
                    "merchantId": int(self.merchant_id),
                    "method": "insert",
                    "product": body,
                })

            url = f"{CONTENT_API_BASE}/products/custombatch"
            try:
                r = requests.post(
                    url,
                    headers=self._headers(),
                    json={"entries": entries},
                    timeout=60,
                )
                if not r.ok:
                    # Entire batch failed — mark all as error
                    err_msg = _extract_mc_error(r.json() if r.content else {})
                    for product in chunk:
                        offer_id = product.get("sku") or str(product.get("id", ""))
                        results.append({
                            "mc_product_id": "",
                            "mc_offer_id": offer_id,
                            "status": "error",
                            "error": err_msg,
                        })
                    continue

                batch_data = r.json()
                for entry in batch_data.get("entries", []):
                    batch_id = entry.get("batchId", 0)
                    product = chunk[batch_id - chunk_start]
                    offer_id = product.get("sku") or str(product.get("id", ""))

                    if "errors" in entry:
                        err_msg = _extract_mc_error(entry["errors"])
                        results.append({
                            "mc_product_id": "",
                            "mc_offer_id": offer_id,
                            "status": "error",
                            "error": err_msg,
                        })
                    else:
                        mc_product = entry.get("product", {})
                        results.append({
                            "mc_product_id": mc_product.get("id", ""),
                            "mc_offer_id": offer_id,
                            "status": "pending",
                            "error": None,
                        })

            except Exception as e:
                for product in chunk:
                    offer_id = product.get("sku") or str(product.get("id", ""))
                    results.append({
                        "mc_product_id": "",
                        "mc_offer_id": offer_id,
                        "status": "error",
                        "error": str(e),
                    })

        return results

    def batch_get_statuses(self, mc_product_ids: list[str]) -> dict[str, dict]:
        """
        Fetch approval statuses for multiple products in one custombatch call.

        Returns: { mc_product_id → status_dict }
        """
        if not mc_product_ids:
            return {}

        entries = [
            {
                "batchId": i,
                "merchantId": int(self.merchant_id),
                "method": "get",
                "productId": pid,
            }
            for i, pid in enumerate(mc_product_ids)
        ]

        url = f"{CONTENT_API_BASE}/productstatuses/custombatch"
        statuses: dict[str, dict] = {}
        try:
            r = requests.post(
                url,
                headers=self._headers(),
                json={"entries": entries},
                timeout=60,
            )
            if not r.ok:
                return {}

            for entry in r.json().get("entries", []):
                batch_id = entry.get("batchId", 0)
                pid = mc_product_ids[batch_id]

                if "errors" in entry:
                    statuses[pid] = {
                        "status": "error",
                        "disapproval_reasons": [],
                        "destinations": {},
                    }
                    continue

                ps = entry.get("productStatus", {})
                dest_statuses = ps.get("destinationStatuses", [])
                all_approved = all(
                    d.get("status") in ("approved", "unaffected") for d in dest_statuses
                )
                any_disapproved = any(
                    d.get("status") == "disapproved" for d in dest_statuses
                )

                if any_disapproved:
                    agg = "disapproved"
                elif all_approved and dest_statuses:
                    agg = "approved"
                else:
                    agg = "pending"

                disapproval_reasons = [
                    {
                        "code": iss.get("code", ""),
                        "description": iss.get("description", ""),
                        "resolution": iss.get("resolution", ""),
                    }
                    for iss in ps.get("itemLevelIssues", [])
                ]

                statuses[pid] = {
                    "status": agg,
                    "disapproval_reasons": disapproval_reasons,
                    "destinations": {
                        d.get("destination", ""): d.get("status", "")
                        for d in dest_statuses
                    },
                    "expires_at": ps.get("expirationDate"),
                }
        except Exception as e:
            print(f"MerchantCenterConnector.batch_get_statuses error: {e}")

        return statuses

    # ------------------------------------------------------------------
    # High-level sync (products table → MC + sync status back to DB)
    # ------------------------------------------------------------------

    def sync_workspace_products(
        self, workspace_id: str, db_conn=None
    ) -> dict:
        """
        Full sync:
          1. Load all active products for workspace from DB
          2. Batch-upsert to Merchant Center
          3. Write results to merchant_center_products table
          4. Log the run in google_shopping_feed_log

        Returns summary dict:
            {
              "pushed": N,
              "pending": N,
              "errors": N,
              "error_details": [...],
              "log_id": "UUID",
            }
        """
        import psycopg2.extras
        from services.agent_swarm.config import DATABASE_URL

        close_conn = False
        if db_conn is None:
            import psycopg2
            db_conn = psycopg2.connect(DATABASE_URL)
            close_conn = True

        try:
            cur = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # ── Create feed log entry ─────────────────────────────────────
            cur.execute(
                """
                INSERT INTO google_shopping_feed_log
                    (workspace_id, merchant_id, status)
                VALUES (%s, %s, 'running')
                RETURNING id
                """,
                (workspace_id, self.merchant_id),
            )
            log_id = str(cur.fetchone()["id"])
            db_conn.commit()

            # ── Load products ─────────────────────────────────────────────
            cur.execute(
                """
                SELECT p.*, w.name AS workspace_name, w.currency
                FROM products p
                JOIN workspaces w ON w.id = p.workspace_id
                WHERE p.workspace_id = %s
                  AND p.is_active = TRUE
                  AND p.url IS NOT NULL
                  AND p.url != ''
                ORDER BY p.created_at
                """,
                (workspace_id,),
            )
            products = [dict(r) for r in cur.fetchall()]

            if not products:
                _finish_log(
                    cur, db_conn, log_id, "success",
                    pushed=0, approved=0, disapproved=0, pending=0, errors=[]
                )
                return {"pushed": 0, "pending": 0, "errors": 0, "error_details": [], "log_id": log_id}

            # ── Batch upsert ──────────────────────────────────────────────
            push_results = self.batch_upsert(products)

            product_map = {
                (p.get("sku") or str(p["id"])): p
                for p in products
            }

            pushed = len(push_results)
            error_details = []
            mc_ids_to_check = []

            for res in push_results:
                if res.get("error"):
                    error_details.append({
                        "offer_id": res["mc_offer_id"],
                        "error": res["error"],
                    })
                elif res.get("mc_product_id"):
                    mc_ids_to_check.append(res["mc_product_id"])

            # ── Upsert merchant_center_products rows ─────────────────────
            now = datetime.now(timezone.utc)
            for res in push_results:
                product = product_map.get(res["mc_offer_id"])
                if not product:
                    continue
                product_id = str(product["id"])
                expires_at = (now + timedelta(days=28)).isoformat()

                if res.get("error"):
                    # Record the error attempt
                    cur.execute(
                        """
                        INSERT INTO merchant_center_products
                            (workspace_id, product_id, merchant_id,
                             mc_product_id, mc_offer_id,
                             title, status, disapproval_reasons,
                             last_synced_at, expires_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 'error', %s, NOW(), %s)
                        ON CONFLICT (workspace_id, merchant_id, mc_offer_id)
                        DO UPDATE SET
                            status = 'error',
                            disapproval_reasons = EXCLUDED.disapproval_reasons,
                            last_synced_at = NOW(),
                            updated_at = NOW()
                        """,
                        (
                            workspace_id, product_id, self.merchant_id,
                            "", res["mc_offer_id"],
                            product.get("name", ""),
                            json.dumps([{"code": "push_error", "description": res["error"]}]),
                            expires_at,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO merchant_center_products
                            (workspace_id, product_id, merchant_id,
                             mc_product_id, mc_offer_id,
                             title, status, last_synced_at, expires_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 'pending', NOW(), %s)
                        ON CONFLICT (workspace_id, merchant_id, mc_offer_id)
                        DO UPDATE SET
                            mc_product_id = EXCLUDED.mc_product_id,
                            status = 'pending',
                            last_synced_at = NOW(),
                            expires_at = EXCLUDED.expires_at,
                            updated_at = NOW()
                        """,
                        (
                            workspace_id, product_id, self.merchant_id,
                            res["mc_product_id"], res["mc_offer_id"],
                            product.get("name", ""),
                            expires_at,
                        ),
                    )
            db_conn.commit()

            # ── Finish log ────────────────────────────────────────────────
            _finish_log(
                cur, db_conn, log_id, "success" if not error_details else "partial",
                pushed=pushed,
                approved=0,  # Status is async; check later via refresh_statuses
                disapproved=0,
                pending=pushed - len(error_details),
                errors=error_details,
            )

            return {
                "pushed": pushed,
                "pending": pushed - len(error_details),
                "errors": len(error_details),
                "error_details": error_details,
                "log_id": log_id,
            }

        except Exception as e:
            print(f"MerchantCenterConnector.sync_workspace_products error: {e}")
            return {
                "pushed": 0, "pending": 0, "errors": 1,
                "error_details": [{"error": str(e)}],
                "log_id": None,
            }
        finally:
            if close_conn:
                db_conn.close()

    def refresh_product_statuses(self, workspace_id: str, db_conn=None) -> dict:
        """
        Pull current approval statuses from MC for all products in the DB
        and write them back to merchant_center_products.

        Run this ~1 hour after sync_workspace_products() so MC has
        had time to review the products.

        Returns: { "updated": N, "approved": N, "disapproved": N, "pending": N }
        """
        import psycopg2.extras
        from services.agent_swarm.config import DATABASE_URL

        close_conn = False
        if db_conn is None:
            import psycopg2
            db_conn = psycopg2.connect(DATABASE_URL)
            close_conn = True

        try:
            cur = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # Fetch all products with a real MC ID
            cur.execute(
                """
                SELECT id, mc_product_id, mc_offer_id
                FROM merchant_center_products
                WHERE workspace_id = %s
                  AND merchant_id = %s
                  AND mc_product_id != ''
                  AND status NOT IN ('error')
                """,
                (workspace_id, self.merchant_id),
            )
            rows = cur.fetchall()
            if not rows:
                return {"updated": 0, "approved": 0, "disapproved": 0, "pending": 0}

            mc_ids = [row["mc_product_id"] for row in rows]
            statuses = self.batch_get_statuses(mc_ids)

            approved = disapproved = pending = updated = 0

            for row in rows:
                pid = row["mc_product_id"]
                status_data = statuses.get(pid)
                if not status_data:
                    continue

                status = status_data["status"]
                reasons = status_data.get("disapproval_reasons", [])
                destinations = status_data.get("destinations", {})
                expires_at = status_data.get("expires_at")

                cur.execute(
                    """
                    UPDATE merchant_center_products
                    SET status = %s,
                        disapproval_reasons = %s,
                        destinations = %s,
                        expires_at = %s,
                        last_synced_at = NOW(),
                        updated_at = NOW()
                    WHERE mc_product_id = %s
                      AND workspace_id = %s
                    """,
                    (
                        status,
                        json.dumps(reasons),
                        json.dumps(destinations),
                        expires_at,
                        pid,
                        workspace_id,
                    ),
                )
                updated += 1
                if status == "approved":
                    approved += 1
                elif status == "disapproved":
                    disapproved += 1
                else:
                    pending += 1

            db_conn.commit()
            return {
                "updated": updated,
                "approved": approved,
                "disapproved": disapproved,
                "pending": pending,
            }

        except Exception as e:
            print(f"MerchantCenterConnector.refresh_product_statuses error: {e}")
            return {"updated": 0, "approved": 0, "disapproved": 0, "pending": 0}
        finally:
            if close_conn:
                db_conn.close()

    def get_disapproval_summary(self, workspace_id: str, db_conn=None) -> list[dict]:
        """
        Return all disapproved products with reasons for human review.

        Returns:
            [
              {
                "product_name": "...",
                "offer_id": "...",
                "mc_product_id": "...",
                "reasons": [{"code": "...", "description": "...", "resolution": "..."}],
              },
              ...
            ]
        """
        import psycopg2.extras
        from services.agent_swarm.config import DATABASE_URL

        close_conn = False
        if db_conn is None:
            import psycopg2
            db_conn = psycopg2.connect(DATABASE_URL)
            close_conn = True

        try:
            cur = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """
                SELECT mcp.mc_product_id, mcp.mc_offer_id, mcp.title,
                       mcp.disapproval_reasons, mcp.destinations
                FROM merchant_center_products mcp
                WHERE mcp.workspace_id = %s
                  AND mcp.merchant_id = %s
                  AND mcp.status = 'disapproved'
                ORDER BY mcp.updated_at DESC
                """,
                (workspace_id, self.merchant_id),
            )
            rows = cur.fetchall()

            results = []
            for row in rows:
                reasons = row["disapproval_reasons"]
                if isinstance(reasons, str):
                    try:
                        reasons = json.loads(reasons)
                    except Exception:
                        reasons = []
                results.append({
                    "product_name": row["title"],
                    "offer_id": row["mc_offer_id"],
                    "mc_product_id": row["mc_product_id"],
                    "reasons": reasons or [],
                    "destinations": row["destinations"] or {},
                })
            return results

        except Exception as e:
            print(f"MerchantCenterConnector.get_disapproval_summary error: {e}")
            return []
        finally:
            if close_conn:
                db_conn.close()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_merchant_connector(workspace_id: str) -> Optional["MerchantCenterConnector"]:
    """
    Build a MerchantCenterConnector for the workspace.

    Loads the workspace's Google platform_connection, builds a
    GoogleConnector from it, then wraps it in MerchantCenterConnector.

    Returns None if no Google connection with merchant_id exists.
    """
    from services.agent_swarm.core.workspace import (
        get_workspace, get_primary_connection,
    )

    workspace = get_workspace(workspace_id)
    if not workspace:
        return None

    conn = get_primary_connection(workspace, "google")
    if not conn:
        return None

    if not conn.get("merchant_id"):
        print(f"No merchant_id on Google connection for workspace {workspace_id}")
        return None

    gc = GoogleConnector(conn, workspace)
    return MerchantCenterConnector(gc)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_mc_error(err: dict) -> str:
    """Extract a human-readable error string from a Content API error response."""
    if not err:
        return "Unknown Merchant Center error"
    errors = err.get("errors", {}).get("errors", []) or err.get("error", {}).get("errors", [])
    if errors:
        return "; ".join(e.get("message", str(e)) for e in errors[:3])
    msg = err.get("message") or err.get("error", {}).get("message", "")
    return msg or str(err)[:200]


def _finish_log(
    cur, db_conn, log_id: str,
    status: str, pushed: int, approved: int,
    disapproved: int, pending: int, errors: list
):
    """Write final counts + status to google_shopping_feed_log."""
    cur.execute(
        """
        UPDATE google_shopping_feed_log
        SET products_pushed = %s,
            products_approved = %s,
            products_disapproved = %s,
            products_pending = %s,
            errors = %s,
            finished_at = NOW(),
            status = %s
        WHERE id = %s
        """,
        (pushed, approved, disapproved, pending, json.dumps(errors), status, log_id),
    )
    db_conn.commit()
