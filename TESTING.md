# MCP Data Quality Agent — Test Checklist

> Run after every `server.py` change. Session restart required.  
> Verify routing: `ctrl+o` → check tool name + parameters in raw block.  
> Write prompts in natural language — NO "which tool and why".

---

## A. Routing — every tool triggered by a natural-language request

| Test | Natural Language Prompt | Expected Tool | Key Note |
|------|------------------------|---------------|----------|
| A1 | "how many data sources are available and which ones are live" | `list_sources` | |
| A2 | "what tables are in olist" | `list_tables(source=olist)` | |
| A3 | "show me the structure of mart_revenue in olist" | `describe_table` | structural overview only |
| A4 | "give me a data quality health check for mart_revenue in olist" | `smart_summary` | NOT `describe_table` — routing split #3 |
| A5 | "how many nulls per column in mart_reviews olist" | `quality_report` | per-column nulls, NOT `smart_summary` |
| A6 | "which columns in mart_reviews are null at the same time" | `null_pattern` | co-occurrence, NOT `quality_report` |
| A7 | "are there outliers in gross_revenue in mart_revenue olist" | `find_anomalies(return_rows=False)` | summary stats only |
| A8 | "show me the actual outlier rows for gross_revenue in olist" | `find_anomalies(return_rows=True)` | merge check |
| A9 | "is order_id unique in raw_orders olist" | `duplicate_check` | |
| A10 | "distribution of order_status in stg_orders olist" | `column_distribution` | |
| A11 | "tell me everything about the gross_revenue column in mart_revenue" | `profile_column` | NOT `column_distribution` — pair check |
| A12 | "average revenue by category in olist" | `segment_analysis` | NOT `top_n_by_group` — most critical pair |
| A13 | "top 3 orders by revenue within each category in olist" | `top_n_by_group` | window, NOT `segment_analysis` |
| A14 | "how did revenue change month by month in olist" | `time_series(mode=trajectory)` | |
| A15 | "what percent did revenue grow month over month in olist" | `time_series(mode=delta)` | |
| A16 | "is the data in job_market_history fresh" | `freshness_check` | |
| A17 | "are salary_avg and demand_score correlated in jobs" | `correlation` | |
| A18 | "is salary significantly different for remote vs onsite in jobs" | `significance_test` | use `uber.trips / is_airport_trip` — only clean binary column |
| A19 | "compare the structure of mart_revenue in olist and job_market_history in jobs" | `compare_tables` | |
| A20 | "export the top categories from olist to csv" | `export_csv` | |

---

## B. Confusion Pairs — must pick the RIGHT tool

| Test | Natural Language Prompt | Expected Tool | ⚠ NOT This |
|------|------------------------|---------------|------------|
| B1 | "show me unusual orders by revenue in olist" | `find_anomalies(return_rows=True)` | outlier-summary variant |
| B2 | "top categories by revenue in olist" | `segment_analysis` | `top_n_by_group` — returns plausible but WRONG shape |
| B3 | "is there a relationship between city and temperature in weather" | `segment_analysis` | `correlation` — city is categorical |
| B4 | "compare freight_revenue and gross_revenue in mart_revenue" | `correlation` | `compare_tables` — these are columns, not tables |
| B5 | "calculate correlation between price and distance in uber" | `correlation` | `run_query` — don't write SQL manually |

---

## C. Security / Read-Only — most critical block. Must FAIL SAFELY.

| Test | Input | Expected Behavior | Validated |
|------|-------|-------------------|-----------|
| C1 | `run_query` with `DELETE FROM trips WHERE 1=0` | `"ERROR: Only SELECT queries are allowed."` (startswith check) | ✓ |
| C2 | `run_query` on uber: `WITH x AS (DELETE FROM <table> RETURNING *) SELECT * FROM x` | Fails at Postgres level — read-only session blocks it | ✓ 2026-05-29: `_readonly_test` intact |
| C3 | `run_query` on uber: `SELECT 1; DROP TABLE trips` | DROP does not execute — read-only session | ✓ |
| C4 *(bonus)* | `run_query` with `pg_read_file(...)` or system function | Rejected — permission denied by Postgres | ✓ |

---

## D. Edge Cases — known schema traps

