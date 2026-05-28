# Ask your data. Claude answers.

### MCP Data Quality Agent — 20 tools · 5 databases · natural language

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/FastMCP-1.0-6C3483?style=flat-square&logo=anthropic&logoColor=white"/>
  <img src="https://img.shields.io/badge/DuckDB-1.5-FFF000?style=flat-square&logo=duckdb&logoColor=black"/>
  <img src="https://img.shields.io/badge/PostgreSQL-Supabase-4169E1?style=flat-square&logo=postgresql&logoColor=white"/>
  <img src="https://img.shields.io/badge/MCP-Protocol-FF6B35?style=flat-square&logo=anthropic&logoColor=white"/>
  <img src="https://img.shields.io/badge/tools-20-2ECC71?style=flat-square"/>
</p>

An MCP server that gives Claude direct, read-only access to four DuckDB databases and a Supabase PostgreSQL instance. Claude picks the right tool, writes the SQL, runs it, and interprets the result — no copy-paste, no context-switching, no boilerplate.

---

## Screenshots

<details>
<summary>🔌 MCP Server — connected and ready</summary>

![MCP Connected](assets/mcp_connected.png)

</details>

<details>
<summary>📡 list_sources — all 5 databases healthy</summary>

![List Sources](assets/list_sources.png)

</details>

<details>
<summary>🧠 smart_summary — one-call dataset overview</summary>

![Smart Summary](assets/smart_summary.png)

</details>

<details>
<summary>📊 segment_analysis — salary by tech stack</summary>

![Segment Analysis](assets/segment_analysis.png)

</details>

<details>
<summary>🔗 correlation — salary vs demand (Pearson + Spearman)</summary>

![Correlation](assets/correlation.png)

</details>

<details>
<summary>🩺 quality_report — nulls, duplicates, numeric stats</summary>

![Quality Report](assets/quality_report.png)

</details>

<details>
<summary>🔍 find_anomalies — IQR outlier detection</summary>

![Anomaly Detection](assets/anomaly_detection.png)

</details>

<details>
<summary>⚡ run_query — freeform SQL via MCP</summary>

![Run Query](assets/run_query.png)

</details>

<details>
<summary>🔬 profile_column — full statistical portrait of one column</summary>

![Profile Column](assets/profile_column.png)

</details>

<details>
<summary>🚨 outlier_rows — full row context for every outlier</summary>

![Outlier Rows](assets/outlier_rows.png)

</details>

<details>
<summary>🏆 top_n_by_group — top 3 salaries per tech stack</summary>

![Top N by Group](assets/top_n_by_group.png)

</details>

<details>
<summary>✅ freshness_check — pipeline health status</summary>

![Freshness Check](assets/freshness_check.png)

</details>

<details>
<summary>💡 Bottom Line — 3 data-driven insights</summary>

![Bottom Line](assets/bottom_line.png)

</details>

---

## What a session looks like

```
You:    "Which tech stacks in the SO Survey have the highest salary but lowest
         representation — hidden gems for job seekers?"

Claude: [calls segment_analysis → so_survey · survey_results_public · tech_stack · salary_avg]
        [calls column_distribution → so_survey · survey_results_public · tech_stack]

        → Scala: $187k median, only 2.1% of respondents
          Erlang: $168k, under 1%
          Go: $140k, 8.4% — most accessible of the three
```

```
You:    "Something feels off with the Olist revenue data — run a full check."

Claude: [calls quality_report → olist · main_marts.mart_revenue]
        [calls find_anomalies → olist · main_marts.mart_revenue · gross_revenue]
        [calls null_pattern   → olist · main_marts.mart_revenue]
        [calls outlier_rows   → olist · main_marts.mart_revenue · gross_revenue]

        → 97,276 rows. 0 nulls. 7,592 outliers (7.8%) — all in fixed_telephony category.
          Top offender: $13,440 single order. Not a data error — category has high-ticket items.
```

```
You:    "Is the weather pipeline still fresh, and how does today compare to last week?"

Claude: [calls freshness_check → weather · main.weather_history · recorded_at]
        [calls trend_analysis  → weather · main.weather_history · recorded_at · temperature_c · day]

        → FRESH — last record 4 hours ago.
          NYC: +3.2°C above 7-day average. Chicago trending cold (-2.1°C).
```

---

## 20 tools

### Discovery
| Tool | What it does |
|------|-------------|
| `list_sources` | All connected sources with live status |
| `list_tables(source)` | Tables in a source — `schema.table` format for multi-schema DBs |
| `describe_table(source, table)` | Column types · row count · 3-row sample |
| `run_query(source, sql)` | Execute any `SELECT` / `WITH` — read-only enforced |

