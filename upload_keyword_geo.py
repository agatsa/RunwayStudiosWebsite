"""
Upload Keyword report and Geographic report directly to FastAPI backend.
"""
import csv, math, requests
from datetime import datetime

API  = "https://agent-swarm-771420308292.asia-south1.run.app/upload/excel-kpis"
AUTH = {"X-Cron-Token": "some_random_secret_123"}
WS   = "90279799-7dc4-411a-8cae-bcf418ad8fb1"
CHUNK = 500

def parse_num(v):
    try:
        return float(str(v).replace(",","").replace("%","").strip())
    except:
        return 0.0

def upload_chunks(entity_level, rows, label):
    total_chunks = math.ceil(len(rows) / CHUNK)
    total = 0
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i:i+CHUNK]
        n = i // CHUNK + 1
        print(f"  {label}: chunk {n}/{total_chunks} ({len(chunk)} rows)...", end=" ")
        r = requests.post(API, json={
            "workspace_id": WS,
            "platform": "google",
            "entity_level": entity_level,
            "rows": chunk,
        }, headers=AUTH, timeout=60)
        if r.status_code != 200:
            print(f"ERROR {r.status_code}: {r.text[:200]}")
            return total
        total += r.json().get("rows_upserted", len(chunk))
        print("ok")
    return total

# ── KEYWORDS ──────────────────────────────────────────────────────────────────

print("=== Parsing keyword report ===")
kw_rows = []
with open(r"C:\Users\rahul\Downloads\Combined Keyword Report.csv", encoding="utf-8-sig") as f:
    reader = csv.reader(f)
    headers = None
    for i, row in enumerate(reader):
        if i < 2: continue
        if headers is None:
            headers = [h.strip().lower() for h in row]
            print(f"Headers: {headers[:8]}...")
            continue
        if not any(row): continue
        r = dict(zip(headers, row))

        campaign = r.get("campaign","").strip()
        keyword  = r.get("search keyword","").strip()
        if not keyword or keyword.lower() in ("search keyword","keyword","total"):
            continue

        mt = r.get("search keyword match type","").strip().lower()
        if mt.startswith("exact"):   mt = "EXACT"
        elif mt.startswith("phrase"): mt = "PHRASE"
        else:                         mt = "BROAD"

        qs_raw = r.get("quality score","").strip()
        qs = None
        if qs_raw and qs_raw not in ("--"," --",""):
            try: qs = float(qs_raw)
            except: pass

        is_raw = r.get("search impr. share","").strip()
        imp_share = None
        if is_raw and is_raw not in ("--"," --",""):
            try: imp_share = float(is_raw.replace("%",""))
            except: pass

        kw_rows.append({
            "date":             r.get("day","").strip(),
            "campaign_name":    campaign,
            "ad_group_name":    r.get("ad group","").strip(),
            "keyword":          keyword,
            "match_type":       mt,
            "quality_score":    qs,
            "impression_share": str(imp_share) if imp_share is not None else None,
            "spend":            parse_num(r.get("cost",0)),
            "impressions":      round(parse_num(r.get("impr.",0))),
            "clicks":           round(parse_num(r.get("clicks",0))),
            "conversions":      parse_num(r.get("conversions",0)),
            "revenue":          parse_num(r.get("conv. value",0)),
        })

print(f"Parsed {len(kw_rows)} keyword rows")
n_kw = upload_chunks("keyword", kw_rows, "Keywords")
print(f"Keywords done: {n_kw} upserted\n")

# ── GEOGRAPHIC ────────────────────────────────────────────────────────────────

# Aggregate date for geo report (no Day column) — use last day of report period
GEO_DATE = "2026-02-28"

print("=== Parsing geographic report ===")
geo_rows = []
with open(r"C:\Users\rahul\Downloads\Geographic Report.csv", encoding="utf-8-sig") as f:
    reader = csv.reader(f)
    headers = None
    for i, row in enumerate(reader):
        if i < 2: continue
        if headers is None:
            headers = [h.strip().lower() for h in row]
            print(f"Headers: {headers[:8]}...")
            continue
        if not any(row): continue
        r = dict(zip(headers, row))

        campaign = r.get("campaign","").strip()
        city     = r.get("city (matched)","").strip()
        if not city:
            continue
        cl = city.lower()
        if cl in ("city (matched)", "total", "unknown", "(not set)", ""):
            continue
        if cl.startswith("total:") or cl.startswith("total "):
            continue

        geo_rows.append({
            "date":          GEO_DATE,
            "campaign_name": campaign,
            "region":        city,
            "spend":         parse_num(r.get("cost",0)),
            "impressions":   round(parse_num(r.get("impr.",0))),
            "clicks":        round(parse_num(r.get("clicks",0))),
            "conversions":   parse_num(r.get("conversions",0)),
            "revenue":       parse_num(r.get("conv. value",0)),
        })

print(f"Parsed {len(geo_rows)} geo rows")
n_geo = upload_chunks("geo", geo_rows, "Geographic")
print(f"Geographic done: {n_geo} upserted\n")

print(f"All uploads complete — Keywords: {n_kw}, Geographic: {n_geo}")