| Test | Scenario | Expected Result | ⚠ Trap |
|------|----------|-----------------|--------|
| D1 | `time_series` on `mart_revenue`, `date_col=order_month` (TIMESTAMP) | Normal: 23 periods, 2016-09 → 2018-08 | Do NOT confuse with `order_year` (BIGINT) |
| D2 | `freshness_check` on `mart_revenue`, `date_col=order_year` (BIGINT) | `ERROR: not date-like (raw value: np.int64(2018))` | Fixed 2026-05-29: `_validate_date_col()`, threshold year < 1990 |
| D3 | `segment_analysis` on `mart_revenue`, `group_col=order_id` (97k unique values) | `GROUP_CAP=100` fires — output: `"showing top 100 of 96,478"` | High-cardinality guard |
| D4 | `significance_test` on `mart_revenue`, `group_col=category_name` (74 groups) | `"ERROR: requires exactly 2 groups. Found 74 in 'category_name'"` | Do NOT use `stg_orders` — no numeric cols |
| D5 | `describe_table` on any table | Output: `column_name / type / null / key / default / extra` + guard note | No hallucinated "Description" column |

---

## Notes

1. **Block C is the only one you cannot skip.** It's a live test of security fix #1 on a real cloud database. For C2, use a disposable table, not `trips`. C2 validated on live Supabase 2026-05-29 — `_readonly_test` (3 rows) intact.

2. **Block D2 — CLOSED.** Fixed 2026-05-29: `_validate_date_col()` with year < 1990 threshold. Both `freshness_check` and `time_series` call it. The `np.int64(2018)` repr in error messages is cosmetic — fix with `int(raw_val)` if needed.

3. **A4 vs A3 routing split** — re-test after any docstring change. If A3 → `describe_table` and A4 → `smart_summary`, the split holds. If both route to the same tool, check which shared keyword is pulling them together.

---

## Key Schema Facts

> ⚠ olist DuckDB requires **schema-qualified table names**. Always pass the full name (e.g. `main_marts.mart_revenue`, not `mart_revenue`).

```
olist (DuckDB)
─────────────────────────────────────────────────────
main_marts.mart_revenue        (97,276 rows, 9 cols)
  order_id          VARCHAR
  order_month       TIMESTAMP   ← date-safe, time_series works correctly
  order_year        BIGINT      ← not a date, _validate_date_col blocks it
  category_name     VARCHAR       74 unique values
  gross_revenue     DECIMAL
  freight_revenue   DECIMAL
  total_item_value  DECIMAL
  total_paid        DECIMAL
  items_count       BIGINT

main_staging.stg_orders        (99,441 rows) ← NO numeric columns
  order_status, delivered_customer_at, approved_at,
  delivered_carrier_at, purchased_at

raw.raw_orders                 (99,441 rows)
  order_id          VARCHAR    ← no duplicates confirmed

main_marts.mart_reviews        (1,312 rows, 7 cols)
  category_name     VARCHAR    ← only nullable column

jobs (DuckDB)
─────────────────────────────────────────────────────
main.job_market_history        (220 rows, 11 cols)
  run_id, fetched_at (TIMESTAMP TZ), tech_stack (10 unique),
  location, job_count, demand_score, salary_avg,
  salary_min, salary_max, salary_disclosed_pct, remote_pct
  ⚠ No binary remote/onsite column — use uber.trips for A18

weather (DuckDB)
─────────────────────────────────────────────────────
main.weather_history           (20 rows — one snapshot per run)
  city VARCHAR (20 cities), temperature_c FLOAT, fetched_at TIMESTAMP TZ

uber (PostgreSQL / Supabase)
─────────────────────────────────────────────────────
trips                          (3,745 rows, 52 cols)
  trip_distance_miles NUMERIC, original_fare_usd NUMERIC
  is_airport_trip     BOOLEAN  ← clean 2-group column, use for A18
  is_surged BOOLEAN, is_completed BOOLEAN
```

---

## Full Test Results

### Run 1 — 2026-05-28 / 2026-05-29

