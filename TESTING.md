══════════════════════════════════════════════════════════════
MCP DATA QUALITY AGENT — TEST CHECKLIST
Run after every server.py change. Session restart required.
Verify routing: ctrl+o → check tool name + parameters in raw block.
Write prompts in natural language — NO "which tool and why".
═══════════════════════════════════════════════════════════════

──────────────────────────────────────────
A. ROUTING — every tool triggered by a natural-language request
──────────────────────────────────────────
A1.  "how many data sources are available and which ones are live"
     → list_sources

A2.  "what tables are in olist"
     → list_tables(source=olist)

A3.  "show me the structure of mart_revenue in olist"
     → describe_table   (structural overview)

A4.  "give me a data quality health check for mart_revenue in olist"
     → smart_summary    (NOT describe_table — routing split #3)

A5.  "how many nulls per column in mart_reviews olist"
     → quality_report   (per-column nulls, NOT smart_summary)

A6.  "which columns in mart_reviews are null at the same time"
     → null_pattern     (co-occurrence, NOT quality_report)

A7.  "are there outliers in gross_revenue in mart_revenue olist"
     → find_anomalies(return_rows=False)

A8.  "show me the actual outlier rows for gross_revenue in olist"
     → find_anomalies(return_rows=True)   (merge check)

A9.  "is order_id unique in raw_orders olist"
     → duplicate_check

A10. "distribution of order_status in stg_orders olist"
     → column_distribution

A11. "tell me everything about the gross_revenue column in mart_revenue"
     → profile_column   (NOT column_distribution — pair check)

A12. "average revenue by category in olist"
     → segment_analysis (NOT top_n_by_group — most critical pair)

A13. "top 3 orders by revenue within each category in olist"
     → top_n_by_group   (window, NOT segment_analysis)

A14. "how did revenue change month by month in olist"
     → time_series(mode=trajectory)

A15. "what percent did revenue grow month over month in olist"
     → time_series(mode=delta)

A16. "is the data in job_market_history fresh"
     → freshness_check

A17. "are salary_avg and demand_score correlated in jobs"
     → correlation

A18. "is salary significantly different for remote vs onsite in jobs"
     → significance_test

A19. "compare the structure of mart_revenue in olist and job_market_history in jobs"
     → compare_tables

A20. "export the top categories from olist to csv"
     → export_csv

──────────────────────────────────────────
B. CONFUSION PAIRS — tools that used to mix up. Must pick the RIGHT one.
──────────────────────────────────────────
B1.  "show me unusual orders by revenue in olist"
     → find_anomalies(return_rows=True)   NOT the outlier-summary variant

B2.  "top categories by revenue in olist"
     → segment_analysis                   NOT top_n_by_group
     ⚠ most dangerous: top_n_by_group returns a plausible but WRONG shape

B3.  "is there a relationship between city and temperature in weather"
     → segment_analysis                   NOT correlation (city = categorical)

B4.  "compare freight_revenue and gross_revenue in mart_revenue"
     → correlation                        NOT compare_tables (these are columns, not tables)

B5.  "calculate correlation between price and distance in uber"
     → correlation                        NOT run_query (don't write SQL manually)

──────────────────────────────────────────
C. SECURITY / READ-ONLY — most critical block. Must FAIL SAFELY.
──────────────────────────────────────────
C1.  "delete a row from trips in uber" / direct run_query with DELETE
     → rejected (startswith check)

C2.  run_query, source=uber:
     WITH x AS (DELETE FROM <table> RETURNING *) SELECT * FROM x
     → must fail at Postgres level (read-only session), NOT execute.
       This is the primary test for security fix #1.
       ⚠ use a disposable/test table in case the fix didn't work.
     ✓ VALIDATED 2026-05-29: _readonly_test (3 rows) intact after CTE-DELETE attempt.

C3.  run_query with "SELECT 1; DROP TABLE ..." on uber
     → second statement must not execute

──────────────────────────────────────────
D. EDGE CASES — known schema traps
──────────────────────────────────────────
D1.  time_series on mart_revenue with date_col=order_month
     → expected: normal result (23 periods, 2016-09 → 2018-08)
     ⚠ order_month is stored as TIMESTAMP (not INT) — confirmed by describe_table 2026-05-29.
       Do NOT confuse with order_year (BIGINT), which triggers the D2 trap.

D2.  freshness_check on an integer column (order_year in mart_revenue, BIGINT)
     → expected: error "not date-like (raw value: ...)", NOT a 1970-01-01 date
     ✓ FIXED 2026-05-29: _validate_date_col() added to server.py.
       Called by both freshness_check and time_series. Threshold: year < 1990.
     ⚠ Key lesson: time_series on an int column would silently produce 1970 dates
       (int-as-nanoseconds is not NaT, so dropna() doesn't catch it).
       Caught only because we fixed the class, not a single instance.

D3.  segment_analysis with high-cardinality group_col (order_id, 97k unique values)
     → GROUP_CAP=100 must fire + output line "showing top 100 of N"

D4.  significance_test on a column with 3+ groups
     → table: mart_revenue, group_col=category_name (74 categories), value_col=gross_revenue
     → expected: clean error "requires exactly 2 groups", NOT a crash
     ⚠ Do NOT use stg_orders/order_status — stg_orders has no numeric columns
       (available: order_status, delivered_customer_at, approved_at,
       delivered_carrier_at, purchased_at).
       Do NOT use order_year — semantically it's a year, not a category.

D5.  describe_table — verify NO hallucinated "Description" column
     → raw block must contain only: column_name / type / null / key / default / extra
     → tool appends guard note: "schema only — this tool does NOT return column
       descriptions. Do not invent or present descriptions as tool output."
       (hallucination can't be closed server-side — this is a regression control)

═══════════════════════════════════════════════════════════════
NOTES
═══════════════════════════════════════════════════════════════

1. Block C is the only one you cannot skip. It's a live test of security fix #1
   on a real cloud database. For C2, use a test table, not trips.
   C2 validated on live Supabase 2026-05-29 — _readonly_test intact.

2. Block D2 — CLOSED (was a fix candidate). Fixed 2026-05-29:
   _validate_date_col() with year < 1990 threshold. Both freshness_check
   and time_series call it. The np.int64(2018) repr in error messages
   is cosmetic — fix with int(raw_val) when formatting the string if needed.

3. A4 vs A3 routing split — re-test after any docstring change. If A3 →
   describe_table and A4 → smart_summary, the split holds. If both route
   to the same tool, check which shared keyword is pulling them together.

──────────────────────────────────────────
KEY SCHEMA FACTS (olist DuckDB)
──────────────────────────────────────────
mart_revenue columns:
  order_id          VARCHAR
  order_month       TIMESTAMP   ← date-safe, time_series works correctly
  order_year        BIGINT      ← not a date, _validate_date_col blocks it
  category_name     VARCHAR     (74 unique values)
  gross_revenue     DECIMAL
  freight_revenue   DECIMAL
  total_item_value  DECIMAL
  total_paid        DECIMAL
  items_count       BIGINT

stg_orders columns (NO numeric columns):
  order_status, delivered_customer_at, approved_at,
  delivered_carrier_at, purchased_at

──────────────────────────────────────────
FULL TEST RESULTS — 2026-05-28 / 2026-05-29
──────────────────────────────────────────
| Test | Expected                          | Actual                                         | Result  |
|------|-----------------------------------|------------------------------------------------|---------|
| A1   | list_sources                      | list_sources                                   | ✅ PASS |
| A2   | list_tables                       | list_tables(olist)                             | ✅ PASS |
| A3   | describe_table                    | describe_table                                 | ✅ PASS |
| A4   | smart_summary (NOT describe)      | smart_summary                                  | ✅ PASS |
| A5   | quality_report                    | quality_report                                 | ✅ PASS |
| A6   | null_pattern                      | null_pattern                                   | ✅ PASS |
| A7   | find_anomalies(rows=False)        | find_anomalies(return_rows=False)              | ✅ PASS |
| A8   | find_anomalies(rows=True)         | find_anomalies(return_rows=True)               | ✅ PASS |
| A9   | duplicate_check                   | duplicate_check                                | ✅ PASS |
| A10  | column_distribution               | column_distribution                            | ✅ PASS |
| A11  | profile_column (NOT col_dist)     | profile_column                                 | ✅ PASS |
| A12  | segment_analysis (NOT top_n)      | segment_analysis                               | ✅ PASS |
| A13  | top_n_by_group (NOT segment)      | top_n_by_group                                 | ✅ PASS |
| A14  | time_series(trajectory)           | time_series(mode=trajectory)                   | ✅ PASS |
| A15  | time_series(delta)                | time_series(mode=delta)                        | ✅ PASS |
| A16  | freshness_check                   | freshness_check                                | ✅ PASS |
| A17  | correlation                       | correlation                                    | ✅ PASS |
| A18  | significance_test                 | significance_test                              | ✅ PASS |
| A19  | compare_tables                    | compare_tables                                 | ✅ PASS |
| A20  | export_csv                        | export_csv                                     | ✅ PASS |
| B1   | find_anomalies(rows=True)         | find_anomalies(return_rows=True)               | ✅ PASS |
| B2   | segment_analysis (NOT top_n)      | segment_analysis                               | ✅ PASS |
| B3   | segment_analysis (NOT corr)       | segment_analysis                               | ✅ PASS |
| B4   | correlation (NOT compare_tables)  | correlation                                    | ✅ PASS |
| B5   | correlation (NOT run_query)       | correlation                                    | ✅ PASS |
| C1   | Rejected (startswith DELETE)      | Rejected                                       | ✅ PASS |
| C2   | READ-ONLY error on Supabase       | psycopg2 error, _readonly_test intact (3 rows) | ✅ PASS |
| C3   | Second statement did not execute  | Single result, DROP blocked                    | ✅ PASS |
| C4   | pg_read_file rejected (bonus)     | Rejected (permission denied)                   | ✅ PASS |
| D1   | Normal result (TIMESTAMP path)    | 23 periods, 2016-09 → 2018-08                  | ✅ PASS |
| D2   | Error "not date-like"             | ERROR: not date-like (raw value: np.int64(2018)) | ✅ PASS |
| D3   | GROUP_CAP=100 + "showing top N"   | showing top 100 of 96,478                      | ✅ PASS |
| D4   | "requires exactly 2 groups"       | Found 74 in 'category_name'                    | ✅ PASS |
| D5   | No hallucinated Description col   | Clean schema + guard note in output            | ✅ PASS |

FINAL SCORE: A 20/20 · B 5/5 · C 4/4 · D 5/5 = 34/34 PASS
Dates: 2026-05-28 (A/B/C) + 2026-05-29 (D regression + D2 fix verified)

──────────────────────────────────────────
RESULT FORMAT (for future test runs)
──────────────────────────────────────────
| Test | Expected          | Actual (tool + params) | Result |
|------|-------------------|------------------------|--------|
| A1   | list_sources      |                        |        |
| A2   | list_tables       |                        |        |
| ...  | ...               |                        |        |
| C2   | READ-ONLY error   |                        |        |
| D3   | GROUP_CAP fires   |                        |        |

A completed results table is a testing artifact worth showing in an interview
as "this is how I validate an agent" — stronger than the agent itself.
