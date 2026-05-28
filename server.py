"""
MCP Data Quality Agent
Gives Claude read-only access to multiple DuckDB databases + PostgreSQL (Supabase).
"""

import os
import duckdb
import psycopg2
import pandas as pd
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()

mcp = FastMCP("data-quality-agent")

SOURCES = {
    "so_survey": os.getenv("DUCKDB_SO_SURVEY", ""),
    "olist":     os.getenv("DUCKDB_OLIST", ""),
    "weather":   os.getenv("DUCKDB_WEATHER", ""),
    "jobs":      os.getenv("DUCKDB_JOBS", ""),
}

PG_CONFIG = {
    "host":     os.getenv("PG_HOST", ""),
    "port":     int(os.getenv("PG_PORT", 5432)),
    "database": os.getenv("PG_DATABASE", "postgres"),
    "user":     os.getenv("PG_USER", ""),
    "password": os.getenv("PG_PASSWORD", ""),
}


def _duckdb_query(path: str, sql: str) -> pd.DataFrame:
    con = duckdb.connect(path, read_only=True)
    try:
        return con.execute(sql).df()
    finally:
        con.close()


def _pg_query(sql: str) -> pd.DataFrame:
    con = psycopg2.connect(**PG_CONFIG)
    try:
        return pd.read_sql(sql, con)
    finally:
        con.close()


def _run(source: str, sql: str) -> pd.DataFrame:
    if source == "uber":
        return _pg_query(sql)
    if source not in SOURCES:
        raise ValueError(
            f"Unknown source '{source}'. Available: {list(SOURCES.keys()) + ['uber']}"
        )
    path = SOURCES[source]
    if not path:
        raise ValueError(f"Path for '{source}' not set in .env")
    return _duckdb_query(path, sql)


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_sources() -> str:
    """Show all available data sources and their file paths."""
    lines = []
    for name, path in SOURCES.items():
        status = "OK" if path and os.path.exists(path) else "NOT FOUND"
        lines.append(f"  {name:12} [{status}]  {path}")
    lines.append(f"  {'uber':12} [PostgreSQL/Supabase]  {PG_CONFIG['host']}")
    return "Available sources:\n" + "\n".join(lines)


