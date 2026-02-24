# services/ingestion_service/storage/gcs_raw.py
import json
import os
from datetime import datetime, timezone
from google.cloud import storage

def _bucket_name() -> str:
    b = os.getenv("RAW_GCS_BUCKET")
    if not b:
        raise RuntimeError("RAW_GCS_BUCKET is not set")
    return b

def write_raw_json(platform: str, account_id: str, window_start: datetime, window_end: datetime, request_id: str, payload: dict) -> str:
    client = storage.Client()
    bucket = client.bucket(_bucket_name())

    day = window_start.astimezone(timezone.utc).strftime("%Y-%m-%d")
    ws = window_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    we = window_end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    path = f"raw/{platform}/{account_id}/{day}/{ws}__{we}__{request_id}.json"
    blob = bucket.blob(path)
    blob.upload_from_string(json.dumps(payload, ensure_ascii=False), content_type="application/json")
    return f"gs://{_bucket_name()}/{path}"