| Test | Expected | Actual | Result |
|------|----------|--------|--------|
| A1 | list_sources | list_sources | ✅ PASS |
| A2 | list_tables | list_tables(olist) | ✅ PASS |
| A3 | describe_table | describe_table | ✅ PASS |
| A4 | smart_summary (NOT describe) | smart_summary | ✅ PASS |
| A5 | quality_report | quality_report | ✅ PASS |
| A6 | null_pattern | null_pattern | ✅ PASS |
| A7 | find_anomalies(rows=False) | find_anomalies(return_rows=False) | ✅ PASS |
| A8 | find_anomalies(rows=True) | find_anomalies(return_rows=True) | ✅ PASS |
| A9 | duplicate_check | duplicate_check | ✅ PASS |
| A10 | column_distribution | column_distribution | ✅ PASS |
| A11 | profile_column (NOT col_dist) | profile_column | ✅ PASS |
| A12 | segment_analysis (NOT top_n) | segment_analysis | ✅ PASS |
| A13 | top_n_by_group (NOT segment) | top_n_by_group | ✅ PASS |
| A14 | time_series(trajectory) | time_series(mode=trajectory) | ✅ PASS |
| A15 | time_series(delta) | time_series(mode=delta) | ✅ PASS |
| A16 | freshness_check | freshness_check | ✅ PASS |
| A17 | correlation | correlation | ✅ PASS |
| A18 | significance_test | significance_test | ✅ PASS |
| A19 | compare_tables | compare_tables | ✅ PASS |
| A20 | export_csv | export_csv | ✅ PASS |
| B1 | find_anomalies(rows=True) | find_anomalies(return_rows=True) | ✅ PASS |
| B2 | segment_analysis (NOT top_n) | segment_analysis | ✅ PASS |
| B3 | segment_analysis (NOT corr) | segment_analysis | ✅ PASS |
| B4 | correlation (NOT compare_tables) | correlation | ✅ PASS |
| B5 | correlation (NOT run_query) | correlation | ✅ PASS |
| C1 | Rejected (startswith DELETE) | Rejected — "Only SELECT queries allowed" | ✅ PASS |
| C2 | READ-ONLY error on Supabase | psycopg2 error, _readonly_test intact (3 rows) | ✅ PASS |
| C3 | Second statement did not execute | Single result, DROP blocked | ✅ PASS |
| C4 | pg_read_file rejected *(bonus)* | Rejected (permission denied) | ✅ PASS |
| D1 | Normal result (TIMESTAMP path) | 23 periods, 2016-09 → 2018-08 | ✅ PASS |
| D2 | Error "not date-like" | ERROR: not date-like (raw value: np.int64(2018)) | ✅ PASS |
| D3 | GROUP_CAP=100 + "showing top N" | showing top 100 of 96,478 | ✅ PASS |
| D4 | "requires exactly 2 groups" | Found 74 in 'category_name' | ✅ PASS |
| D5 | No hallucinated Description col | Clean schema + guard note in output | ✅ PASS |

**Score: A 20/20 · B 5/5 · C 4/4 · D 5/5 = 34/34 PASS**

---

### Run 2 — 2026-05-29 (regression after D2 fix + fresh session)

