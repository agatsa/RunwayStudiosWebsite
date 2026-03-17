"""
Google Play Developer API connector.
Uses a service account JSON for authentication.
Docs: https://developers.google.com/android-publisher
"""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False
    service_account = None
    build = None
    HttpError = Exception


class GooglePlayError(Exception):
    pass


class GooglePlayAPI:
    SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]

    def __init__(self, service_account_json: dict):
        """
        service_account_json: parsed dict from the downloaded .json key file
        """
        if not HAS_GOOGLE:
            raise GooglePlayError(
                "google-api-python-client not installed — "
                "run: pip install google-api-python-client google-auth"
            )
        self.sa_json = service_account_json
        self._service = None

    def _get_service(self):
        if self._service:
            return self._service
        creds = service_account.Credentials.from_service_account_info(
            self.sa_json, scopes=self.SCOPES
        )
        self._service = build(
            "androidpublisher", "v3",
            credentials=creds,
            cache_discovery=False,
        )
        return self._service

    def fetch_reviews(self, package_name: str, max_results: int = 100) -> list:
        """
        Fetch reviews from Google Play Developer API.
        Returns list of normalised review dicts.
        """
        svc = self._get_service()
        reviews = []
        page_token = None

        while len(reviews) < max_results:
            params = {
                "packageName": package_name,
                "maxResults": min(100, max_results - len(reviews)),
            }
            if page_token:
                params["pageToken"] = page_token
            try:
                result = svc.reviews().list(**params).execute()
            except HttpError as e:
                raise GooglePlayError(f"Play API error: {e.resp.status} {e.content[:200]}")

            for item in result.get("reviews", []):
                user_comment = None
                dev_comment = None
                for comment in item.get("comments", []):
                    if "userComment" in comment:
                        user_comment = comment["userComment"]
                    if "developerComment" in comment:
                        dev_comment = comment["developerComment"]

                if not user_comment:
                    continue

                # lastModified is a dict {"seconds": ..., "nanos": ...}
                last_mod = user_comment.get("lastModified", {})
                ts_seconds = last_mod.get("seconds")
                review_date = None
                if ts_seconds:
                    import datetime
                    review_date = datetime.datetime.utcfromtimestamp(
                        int(ts_seconds)
                    ).isoformat()

                reviews.append({
                    "review_id": item["reviewId"],
                    "author": item.get("authorName", "Anonymous"),
                    "rating": user_comment.get("starRating", 5),
                    "title": "",  # Play Store doesn't have review titles
                    "body": user_comment.get("text", ""),
                    "version": user_comment.get("appVersionName", ""),
                    "review_date": review_date,
                    "store": "playstore",
                    "has_reply": dev_comment is not None,
                })

            page_token = result.get("tokenPagination", {}).get("nextPageToken")
            if not page_token:
                break

        return reviews[:max_results]

    def reply_to_review(self, package_name: str, review_id: str, reply_text: str) -> bool:
        """Post or update a developer reply to a Play Store review."""
        svc = self._get_service()
        try:
            svc.reviews().reply(
                packageName=package_name,
                reviewId=review_id,
                body={"replyText": reply_text[:350]},  # Play Store max ~350 chars
            ).execute()
            return True
        except HttpError as e:
            raise GooglePlayError(f"Reply failed: {e.resp.status} {e.content[:200]}")

    def get_app_details(self, package_name: str) -> dict:
        """Fetch basic app edit info (requires an in-progress edit)."""
        # Most basic app info not available via androidpublisher without an edit.
        # Return minimal info from what we know.
        return {"package_name": package_name}
