"""Extract compact, analysis-ready tables from the public GA4 sample in BigQuery.

Source: bigquery-public-data.ga4_obfuscated_sample_ecommerce (Google Merchandise Store,
2020-11-01 → 2021-01-31). OBSERVED data, obfuscated by Google. All heavy lifting runs in
BigQuery; only compact extracts (~15 MB parquet) are written to data/ga4/.

Usage (recommended: Google Cloud Shell, where credentials already exist):
    pip install --user -q google-cloud-bigquery db-dtypes pyarrow pandas
    python3 scripts/extract_ga4.py extract --project "$GOOGLE_CLOUD_PROJECT"

Notes that matter for correctness:
- Session key = user_pseudo_id + ga_session_id (ga_session_id alone is not unique).
- traffic_source.* is the FIRST-USER acquisition source, not the session source.
- event_date is in the property's timezone; event_timestamp is UTC microseconds. Both kept.
- Purchase rows are extracted raw (duplicates included) so dedup is a tested dbt step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

SRC = "`bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`"
OUT = Path(__file__).resolve().parents[1] / "data" / "ga4"
SCOPES = ["https://www.googleapis.com/auth/bigquery",
          "https://www.googleapis.com/auth/cloud-platform.read-only"]

PARAM = "(SELECT value.int_value FROM UNNEST(event_params) WHERE key = '{k}')"
PARAM_ANY = ("(SELECT COALESCE(value.string_value, CAST(value.int_value AS STRING)) "
             "FROM UNNEST(event_params) WHERE key = '{k}')")

QUERIES: dict[str, str] = {
    # One row per session. ~360K rows.
    "sessions": f"""
WITH ev AS (
  SELECT
    user_pseudo_id,
    {PARAM.format(k='ga_session_id')} AS ga_session_id,
    PARSE_DATE('%Y%m%d', event_date) AS event_date,
    event_timestamp, event_name,
    {PARAM_ANY.format(k='session_engaged')} AS session_engaged,
    {PARAM.format(k='engagement_time_msec')} AS engagement_time_msec,
    device.category AS device_category, device.operating_system AS operating_system,
    geo.country AS country,
    traffic_source.source AS first_user_source, traffic_source.medium AS first_user_medium,
    traffic_source.name AS first_user_campaign,
    ecommerce.transaction_id AS transaction_id,
    ecommerce.purchase_revenue_in_usd AS purchase_revenue_usd
  FROM {SRC}
)
SELECT
  user_pseudo_id, ga_session_id,
  TIMESTAMP_MICROS(MIN(event_timestamp)) AS session_start_utc,
  MIN(event_date) AS session_date,
  COUNT(DISTINCT event_date) AS n_event_dates,
  ANY_VALUE(device_category) AS device_category,
  ANY_VALUE(operating_system) AS operating_system,
  ANY_VALUE(country) AS country,
  ANY_VALUE(first_user_source) AS first_user_source,
  ANY_VALUE(first_user_medium) AS first_user_medium,
  ANY_VALUE(first_user_campaign) AS first_user_campaign,
  COUNT(*) AS n_events,
  COUNTIF(event_name = 'page_view') AS page_views,
  MAX(IF(session_engaged = '1', 1, 0)) AS engaged,
  SUM(COALESCE(engagement_time_msec, 0)) AS engagement_time_msec,
  MAX(IF(event_name = 'view_item', 1, 0)) AS has_view_item,
  MAX(IF(event_name = 'add_to_cart', 1, 0)) AS has_add_to_cart,
  MAX(IF(event_name = 'begin_checkout', 1, 0)) AS has_begin_checkout,
  MAX(IF(event_name = 'add_shipping_info', 1, 0)) AS has_add_shipping_info,
  MAX(IF(event_name = 'add_payment_info', 1, 0)) AS has_add_payment_info,
  MAX(IF(event_name = 'purchase', 1, 0)) AS has_purchase,
  COUNT(DISTINCT IF(event_name = 'purchase', transaction_id, NULL)) AS transactions,
  SUM(IF(event_name = 'purchase', COALESCE(purchase_revenue_usd, 0), 0)) AS purchase_revenue_usd
FROM ev
GROUP BY user_pseudo_id, ga_session_id
""",
    # Raw purchase events (duplicates intentionally kept). ~5K rows.
    "purchase_events": f"""
