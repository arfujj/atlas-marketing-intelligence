# GA4 extraction & validation

**Evidence type: Observed.** Google Merchandise Store, `bigquery-public-data.ga4_obfuscated_sample_ecommerce`,
2020-11-01 → 2021-01-31, obfuscated by Google. Extracted 2026-10-23 with `scripts/extract_ga4.py`
in Google Cloud Shell (BigQuery sandbox, ≈ 5.1 GB scanned). Compact extracts in `data/ga4/`
(≈ 12 MB, zstd parquet, BigQuery `dbdate` metadata stripped so pandas/DuckDB read them natively).

| Table | Rows | Grain |
|---|---|---|
| `sessions` | 360,129 | user_pseudo_id × ga_session_id |
| `purchase_events` | 5,692 | raw purchase event (duplicates kept on purpose) |
| `purchase_items` | 16,003 | purchase item line |
| `item_funnel_daily` | 10,381 | date × event × item_category |
| `events_daily` | 1,465 | date × event_name |
| `totals` | 1 | dataset |

## Reconciliation

| Check | Extract | Reference | Status |
|---|---|---|---|
| Events | 4,295,584 | 4,295,584 | exact |
| Users (`user_pseudo_id`) | 270,154 | 270,154 | exact |
| Sessions (`user_pseudo_id` + `ga_session_id`) | 360,129 | 360,129 | exact |
| Date range | 2020-11-01 → 2021-01-31 | same | exact |
| Transactions | 4,452 distinct ids | 4,887 (third-party figure) | definition differs, see below |

Reference figures come from public write-ups of the dataset, not from an official Google
reconciliation. The transaction figure depends on how `(not set)` ids and duplicates are counted.

## Data-quality findings (these drive dbt tests)

- **883** purchase events have `transaction_id = '(not set)'` and **23** have a NULL id: they can't be deduplicated by id.
- **335** purchase rows repeat an already-seen transaction id.
- Revenue: **$362,165** summing purchase events naively, versus **$307,640** after deduplicating by
  transaction id with the documented rule (keep the earliest event per valid id; exclude
  `(not set)`/NULL, which carry **$31,817** on 906 events and are reported separately). An earlier
  version of this note said $307,608; no dedup rule reproduces that figure from the extract
  (earliest $307,640, latest $307,868, min $307,308, max $308,200), so it is corrected here
  (decision D-011).
- Item-level revenue reconciles to event-level revenue within 0.1%: $362,110 vs $362,165 over all
  rows, $307,562 vs $307,640 for deduplicated transactions; 81.3% of transactions match to the cent.
- `event_date` equals the UTC date of `event_timestamp` for every event in this export, so all
  daily marts use UTC dates (tested).
- **845** sessions span more than one `event_date` (midnight crossing): a session's date ≠ every event's date.
- `traffic_source.*` is the **first-user** acquisition source: `(data deleted)` covers 22,236 sessions,
  `<Other>` 97,289. Never present it as session or last-touch attribution.
- 4,848 sessions contain a purchase event.

All of the above are asserted by dbt tests in `dbt/tests/ga4/` and surfaced as rows of
`ga4.mart_ga4_data_quality` (value + the modelling decision each finding drives).
