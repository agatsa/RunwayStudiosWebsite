"""
Upload combined report (CSV) directly to FastAPI backend.
Handles 3 passes: campaign + device + hour_of_day
"""
import csv
import json
import math
import requests
from collections import defaultdict

FILE = r"C:\Users\rahul\Downloads\combined report.csv"
API  = "https://agent-swarm-771420308292.asia-south1.run.app/upload/excel-kpis"
AUTH = {"X-Cron-Token": "some_random_secret_123"}
WS   = "90279799-7dc4-411a-8cae-bcf418ad8fb1"
CHUNK = 500

DAY_NAMES = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]

# ── Parse CSV ──────────────────────────────────────────────────────────────────

def parse_num(v):
    try:
        return float(str(v).replace(",","").replace("%","").strip())
    except:
        return 0.0

rows = []
with open(FILE, encoding="utf-8-sig", newline="") as f:
    reader = csv.reader(f)
    headers = None
    for i, row in enumerate(reader):
        if i < 2:
            continue          # skip title + date range rows
        if headers is None:
            headers = [h.strip().lower() for h in row]
            print(f"Headers ({len(headers)}): {headers[:10]}...")
            continue
        if not any(row):
            continue
        r = dict(zip(headers, row))

        campaign = r.get("campaign","").strip()
        if not campaign or campaign.lower() in ("campaign","total"):
            continue

        device   = r.get("device","").strip()
        hour_raw = r.get("hour of the day","").strip()
        date_raw = r.get("day","").strip()

        try:
            hour = int(float(hour_raw))
        except:
            hour = 0

        # Parse impression share — Google exports as "30.99%" or " --"
        def parse_pct(v):
            s = str(v).strip()
            if s in ("--"," --",""):
                return None
            try:
                return float(s.replace("%","").strip())
            except:
                return None

        rows.append({
            "campaign_name":  campaign,
            "device":         device,
            "hour":           hour,
            "date":           date_raw,
            "spend":          parse_num(r.get("cost", 0)),
            "impressions":    round(parse_num(r.get("impr.", 0))),
            "clicks":         round(parse_num(r.get("clicks", 0))),
            "conversions":    parse_num(r.get("conversions", 0)),
            "revenue":        parse_num(r.get("conv. value", 0)),
            "impression_share": parse_pct(r.get("search impr. share","")),
        })

print(f"Parsed {len(rows)} rows")

# ── Aggregate helper ───────────────────────────────────────────────────────────

METRICS = ["spend","impressions","clicks","conversions","revenue"]

def aggregate(rows, key_fields):
    agg = {}
    for r in rows:
        key = "||".join(str(r.get(f,"")) for f in key_fields)
        if key not in agg:
            agg[key] = dict(r)
        else:
            for m in METRICS:
                agg[key][m] = (agg[key].get(m) or 0) + (r.get(m) or 0)
    return list(agg.values())

# ── Chunked upload ─────────────────────────────────────────────────────────────

def upload(entity_level, upload_rows, label):
    total_chunks = math.ceil(len(upload_rows) / CHUNK)
    total_upserted = 0
    for i in range(0, len(upload_rows), CHUNK):
        chunk = upload_rows[i:i+CHUNK]
        chunk_num = i // CHUNK + 1
        print(f"  {label}: chunk {chunk_num}/{total_chunks} ({len(chunk)} rows)...", end=" ")
        body = {
            "workspace_id": WS,
            "platform": "google",
            "entity_level": entity_level,
            "rows": chunk,
        }
        r = requests.post(API, json=body, headers=AUTH, timeout=60)
        if r.status_code != 200:
            print(f"ERROR {r.status_code}: {r.text[:200]}")
            return total_upserted
        data = r.json()
        upserted = data.get("rows_upserted", len(chunk))
        total_upserted += upserted
        print(f"ok ({upserted} upserted)")
    return total_upserted

# ── Pass 1: Campaign (aggregate by campaign + date) ───────────────────────────
campaign_rows = aggregate(rows, ["campaign_name", "date"])
print(f"\nPass 1 — Campaign: {len(campaign_rows)} rows")
n1 = upload("campaign", campaign_rows, "Campaign")

# ── Pass 2: Device (aggregate by campaign + device + date) ────────────────────
device_rows = aggregate([r for r in rows if r.get("device")], ["campaign_name","device","date"])
print(f"\nPass 2 — Device: {len(device_rows)} rows")
n2 = upload("device", device_rows, "Device")

# ── Pass 3: Hour of day (add day_of_week, aggregate by hour + date) ──────────
from datetime import datetime
def get_dow(date_str):
    try:
        return DAY_NAMES[datetime.strptime(date_str, "%Y-%m-%d").weekday() + 1 % 7]
    except:
        return "Monday"

hour_rows_raw = []
for r in rows:
    if r.get("hour") is not None:
        nr = dict(r)
        try:
            nr["day_of_week"] = DAY_NAMES[datetime.strptime(r["date"], "%Y-%m-%d").weekday()]
        except:
            nr["day_of_week"] = "Monday"
        hour_rows_raw.append(nr)

hour_rows = aggregate(hour_rows_raw, ["hour", "date"])
print(f"\nPass 3 — Hour of day: {len(hour_rows)} rows")
n3 = upload("hour_of_day", hour_rows, "Hour")

print(f"\nDone! Campaign: {n1}, Device: {n2}, Hour: {n3} rows upserted")