### Quality
| Tool | What it does |
|------|-------------|
| `quality_report(source, table)` | Null counts · duplicate rate · numeric stats per column |
| `null_pattern(source, table, min_nulls)` | Co-null patterns — which columns go null together |
| `duplicate_check(source, table, key_cols)` | Exact duplicates on a specific key or composite key |
| `find_anomalies(source, table, column)` | IQR outlier detection — count and % flagged |
| `outlier_rows(source, table, column, limit)` | Full row context for every outlier — not just counts |

### Exploration
| Tool | What it does |
|------|-------------|
| `column_distribution(source, table, column, top_n)` | Categorical: top-N value counts · Numeric: 8-bucket histogram |
| `profile_column(source, table, column)` | Full portrait — type · nulls · uniques · Q1/Q3/IQR · skew · top values |
| `correlation(source, table, col1, col2)` | Pearson + Spearman (rank-based · no scipy required) |
| `segment_analysis(source, table, group_col, value_col)` | `GROUP BY` + count / sum / mean / median / std per segment |
| `top_n_by_group(source, table, group_col, value_col, n)` | Window-function top-N rows per group |
| `smart_summary(source, table)` | One-call narrative: size · quality · numeric · categorical highlights |

### Time series
| Tool | What it does |
|------|-------------|
| `freshness_check(source, table, date_col)` | Latest entry · days since update · `FRESH` / `OK` / `STALE` label |
| `trend_analysis(source, table, date_col, value_col, period)` | Metric over `day` / `week` / `month` |
| `period_over_period(source, table, date_col, value_col, period)` | MoM / YoY with % change column |

### Output
| Tool | What it does |
|------|-------------|
| `compare_tables(source1, table1, source2, table2)` | Row counts · shared columns · unique columns |
| `export_csv(source, sql, filename)` | Any query → CSV saved to Desktop |

---

## Connected datasets

| Source key | Engine | Rows | Dataset |
|-----------|--------|------|---------|
| `so_survey` | DuckDB | 63k | Stack Overflow Developer Survey 2024 |
| `olist` | DuckDB | 97k | Brazilian e-commerce — orders · revenue · reviews (multi-schema dbt) |
| `weather` | DuckDB | growing | Global Weather Pipeline — 20 cities · 6 continents · 2× daily |
| `jobs` | DuckDB | 220 | Job Market Pulse — daily Adzuna API snapshots |
| `uber` | Supabase PostgreSQL | — | Real Uber trip data — trips · payments · ratings |

---

## Architecture

```mermaid
graph LR
    Claude["🤖 Claude AI"] -->|MCP Protocol| Server["data-quality\nMCP Server"]

    Server --> SO["📊 SO Survey\n63k rows"]
    Server --> Olist["🛒 Olist\n97k rows"]
    Server --> Weather["🌤 Weather\n20 cities"]
    Server --> Jobs["💼 Job Market\n220 snapshots"]
    Server --> Uber["🚗 Uber\nPostgreSQL"]

    SO --> DuckDB1[("DuckDB")]
    Olist --> DuckDB2[("DuckDB")]
    Weather --> DuckDB3[("DuckDB")]
    Jobs --> DuckDB4[("DuckDB")]
    Uber --> PG[("Supabase\nPostgreSQL")]
```

Claude never sees a connection string. The server is the only layer that touches data — Claude only sees what tools return.

---

## Security model

| Constraint | How it's enforced |
|-----------|-------------------|
| Read-only DuckDB | `duckdb.connect(path, read_only=True)` |
| Read-only PostgreSQL | Supabase connection with `SELECT`-only role |
| No DDL / DML via `run_query` | Statement rejected if it doesn't start with `SELECT` or `WITH` |
| No credentials in code | All paths and secrets in `.env` — never committed |

---

## Setup

```bash
git clone https://github.com/evgeniimatveev/mcp-data-quality-agent
cd mcp-data-quality-agent
pip install -r requirements.txt
cp .env.example .env   # fill in your DuckDB paths + PostgreSQL credentials
```

Register with Claude Code (available in any project):

```bash
claude mcp add data-quality --scope user -- python /path/to/server.py
```

Or add to Claude Desktop (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "data-quality": {
      "command": "python",
      "args": ["C:/path/to/mcp-data-quality-agent/server.py"]
    }
  }
}
```

Verify it's live:

```bash
claude mcp list
# data-quality: python .../server.py  ✓ Connected
```

---

## Project structure

```
mcp-data-quality-agent/
├── server.py             # FastMCP server — all 20 tools
├── requirements.txt      # mcp · duckdb · psycopg2-binary · pandas · python-dotenv
├── .env.example          # template — copy to .env and fill in
├── .github/
│   └── workflows/
│       └── health_check.yml   # import smoke test on every push
└── .gitignore            # .env · __pycache__ · *.duckdb excluded
```

---

*Built by [Evgenii Matveev](https://github.com/evgeniimatveev) · Python · FastMCP · DuckDB · PostgreSQL · pandas*