@mcp.tool()
def list_tables(source: str) -> str:
    """List all tables in a data source.

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
    """
    if source == "uber":
        df = _pg_query(
            "SELECT table_schema, table_name, table_type "
            "FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
    else:
        df = _duckdb_query(
            SOURCES[source],
            "SELECT table_schema, table_name, table_type "
            "FROM information_schema.tables "
            "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') "
            "ORDER BY table_schema, table_name"
        )
        # Show as schema.table_name for clarity
        if not df.empty:
            df["full_name"] = df["table_schema"] + "." + df["table_name"]
            df = df[["full_name", "table_type"]].rename(columns={"full_name": "table"})
    return df.to_string(index=False)


@mcp.tool()
def describe_table(source: str, table: str) -> str:
    """Show schema, row count, and 3 sample rows.

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        table: table name
    """
    if source == "uber":
        schema = _pg_query(
            f"SELECT column_name, data_type, is_nullable "
            f"FROM information_schema.columns "
            f"WHERE table_name = '{table}' ORDER BY ordinal_position"
        )
        count = _pg_query(f"SELECT COUNT(*) as row_count FROM {table}")
        sample = _pg_query(f"SELECT * FROM {table} LIMIT 3")
    else:
        schema = _duckdb_query(SOURCES[source], f"DESCRIBE {table}")
        count = _duckdb_query(SOURCES[source], f"SELECT COUNT(*) as row_count FROM {table}")
        sample = _duckdb_query(SOURCES[source], f"SELECT * FROM {table} LIMIT 3")

    return (
        f"=== Schema ===\n{schema.to_string(index=False)}\n\n"
        f"=== Row Count ===\n{count.to_string(index=False)}\n\n"
        f"=== Sample (3 rows) ===\n{sample.to_string(index=False)}"
    )


@mcp.tool()
def run_query(source: str, sql: str) -> str:
    """Run a SELECT query on a data source.

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        sql: SQL SELECT statement (only SELECT/WITH allowed)
    """
    stripped = sql.strip().upper()
    if not (stripped.startswith("SELECT") or stripped.startswith("WITH")):
        return "ERROR: Only SELECT queries are allowed."
    df = _run(source, sql)
    if df.empty:
        return "Query returned 0 rows."
    return df.to_string(index=False)


@mcp.tool()
def quality_report(source: str, table: str) -> str:
    """Data quality report: null counts, duplicates, numeric stats.

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        table: table name
    """
    df = _run(source, f"SELECT * FROM {table}")
    total = len(df)

    nulls = df.isnull().sum()
    null_pct = (nulls / total * 100).round(1)
    null_df = pd.DataFrame({"null_count": nulls, "null_pct": null_pct})
    null_df = null_df[null_df["null_count"] > 0].sort_values("null_pct", ascending=False)

    duplicates = total - len(df.drop_duplicates())

    numeric = df.select_dtypes(include="number")
    stats = (
        numeric.describe().T[["min", "mean", "max", "std"]].round(2)
        if not numeric.empty else pd.DataFrame()
    )

    parts = [
        f"Table: {source}.{table}  |  Total rows: {total:,}",
        f"\n=== Duplicates: {duplicates:,} ({duplicates/total*100:.1f}%) ===",
        f"\n=== Null Values (columns with nulls only) ===",
        null_df.to_string() if not null_df.empty else "  No nulls found.",
    ]
    if not stats.empty:
        parts.append(f"\n=== Numeric Stats ===\n{stats.to_string()}")

    return "\n".join(parts)


@mcp.tool()
def find_anomalies(source: str, table: str, column: str) -> str:
    """Find outliers in a numeric column using IQR method.

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        table: table name
        column: numeric column to analyze
    """
    df = _run(source, f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL")
    series = pd.to_numeric(df[column], errors="coerce").dropna()

    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    outliers = series[(series < lower) | (series > upper)]

    if outliers.empty:
        return f"No outliers detected in {source}.{table}.{column}"

    return (
        f"Column: {source}.{table}.{column}  |  Rows analyzed: {len(series):,}\n"
        f"IQR bounds: [{lower:.2f}, {upper:.2f}]\n"
        f"Outliers: {len(outliers):,} ({len(outliers)/len(series)*100:.1f}%)\n"
        f"Outlier range: [{outliers.min():.2f}, {outliers.max():.2f}]"
    )


@mcp.tool()
def column_distribution(source: str, table: str, column: str, top_n: int = 10) -> str:
    """Top-N value counts for categorical columns; bucketed distribution for numeric.

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        table: table name
        column: column to analyze
        top_n: number of top values to show (default 10)
    """
    df = _run(source, f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL")
    series = df[column]
    total = len(series)

    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() / total > 0.8:
        bins = pd.cut(numeric.dropna(), bins=8)
        dist = bins.value_counts().sort_index()
        dist_df = pd.DataFrame({
            "range": dist.index.astype(str),
            "count": dist.values,
            "pct": (dist.values / total * 100).round(1),
        })
        return (
            f"Column: {source}.{table}.{column}  |  Type: numeric  |  Rows: {total:,}\n"
            f"{dist_df.to_string(index=False)}"
        )
    else:
        counts = series.value_counts().head(top_n)
        dist_df = pd.DataFrame({
            "value": counts.index,
            "count": counts.values,
            "pct": (counts.values / total * 100).round(1),
        })
        return (
            f"Column: {source}.{table}.{column}  |  Type: categorical"
            f"  |  Rows: {total:,}  |  Unique: {series.nunique():,}\n"
            f"{dist_df.to_string(index=False)}"
        )


@mcp.tool()
def freshness_check(source: str, table: str, date_col: str) -> str:
    """Check data freshness: latest record, oldest record, and days since last update.

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        table: table name
        date_col: timestamp or date column to check
    """
    df = _run(
        source,
        f"SELECT MIN({date_col}) as oldest, MAX({date_col}) as latest, COUNT(*) as total_rows FROM {table}",
    )
    row = df.iloc[0]
    latest = pd.to_datetime(row["latest"])
    oldest = pd.to_datetime(row["oldest"])
    # normalize to naive for diff
    latest_naive = latest.replace(tzinfo=None) if latest.tzinfo else latest
    oldest_naive = oldest.replace(tzinfo=None) if oldest.tzinfo else oldest
    days_ago = (pd.Timestamp.now() - latest_naive).days
    span_days = (latest_naive - oldest_naive).days

    freshness = "FRESH" if days_ago <= 1 else ("STALE" if days_ago > 7 else "OK")
    return (
        f"Table: {source}.{table}  |  Column: {date_col}  |  Status: {freshness}\n"
        f"Total rows:   {int(row['total_rows']):,}\n"
        f"Latest entry: {latest}  ({days_ago} days ago)\n"
        f"Oldest entry: {oldest}\n"
        f"Data spans:   {span_days} days"
    )


@mcp.tool()
def correlation(source: str, table: str, col1: str, col2: str) -> str:
    """Pearson + Spearman correlation between two numeric columns.

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        table: table name
        col1: first numeric column
        col2: second numeric column
    """
    df = _run(
        source,
        f"SELECT {col1}, {col2} FROM {table} WHERE {col1} IS NOT NULL AND {col2} IS NOT NULL",
    )
    s1 = pd.to_numeric(df[col1], errors="coerce")
    s2 = pd.to_numeric(df[col2], errors="coerce")
    mask = s1.notna() & s2.notna()
    s1, s2 = s1[mask], s2[mask]

    pearson = s1.corr(s2, method="pearson")
    spearman = s1.rank().corr(s2.rank(), method="pearson")  # rank-based, no scipy needed

    strength = "strong" if abs(pearson) >= 0.7 else ("moderate" if abs(pearson) >= 0.4 else "weak")
    direction = "positive" if pearson > 0 else "negative"

    return (
        f"Correlation: {source}.{table} | {col1} vs {col2}  |  Rows: {len(s1):,}\n"
        f"Pearson:  {pearson:+.4f}  ({strength} {direction})\n"
        f"Spearman: {spearman:+.4f}\n\n"
        f"{col1:>25}  mean={s1.mean():.2f}  std={s1.std():.2f}  range=[{s1.min():.2f}, {s1.max():.2f}]\n"
        f"{col2:>25}  mean={s2.mean():.2f}  std={s2.std():.2f}  range=[{s2.min():.2f}, {s2.max():.2f}]"
    )


@mcp.tool()
def compare_tables(source1: str, table1: str, source2: str, table2: str) -> str:
    """Compare two tables: row counts, column counts, shared vs unique columns.

    Args:
        source1: first source name
        table1: first table name
        source2: second source name
        table2: second table name
    """
    count1 = _run(source1, f"SELECT COUNT(*) as n FROM {table1}").iloc[0]["n"]
    count2 = _run(source2, f"SELECT COUNT(*) as n FROM {table2}").iloc[0]["n"]
    cols1 = set(_run(source1, f"SELECT * FROM {table1} LIMIT 1").columns)
    cols2 = set(_run(source2, f"SELECT * FROM {table2} LIMIT 1").columns)

    shared = cols1 & cols2
    only1 = cols1 - cols2
    only2 = cols2 - cols1

    return "\n".join([
        f"{'':25} {source1}.{table1}",
        f"{'vs':25} {source2}.{table2}",
        f"",
        f"{'Row count':20} {int(count1):>12,}  vs  {int(count2):,}",
        f"{'Column count':20} {len(cols1):>12}  vs  {len(cols2)}",
        f"",
        f"Shared columns ({len(shared)}):          {', '.join(sorted(shared)) or 'none'}",
        f"Only in {source1}.{table1} ({len(only1)}):  {', '.join(sorted(only1)) or 'none'}",
        f"Only in {source2}.{table2} ({len(only2)}):  {', '.join(sorted(only2)) or 'none'}",
    ])


@mcp.tool()
def trend_analysis(source: str, table: str, date_col: str, value_col: str, period: str = "month") -> str:
    """Aggregate a metric over time — shows how a value changes by day/week/month.

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        table: table name
        date_col: date or timestamp column to group by
        value_col: numeric column to aggregate (count, sum, avg shown)
        period: 'day', 'week', or 'month' (default: 'month')
    """
    if period not in {"day", "week", "month"}:
        return "ERROR: period must be 'day', 'week', or 'month'"

    df = _run(
        source,
        f"SELECT {date_col}, {value_col} FROM {table} "
        f"WHERE {date_col} IS NOT NULL AND {value_col} IS NOT NULL",
    )
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce", utc=True)
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    df = df.dropna()

    freq_map = {"day": "D", "week": "W", "month": "M"}
    df["period"] = df[date_col].dt.to_period(freq_map[period])

    grouped = (
        df.groupby("period")[value_col]
        .agg(count="count", total="sum", avg="mean")
        .reset_index()
    )
    grouped["total"] = grouped["total"].round(2)
    grouped["avg"] = grouped["avg"].round(2)

    return (
        f"Trend: {source}.{table} | {value_col} by {period}\n"
        f"Periods: {len(grouped)}  |  Range: {grouped['period'].iloc[0]} → {grouped['period'].iloc[-1]}\n\n"
        f"{grouped.to_string(index=False)}"
    )


# ── Tier 1: Core DA work ───────────────────────────────────────────────────────

@mcp.tool()
def segment_analysis(source: str, table: str, group_col: str, value_col: str) -> str:
    """GROUP BY a column and show count/sum/mean/median/std per segment.

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        table: table name
        group_col: categorical column to group by
        value_col: numeric column to aggregate
    """
    df = _run(
        source,
        f"SELECT {group_col}, {value_col} FROM {table} "
        f"WHERE {group_col} IS NOT NULL AND {value_col} IS NOT NULL",
    )
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    df = df.dropna()

    grouped = (
        df.groupby(group_col)[value_col]
        .agg(count="count", total="sum", mean="mean", median="median", std="std")
        .reset_index()
        .sort_values("count", ascending=False)
    )
    for col in ["total", "mean", "median", "std"]:
        grouped[col] = grouped[col].round(2)

    return (
        f"Segment analysis: {source}.{table} | {group_col} → {value_col}\n"
        f"Segments: {len(grouped):,}  |  Total rows: {len(df):,}\n\n"
        f"{grouped.to_string(index=False)}"
    )


@mcp.tool()
def period_over_period(
    source: str, table: str, date_col: str, value_col: str, period: str = "month"
) -> str:
    """Show metric totals per period + % change vs previous period (MoM, WoW, YoY).

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        table: table name
        date_col: date or timestamp column
        value_col: numeric column to aggregate
        period: 'day', 'week', 'month', or 'year' (default: 'month')
    """
    if period not in {"day", "week", "month", "year"}:
        return "ERROR: period must be 'day', 'week', 'month', or 'year'"

    df = _run(
        source,
        f"SELECT {date_col}, {value_col} FROM {table} "
        f"WHERE {date_col} IS NOT NULL AND {value_col} IS NOT NULL",
    )
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce", utc=True)
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    df = df.dropna()

    freq_map = {"day": "D", "week": "W", "month": "M", "year": "Y"}
    df["period"] = df[date_col].dt.to_period(freq_map[period])

    grouped = (
        df.groupby("period")[value_col]
        .agg(count="count", total="sum", avg="mean")
        .reset_index()
    )
    grouped["total"] = grouped["total"].round(2)
    grouped["avg"] = grouped["avg"].round(2)
    grouped["change_pct"] = (
        (grouped["total"] - grouped["total"].shift(1)) / grouped["total"].shift(1) * 100
    ).round(1)

    return (
        f"Period-over-period: {source}.{table} | {value_col} by {period}\n"
        f"Periods: {len(grouped)}  |  Range: {grouped['period'].iloc[0]} → {grouped['period'].iloc[-1]}\n\n"
        f"{grouped.to_string(index=False)}"
    )


@mcp.tool()
def top_n_by_group(
    source: str, table: str, group_col: str, value_col: str, n: int = 3
) -> str:
    """Show top-N rows by value within each group (window-function style).

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        table: table name
        group_col: column to group by
        value_col: numeric column to rank by (descending)
        n: how many top rows per group (default 3)
    """
    df = _run(
        source,
        f"SELECT {group_col}, {value_col} FROM {table} "
        f"WHERE {group_col} IS NOT NULL AND {value_col} IS NOT NULL",
    )
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    df = df.dropna()

    df["rank"] = (
        df.groupby(group_col)[value_col]
        .rank(method="dense", ascending=False)
        .astype(int)
    )
    top = df[df["rank"] <= n].sort_values([group_col, "rank"])

    return (
        f"Top {n} by group: {source}.{table} | {group_col} → {value_col}\n"
        f"Groups: {df[group_col].nunique():,}  |  Rows shown: {len(top):,}\n\n"
        f"{top.to_string(index=False)}"
    )


# ── Tier 2: Data quality / pipeline monitoring ─────────────────────────────────

@mcp.tool()
def null_pattern(source: str, table: str, min_nulls: int = 2) -> str:
    """Find rows where multiple columns are NULL simultaneously — reveals structural gaps.

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        table: table name
        min_nulls: minimum number of simultaneous nulls per row (default 2)
    """
    df = _run(source, f"SELECT * FROM {table}")
    total = len(df)

    null_mask = df.isnull()
    nullable_cols = null_mask.columns[null_mask.any()].tolist()

    if len(nullable_cols) < min_nulls:
        return f"Not enough nullable columns ({len(nullable_cols)}) to find {min_nulls}+ simultaneous nulls."

    # build null-pattern per row using numpy for speed
    import numpy as np
    matrix = null_mask[nullable_cols].values
    col_arr = nullable_cols

    patterns = []
    for row in matrix:
        null_cols = tuple(col_arr[i] for i in range(len(col_arr)) if row[i])
        if len(null_cols) >= min_nulls:
            patterns.append(null_cols)

    if not patterns:
        return f"No rows with {min_nulls}+ simultaneous nulls found in {source}.{table}."

    from collections import Counter
    top_patterns = Counter(patterns).most_common(10)
    multi_null_rows = len(patterns)

    lines = [
        f"Null pattern: {source}.{table}  |  min_nulls={min_nulls}",
        f"Rows with {min_nulls}+ simultaneous nulls: {multi_null_rows:,} ({multi_null_rows/total*100:.1f}%)",
        f"",
        f"Top co-null patterns (columns NULL together):",
    ]
    for pattern, count in top_patterns:
        pct = count / total * 100
        lines.append(f"  [{count:6,} rows / {pct:4.1f}%]  {', '.join(pattern)}")

    return "\n".join(lines)


@mcp.tool()
def duplicate_check(source: str, table: str, key_cols: str) -> str:
    """Check for duplicates on specific key columns (not full row).

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        table: table name
        key_cols: comma-separated columns to check, e.g. 'order_id' or 'order_id,product_id'
    """
    cols = [c.strip() for c in key_cols.split(",")]
    col_list = ", ".join(cols)

    dups = _run(
        source,
        f"SELECT {col_list}, COUNT(*) as occurrences "
        f"FROM {table} "
        f"GROUP BY {col_list} "
        f"HAVING COUNT(*) > 1 "
        f"ORDER BY occurrences DESC "
        f"LIMIT 20",
    )
    total = int(_run(source, f"SELECT COUNT(*) as n FROM {table}").iloc[0]["n"])

    if dups.empty:
        return f"✓ No duplicates on [{key_cols}] in {source}.{table} ({total:,} rows)"

    dup_keys = len(dups)
    extra_rows = int(dups["occurrences"].sum()) - dup_keys

    return (
        f"Duplicate check: {source}.{table} | key=[{key_cols}]\n"
        f"Total rows: {total:,}  |  Duplicate keys: {dup_keys:,}  |  Extra rows: {extra_rows:,}\n\n"
        f"Top duplicates:\n{dups.to_string(index=False)}"
    )


@mcp.tool()
def outlier_rows(source: str, table: str, column: str, limit: int = 20) -> str:
    """Return the actual rows containing outliers (IQR method) — full context for investigation.

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        table: table name
        column: numeric column to detect outliers on
        limit: max rows to return (default 20)
    """
    df = _run(source, f"SELECT * FROM {table} WHERE {column} IS NOT NULL")
    series = pd.to_numeric(df[column], errors="coerce")

    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr

    mask = (series < lower) | (series > upper)
    outlier_df = df[mask].sort_values(column, ascending=False).head(limit)

    if outlier_df.empty:
        return f"No outliers detected in {source}.{table}.{column}"

    return (
        f"Outlier rows: {source}.{table}.{column}\n"
        f"IQR bounds: [{lower:.2f}, {upper:.2f}]  |  "
        f"Total outliers: {mask.sum():,}  |  Showing top {len(outlier_df)}\n\n"
        f"{outlier_df.to_string(index=False)}"
    )


# ── Tier 3: Power tools ────────────────────────────────────────────────────────

@mcp.tool()
def export_csv(source: str, sql: str, filename: str) -> str:
    """Run a SELECT query and save the result as a CSV file to the Desktop.

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        sql: SQL SELECT statement
        filename: output filename, e.g. 'report.csv' (saved to ~/Desktop)
    """
    stripped = sql.strip().upper()
    if not (stripped.startswith("SELECT") or stripped.startswith("WITH")):
        return "ERROR: Only SELECT queries are allowed."

    df = _run(source, sql)

    if not os.path.isabs(filename):
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        os.makedirs(desktop, exist_ok=True)
        filepath = os.path.join(desktop, filename)
    else:
        filepath = filename

    if not filepath.endswith(".csv"):
        filepath += ".csv"

    df.to_csv(filepath, index=False)

    return (
        f"✓ Exported {len(df):,} rows × {len(df.columns)} columns\n"
        f"File: {filepath}\n"
        f"Columns: {', '.join(df.columns.tolist())}"
    )


@mcp.tool()
def smart_summary(source: str, table: str) -> str:
    """Auto-generate a narrative summary: size, quality issues, numeric highlights, top categories.

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        table: table name
    """
    df = _run(source, f"SELECT * FROM {table}")
    total = len(df)
    n_cols = len(df.columns)

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = df.select_dtypes(include="object").columns.tolist()
    other_cols = n_cols - len(numeric_cols) - len(cat_cols)

    dups = total - len(df.drop_duplicates())
    null_rates = df.isnull().mean().sort_values(ascending=False)
    severe = null_rates[null_rates > 0.5]
    moderate = null_rates[(null_rates > 0.1) & (null_rates <= 0.5)]

    lines = [
        f"=== Smart Summary: {source}.{table} ===",
        f"",
        f"SIZE",
        f"  {total:,} rows × {n_cols} columns",
        f"  {len(numeric_cols)} numeric  |  {len(cat_cols)} categorical  |  {other_cols} other",
        f"",
        f"DATA QUALITY",
        f"  {'⚠' if dups > 0 else '✓'} Duplicates: {dups:,} ({dups/total*100:.1f}%)",
    ]

    if severe.empty:
        lines.append(f"  ✓ No columns with >50% nulls")
    else:
        lines.append(f"  ⚠ Columns >50% null ({len(severe)}):")
        for col, rate in severe.items():
            lines.append(f"     - {col}: {rate*100:.0f}% null")

    if not moderate.empty:
        names = ", ".join(moderate.index.tolist())
        lines.append(f"  ℹ Columns 10–50% null ({len(moderate)}): {names}")

    if numeric_cols:
        lines += ["", "NUMERIC HIGHLIGHTS"]
        for col in numeric_cols[:5]:
            s = df[col].dropna()
            if s.empty:
                continue
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            iqr = q3 - q1
            n_out = int(((s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)).sum())
            out_note = f"  ⚠ {n_out:,} outliers" if n_out else ""
            lines.append(
                f"  {col}: mean={s.mean():.2f}  median={s.median():.2f}"
                f"  range=[{s.min():.2f}, {s.max():.2f}]{out_note}"
            )

    if cat_cols:
        lines += ["", "CATEGORICAL HIGHLIGHTS"]
        for col in cat_cols[:3]:
            s = df[col].dropna()
            if s.empty:
                continue
            top_val = s.value_counts().index[0]
            top_pct = s.value_counts().iloc[0] / len(s) * 100
            lines.append(
                f"  {col}: {s.nunique():,} unique  |  top='{top_val}' ({top_pct:.1f}%)"
            )

    return "\n".join(lines)


@mcp.tool()
def profile_column(source: str, table: str, column: str) -> str:
    """Full statistical profile of a single column — type, nulls, uniques, distribution, outliers in one shot.

    Args:
        source: one of 'so_survey', 'olist', 'weather', 'jobs', 'uber'
        table: table name
        column: column to profile
    """
    df = _run(source, f"SELECT {column} FROM {table}")
    total = len(df)
    series = df[column]

    null_count = int(series.isnull().sum())
    null_pct = null_count / total * 100
    non_null = series.dropna()
    unique_count = int(non_null.nunique())
    unique_pct = unique_count / len(non_null) * 100 if len(non_null) > 0 else 0

    numeric = pd.to_numeric(non_null, errors="coerce")
    is_numeric = numeric.notna().sum() / len(non_null) > 0.8 if len(non_null) > 0 else False

    lines = [
        f"=== Column Profile: {source}.{table}.{column} ===",
        f"",
        f"OVERVIEW",
        f"  Total rows:    {total:,}",
        f"  Nulls:         {null_count:,} ({null_pct:.1f}%)",
        f"  Non-null:      {len(non_null):,}",
        f"  Unique values: {unique_count:,} ({unique_pct:.1f}% of non-null)",
        f"  Inferred type: {'numeric' if is_numeric else 'categorical / text'}",
    ]

    if is_numeric:
        s = numeric.dropna()
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        n_out = int(((s < lower) | (s > upper)).sum())
        skew = s.skew()
        skew_label = "right-skewed" if skew > 0.5 else ("left-skewed" if skew < -0.5 else "symmetric")

        lines += [
            f"",
            f"NUMERIC STATS",
            f"  Min:     {s.min():>15,.2f}",
            f"  Q1:      {q1:>15,.2f}",
            f"  Median:  {s.median():>15,.2f}",
            f"  Mean:    {s.mean():>15,.2f}",
            f"  Q3:      {q3:>15,.2f}",
            f"  Max:     {s.max():>15,.2f}",
            f"  Std:     {s.std():>15,.2f}",
            f"  Skew:    {skew:>+15.3f}  ({skew_label})",
            f"",
            f"OUTLIERS  (IQR method)",
            f"  Bounds:  [{lower:,.2f}, {upper:,.2f}]",
            f"  Count:   {n_out:,} ({n_out / len(s) * 100:.1f}%)",
            f"  Top 5 extreme: {', '.join(f'{v:,.2f}' for v in s.nlargest(5))}",
        ]
    else:
        top10 = non_null.value_counts().head(10)
        coverage = top10.sum() / len(non_null) * 100

        lines += [
            f"",
            f"TOP VALUES  (top-10 covers {coverage:.1f}% of non-null rows)",
        ]
        for val, cnt in top10.items():
            pct = cnt / len(non_null) * 100
            bar = "█" * max(1, int(pct / 2))
            lines.append(f"  {str(val)[:28]:28}  {cnt:>8,}  {pct:5.1f}%  {bar}")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