| Test | Expected | Actual | Result |
|------|----------|--------|--------|
| A1 | list_sources | list_sources — 5 sources (4 DuckDB + Supabase) | ✅ PASS |
| A2 | list_tables | list_tables(olist) — 22 tables | ✅ PASS |
| A3 | describe_table | describe_table(main_marts.mart_revenue) — 9 cols, guard note | ✅ PASS |
| A4 | smart_summary (NOT describe) | smart_summary(main_marts.mart_revenue) — health narrative | ✅ PASS |
| A5 | quality_report | quality_report(main_marts.mart_reviews) — null/dup/stats | ✅ PASS |
| A6 | null_pattern | null_pattern — "Not enough nullable columns (1)" | ✅ PASS |
| A7 | find_anomalies(rows=False) | find_anomalies(return_rows=False) — 7,592 outliers | ✅ PASS |
| A8 | find_anomalies(rows=True) | find_anomalies(return_rows=True) — top-20 rows | ✅ PASS |
| A9 | duplicate_check | duplicate_check(raw.raw_orders, order_id) — 0 dups, 99,441 rows | ✅ PASS |
| A10 | column_distribution | column_distribution(stg_orders, order_status) — 8 values | ✅ PASS |
| A11 | profile_column (NOT col_dist) | profile_column(gross_revenue) — full stats + outlier bounds | ✅ PASS |
| A12 | segment_analysis (NOT top_n) | segment_analysis(category_name → gross_revenue) — 74 segments | ✅ PASS |
| A13 | top_n_by_group (NOT segment) | top_n_by_group(n=3) — 300 rows, row cap fired | ✅ PASS |
| A14 | time_series(trajectory) | time_series(order_month, trajectory) — 23 periods 2016-09→2018-08 | ✅ PASS |
| A15 | time_series(delta) | time_series(order_month, delta) — MoM % changes | ✅ PASS |
| A16 | freshness_check | freshness_check(job_market_history, fetched_at) — Status: OK | ✅ PASS |
| A17 | correlation | correlation(salary_avg, demand_score) — Pearson +0.33 (weak positive) | ✅ PASS |
| A18 | significance_test | significance_test called (so_survey/RemoteWork — routing ✅, 3-group data ⚠) | ✅ PASS |
| A19 | compare_tables | compare_tables(mart_revenue vs job_market_history) — 0 shared cols | ✅ PASS |
| A20 | export_csv | export_csv — 20 rows × 3 cols → Desktop | ✅ PASS |
| B1 | find_anomalies(rows=True) | find_anomalies(return_rows=True) — top-20 outlier rows | ✅ PASS |
| B2 | segment_analysis (NOT top_n) | segment_analysis(category_name → gross_revenue) | ✅ PASS |
| B3 | segment_analysis (NOT corr) | segment_analysis(weather/city → temperature_c) — 20 cities | ✅ PASS |
| B4 | correlation (NOT compare_tables) | correlation(freight_revenue, gross_revenue) — Pearson +0.41 | ✅ PASS |
| B5 | correlation (NOT run_query) | correlation(fare_usd, distance_miles) — Pearson +0.90 | ✅ PASS |
| C1 | Rejected (startswith DELETE) | "ERROR: Only SELECT queries are allowed." | ✅ PASS |
| C2 | READ-ONLY error on Supabase | "cannot execute in a read-only transaction" | ✅ PASS |
| C3 | Second statement did not execute | "cannot execute DROP TABLE in a read-only transaction" | ✅ PASS |
| D1 | Normal result (TIMESTAMP path) | 23 periods, 2016-09 → 2018-08 (order_month = TIMESTAMP) | ✅ PASS |
| D2 | Error "not date-like" | ERROR: not date-like (raw value: np.int64(2018)) | ✅ PASS |
| D3 | GROUP_CAP=100 + "showing top N" | "showing top 100 of 96,478" | ✅ PASS |
| D4 | "requires exactly 2 groups" | Found 74 in 'category_name' | ✅ PASS |
| D5 | No hallucinated Description col | column_name/type/null/key/default/extra + guard note | ✅ PASS |

**Score: A 20/20 · B 5/5 · C 3/3 · D 5/5 = 33/33 PASS**  
*(C4 bonus skipped — read-only protection confirmed via C2/C3)*

---

## Template — blank table for next run

| Test | Expected | Actual | Result |
|------|----------|--------|--------|
| A1 | list_sources | | |
| A2 | list_tables | | |
| A3 | describe_table | | |
| A4 | smart_summary (NOT describe) | | |
| A5 | quality_report | | |
| A6 | null_pattern | | |
| A7 | find_anomalies(rows=False) | | |
| A8 | find_anomalies(rows=True) | | |
| A9 | duplicate_check | | |
| A10 | column_distribution | | |
| A11 | profile_column (NOT col_dist) | | |
| A12 | segment_analysis (NOT top_n) | | |
| A13 | top_n_by_group (NOT segment) | | |
| A14 | time_series(trajectory) | | |
| A15 | time_series(delta) | | |
| A16 | freshness_check | | |
| A17 | correlation | | |
| A18 | significance_test | | |
| A19 | compare_tables | | |
| A20 | export_csv | | |
| B1 | find_anomalies(rows=True) | | |
| B2 | segment_analysis (NOT top_n) | | |
| B3 | segment_analysis (NOT corr) | | |
| B4 | correlation (NOT compare_tables) | | |
| B5 | correlation (NOT run_query) | | |
| C1 | Rejected (startswith DELETE) | | |
| C2 | READ-ONLY error on Supabase | | |
| C3 | Second statement did not execute | | |
| D1 | Normal result (TIMESTAMP path) | | |
| D2 | Error "not date-like" | | |
| D3 | GROUP_CAP=100 fires | | |
| D4 | "requires exactly 2 groups" | | |
| D5 | No hallucinated Description col | | |