SELECT
  user_pseudo_id,
  {PARAM.format(k='ga_session_id')} AS ga_session_id,
  PARSE_DATE('%Y%m%d', event_date) AS event_date,
  TIMESTAMP_MICROS(event_timestamp) AS event_utc,
  ecommerce.transaction_id AS transaction_id,
  ecommerce.purchase_revenue_in_usd AS purchase_revenue_usd,
  ecommerce.total_item_quantity AS total_item_quantity,
  ecommerce.unique_items AS unique_items,
  device.category AS device_category,
  geo.country AS country,
  traffic_source.source AS first_user_source, traffic_source.medium AS first_user_medium
FROM {SRC}
WHERE event_name = 'purchase'
""",
    # Item lines of purchases. Item revenue vs event revenue is a reconciliation test.
    "purchase_items": f"""
SELECT
  ecommerce.transaction_id AS transaction_id,
  user_pseudo_id,
  TIMESTAMP_MICROS(event_timestamp) AS event_utc,
  i.item_id, i.item_name, i.item_brand, i.item_category,
  i.price_in_usd, i.quantity, i.item_revenue_in_usd
FROM {SRC}, UNNEST(items) AS i
WHERE event_name = 'purchase'
""",
    # Daily item-funnel volume by category.
    "item_funnel_daily": f"""
SELECT
  PARSE_DATE('%Y%m%d', event_date) AS event_date,
  event_name, i.item_category,
  COUNT(*) AS item_events, COUNT(DISTINCT user_pseudo_id) AS users
FROM {SRC}, UNNEST(items) AS i
WHERE event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
GROUP BY 1, 2, 3
""",
    # Daily event counts: used to detect instrumentation breaks.
    "events_daily": f"""
SELECT
  PARSE_DATE('%Y%m%d', event_date) AS event_date, event_name,
  COUNT(*) AS events, COUNT(DISTINCT user_pseudo_id) AS users
FROM {SRC}
GROUP BY 1, 2
""",
    # Totals for reconciliation against Google's published figures.
    "totals": f"""
SELECT
  COUNT(*) AS events,
  COUNT(DISTINCT user_pseudo_id) AS users,
  COUNT(DISTINCT CONCAT(user_pseudo_id, '-',
        CAST({PARAM.format(k='ga_session_id')} AS STRING))) AS sessions,
  COUNT(DISTINCT IF(event_name = 'purchase', ecommerce.transaction_id, NULL)) AS transactions,
  MIN(event_date) AS min_date, MAX(event_date) AS max_date
FROM {SRC}
""",
}


def _credentials():
    """Application Default Credentials (e.g. Google Cloud Shell); browser OAuth as fallback."""
    import google.auth

    try:
        creds, _ = google.auth.default(scopes=SCOPES)
        return creds
    except google.auth.exceptions.DefaultCredentialsError:
        import pydata_google_auth

        return pydata_google_auth.get_user_credentials(SCOPES, use_local_webserver=True)


def cmd_projects() -> None:
    from google.cloud import bigquery

    client = bigquery.Client(credentials=_credentials(), project="bigquery-public-data")
    projects = list(client.list_projects())
    print("Your GCP projects:" if projects else "No GCP projects found.")
    for p in projects:
        print(f"  {p.project_id}  ({p.friendly_name})")


def cmd_extract(project: str) -> None:
    from google.cloud import bigquery

    client = bigquery.Client(credentials=_credentials(), project=project)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "label": ("OBSERVED — Google Merchandise Store, GA4 obfuscated sample "
                  "(bigquery-public-data.ga4_obfuscated_sample_ecommerce). Obfuscated by Google; "
                  "traffic_source = first-user acquisition source."),
        "extracted_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tables": {},
    }
    for name, sql in QUERIES.items():
        job = client.query(sql)
        df = job.result().to_dataframe()
        path = OUT / f"{name}.parquet"
        df.to_parquet(path, index=False)
        manifest["tables"][name] = {
            "rows": len(df),
            "bytes_processed": job.total_bytes_processed,
            "sql_sha256": hashlib.sha256(sql.encode()).hexdigest()[:16],
        }
        print(f"{name:20s} {len(df):>9,} rows  "
              f"{(job.total_bytes_processed or 0) / 1e9:6.2f} GB scanned")
        if name == "totals":
            manifest["totals"] = json.loads(df.to_json(orient="records", date_format="iso"))[0]
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(json.dumps(manifest.get("totals"), indent=2, default=str))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("projects")
    e = sub.add_parser("extract")
    e.add_argument("--project", required=True)
    args = p.parse_args()
    cmd_projects() if args.cmd == "projects" else cmd_extract(args.project)


if __name__ == "__main__":
    main()
