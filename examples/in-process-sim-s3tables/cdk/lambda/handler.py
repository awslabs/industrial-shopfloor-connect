# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Read-only DuckDB query endpoint over Apache Iceberg tables in Amazon S3 Tables.

Adapted from the AWS sample `ddb-duckdb-analytics`
(https://github.com/aws-samples/aws-dynamodb-examples/tree/master/infrastructure_as_code/cdk/ddb-duckdb-analytics),
which fronts the same idea with an IAM-authorized Lambda function URL and an arbitrary-SQL contract.

Two things are deliberately different here, because a public single-page app in front of an
API Gateway REST API destroys that sample's threat model ("only IAM principals can reach the
function URL"):

1. The contract is structured. Each route composes SQL server-side from identifiers that were
   validated against the live Iceberg catalog. Arbitrary SQL exists only on /api/sql, which the
   CDK app strips from the OpenAPI document unless explicitly enabled.
2. The table bucket is chosen per request, so the catalog is attached per request with
   ATTACH OR REPLACE and detached afterwards. Without that, a warm container would leak one
   caller's catalog alias to the next.

Design notes that are easy to regress:

* Order of the cold-start statements is load-bearing. Several DuckDB settings are irreversible,
  and `lock_configuration` must come last.
* `lock_configuration = true` does NOT block ATTACH. It is enforced only inside the SET/RESET
  operator, so ATTACH / DETACH / CREATE SECRET / LOAD still work on a locked connection. That is
  what makes a caller-supplied table bucket possible on one warm connection.
* `enable_external_access` stays at its default `true`. Iceberg data file paths are discovered at
  query time, so they cannot be allowlisted, and disabling it would block every s3:// read.
* `disabled_filesystems` is NOT set on the structured path: it also breaks /tmp spill and cannot
  be undone. It is set only when free-form SQL is enabled, where reading local files is the
  actual threat.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from typing import Any, Iterable

import duckdb

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# --------------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------------

EXTENSION_DIR = os.environ.get("DUCKDB_EXTENSION_DIR", "/opt/duckdb_extensions")
TABLE_BUCKET_REGION = os.environ["TABLE_BUCKET_REGION"]
ARN_PARTITION = os.environ.get("ARN_PARTITION", "aws")
ACCOUNT_ID = os.environ["ACCOUNT_ID"]

# Empty means "any table bucket in the account", which the stack only grants when deployed with
# -c allowAnyTableBucket=true. Otherwise this is the deploy-time allowlist and IAM is scoped to
# exactly these names, so an off-list name would fail at IAM anyway -- we reject it here first to
# return a clear error instead of an AccessDenied.
ALLOWED_TABLE_BUCKETS = [b for b in os.environ.get("ALLOWED_TABLE_BUCKETS", "").split(",") if b]
ALLOW_ANY_TABLE_BUCKET = os.environ.get("ALLOW_ANY_TABLE_BUCKET", "false").lower() == "true"
ALLOW_FREE_SQL = os.environ.get("ALLOW_FREE_SQL", "false").lower() == "true"

# Keep well under Lambda's 6 MB synchronous response payload. API Gateway's own 10 MB limit is not
# the binding one.
MAX_ROWS = int(os.environ.get("MAX_ROWS", "10000"))
MAX_RESPONSE_BYTES = int(os.environ.get("MAX_RESPONSE_BYTES", str(4 * 1024 * 1024)))
MAX_POINTS_PER_SERIES = int(os.environ.get("MAX_POINTS_PER_SERIES", "2000"))
MAX_SERIES = int(os.environ.get("MAX_SERIES", "24"))
MAX_VALUE_COLUMNS = int(os.environ.get("MAX_VALUE_COLUMNS", "8"))

# Leave headroom under the Lambda timeout so we return our own QUERY_TIMEOUT envelope instead of
# API Gateway's INTEGRATION_TIMEOUT.
QUERY_DEADLINE_SECONDS = float(os.environ.get("QUERY_DEADLINE_SECONDS", "20"))

CORS_ALLOW_ORIGINS = [o for o in os.environ.get("CORS_ALLOW_ORIGINS", "").split(",") if o]
CORS_ALLOW_HEADERS = os.environ.get("CORS_ALLOW_HEADERS", "Authorization,Content-Type")
CORS_ALLOW_METHODS = os.environ.get("CORS_ALLOW_METHODS", "POST,OPTIONS")
CORS_MAX_AGE = os.environ.get("CORS_MAX_AGE", "600")

CATALOG_ALIAS = "ice"

# S3 Tables naming rules. These character classes admit no quote, dot, space or semicolon, which is
# why identifier validation is a whitelist-and-reject rather than an escaping exercise.
# https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-buckets-naming.html
TABLE_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
TABLE_BUCKET_BAD_PREFIXES = ("xn--", "sthree-", "amzn-s3-demo-", "aws")
TABLE_BUCKET_BAD_SUFFIXES = ("-s3alias", "--ol-s3", "--x-s3", "-table-s3")
NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,254}$")
TABLE_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,254}$")

# Bucket widths the UI may land on. Snapping keeps the grid stable while panning, so successive
# requests reuse the same bucket boundaries instead of shifting every pixel.
BUCKET_LADDER_MS = [
    1, 2, 5, 10, 20, 50, 100, 200, 250, 500,
    1_000, 2_000, 5_000, 10_000, 15_000, 30_000,
    60_000, 120_000, 300_000, 600_000, 900_000, 1_800_000,
    3_600_000, 7_200_000, 21_600_000, 43_200_000,
    86_400_000, 604_800_000,
]

TIME_TYPES = ("TIMESTAMP", "DATE", "TIME")
NUMERIC_TYPES = (
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
    "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
    "FLOAT", "DOUBLE", "DECIMAL", "REAL",
)
DIMENSION_TYPES = ("VARCHAR", "BOOLEAN", "UUID", "ENUM")


class ApiError(Exception):
    """An error with a code from the closed ErrorEnvelope enum in openapi.yaml."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# --------------------------------------------------------------------------------------------
# Cold start
# --------------------------------------------------------------------------------------------

_LOCK = threading.Lock()


def _bootstrap() -> duckdb.DuckDBPyConnection:
    """Create the one DuckDB instance this container will use, and apply every setting that does
    not depend on AWS credentials.

    Only an UNNAMED in-memory database gives an isolated instance with its own configuration; any
    file path or named in-memory target is served from a process-global cache and reconnecting with
    a different config raises ConnectionException.

    The credential-dependent part -- CREATE SECRET, and the lockdown that has to follow it -- runs in
    _ensure_ready() on the first request instead, so a credential chain that cannot resolve produces
    a readable error envelope rather than killing the container during import with an opaque 502.
    """
    con = duckdb.connect()

    con.execute(f"SET extension_directory='{EXTENSION_DIR}'")
    # Make a missing baked extension fail loudly instead of silently attempting a download.
    con.execute("SET autoinstall_known_extensions=false")
    con.execute("SET autoload_known_extensions=false")
    con.execute("SET allow_community_extensions=false")
    for ext in ("httpfs", "aws", "avro", "iceberg"):
        con.execute(f"LOAD {ext}")

    # An in-memory database defaults temp_directory to the RELATIVE path ".tmp", i.e.
    # /var/task/.tmp under Lambda, which is read-only. Any spill would fail with an IO error that
    # looks unrelated to configuration.
    con.execute("SET temp_directory='/tmp/duckdb'")
    con.execute("SET home_directory='/tmp'")
    con.execute("SET max_temp_directory_size='1GiB'")

    memory_mb = int(os.environ.get("AWS_LAMBDA_FUNCTION_MEMORY_SIZE", "3008"))
    con.execute(f"SET memory_limit='{max(256, int(memory_mb * 0.65))}MiB'")
    con.execute("SET threads=2")
    # Set before lock_configuration, since afterwards it cannot be changed.
    con.execute("SET TimeZone='UTC'")

    LOG.info("DuckDB %s loaded extensions from %s", duckdb.__version__, EXTENSION_DIR)
    return con


CON = _bootstrap()
_READY = False


def _ensure_ready() -> None:
    """Create the S3 credential secret, then seal the configuration. Runs once per container.

    Split out of _bootstrap because it is the only part that can fail for an environmental reason.
    The order matters and cannot be rearranged:

      1. CREATE SECRET -- resolves the execution role's credentials through DuckDB's credential
         chain. Needs to happen before any ATTACH.
      2. disabled_filesystems -- only when free SQL is enabled, and only after every LOAD, because
         the setting is monotonic and self-sealing.
      3. lock_configuration -- last, because it blocks every later SET.

    lock_configuration deliberately does NOT block ATTACH: it is enforced only inside the SET/RESET
    operator, which is what lets each request attach a different table bucket on this one
    connection.
    """
    global _READY
    if _READY:
        return

    try:
        CON.execute(
            "CREATE OR REPLACE SECRET (TYPE s3, PROVIDER credential_chain, REGION ?)",
            [TABLE_BUCKET_REGION],
        )
    except duckdb.Error as exc:
        raise ApiError(
            500,
            "INTERNAL",
            "Could not resolve AWS credentials for S3 Tables access. In Lambda this means the "
            f"execution role is not usable: {exc}",
        ) from exc

    if ALLOW_FREE_SQL:
        CON.execute("SET disabled_filesystems='LocalFileSystem'")
        LOG.warning(
            "ALLOW_FREE_SQL is enabled. /api/sql accepts caller SQL; local filesystem access and "
            "DuckDB spill are disabled, but outbound HTTP reads remain reachable. "
            "Do not use this setting on an internet-facing deployment."
        )

    CON.execute("SET allowed_configs=['memory_limit','threads']")
    CON.execute("SET lock_configuration=true")
    _READY = True
    LOG.info("DuckDB configuration sealed; ready for queries")


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------


def _quote_ident(name: str) -> str:
    """Quote an identifier that has already been checked against the live catalog."""
    return '"' + name.replace('"', '""') + '"'


def _validate_table_bucket(name: Any) -> str:
    if not isinstance(name, str) or not TABLE_BUCKET_RE.match(name):
        raise ApiError(400, "BAD_REQUEST", f"Not a valid S3 Tables bucket name: {name!r}")
    if name.startswith(TABLE_BUCKET_BAD_PREFIXES) or name.endswith(TABLE_BUCKET_BAD_SUFFIXES):
        raise ApiError(400, "BAD_REQUEST", f"Reserved S3 bucket name prefix or suffix: {name!r}")
    if not ALLOW_ANY_TABLE_BUCKET and name not in ALLOWED_TABLE_BUCKETS:
        raise ApiError(
            403,
            "FORBIDDEN_BUCKET",
            f"Table bucket {name!r} is not in this deployment's allowlist "
            f"({', '.join(ALLOWED_TABLE_BUCKETS) or 'none'}). "
            "Add it to the tableBucketNames context value and redeploy, or deploy with "
            "-c allowAnyTableBucket=true.",
        )
    return name


def _validate_namespace(name: Any) -> str:
    if not isinstance(name, str) or not NAMESPACE_RE.match(name):
        raise ApiError(400, "BAD_REQUEST", f"Not a valid namespace name: {name!r}")
    return name


def _validate_table(name: Any) -> str:
    if not isinstance(name, str) or not TABLE_RE.match(name):
        raise ApiError(400, "BAD_REQUEST", f"Not a valid table name: {name!r}")
    return name


def _table_bucket_arn(name: str) -> str:
    return f"arn:{ARN_PARTITION}:s3tables:{TABLE_BUCKET_REGION}:{ACCOUNT_ID}:bucket/{name}"


def _classify(duck_type: str) -> str:
    upper = duck_type.upper()
    if upper.startswith(TIME_TYPES):
        return "time"
    if upper.startswith(NUMERIC_TYPES):
        return "numeric"
    if upper.startswith(DIMENSION_TYPES):
        return "dimension"
    return "other"


def _jsonable(value: Any) -> Any:
    """NaN and Infinity are not valid JSON; everything exotic degrades to a string."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if -1e308 < value < 1e308 and value == value else str(value)
    return str(value)


def _snap_bucket_ms(requested: int, span_ms: int, max_points: int) -> int:
    """Pick a bucket width from the ladder, never finer than max_points allows."""
    floor_ms = max(1, span_ms // max(1, max_points))
    target = max(int(requested), floor_ms)
    for candidate in BUCKET_LADDER_MS:
        if candidate >= target:
            return candidate
    return BUCKET_LADDER_MS[-1]


class Deadline:
    def __init__(self, seconds: float) -> None:
        self.expiry = time.monotonic() + seconds

    def check(self) -> None:
        if time.monotonic() > self.expiry:
            raise ApiError(
                504,
                "QUERY_TIMEOUT",
                "The query exceeded this function's internal deadline. Narrow the time window or "
                "widen bucketMs.",
            )


# --------------------------------------------------------------------------------------------
# Catalog access
# --------------------------------------------------------------------------------------------


def _attach(cur: duckdb.DuckDBPyConnection, table_bucket: str) -> None:
    """Attach the caller's table bucket read-only, replacing any previous attachment.

    ATTACH OR REPLACE, not a conditional attach: the alias survives in a warm container, so
    without an unconditional replace on every request one caller could read the catalog another
    caller attached.
    """
    arn = _table_bucket_arn(table_bucket)
    try:
        cur.execute(
            f"ATTACH OR REPLACE '{arn}' AS {CATALOG_ALIAS} "
            "(TYPE iceberg, ENDPOINT_TYPE s3_tables, READ_ONLY)"
        )
    except duckdb.Error as exc:
        text = str(exc)
        if "NoSuchBucket" in text or "not found" in text.lower() or "404" in text:
            raise ApiError(
                404,
                "NOT_FOUND",
                f"Table bucket {table_bucket!r} was not found in {TABLE_BUCKET_REGION}. "
                "If you have not run the SFC simulator yet, start it first -- it creates the "
                "table bucket, namespace and table on its first write.",
            ) from exc
        if "AccessDenied" in text or "403" in text:
            raise ApiError(
                403,
                "ACCESS_DENIED",
                f"This deployment's role may not read table bucket {table_bucket!r}.",
            ) from exc
        raise ApiError(502, "QUERY_ERROR", f"Could not attach the table bucket: {text}") from exc


def _detach(cur: duckdb.DuckDBPyConnection) -> None:
    """Drop the catalog alias so it cannot outlive this request in a warm container.

    DuckDB has no `DETACH IF EXISTS`, so check first -- a request that failed validation before
    attaching would otherwise raise here and mask the real error.
    """
    try:
        attached = cur.execute(
            "SELECT count(*) FROM duckdb_databases() WHERE database_name = ?", [CATALOG_ALIAS]
        ).fetchone()[0]
        if attached:
            cur.execute(f"DETACH {CATALOG_ALIAS}")
    except duckdb.Error:  # pragma: no cover - best effort cleanup
        LOG.warning("Could not detach %s", CATALOG_ALIAS, exc_info=True)


def _describe(cur: duckdb.DuckDBPyConnection, namespace: str, table: str) -> list[dict[str, str]]:
    ref = f"{CATALOG_ALIAS}.{_quote_ident(namespace)}.{_quote_ident(table)}"
    try:
        rows = cur.execute(f"DESCRIBE SELECT * FROM {ref}").fetchall()
    except duckdb.Error as exc:
        raise ApiError(
            404,
            "NOT_FOUND",
            f"Table {namespace}.{table} could not be read: {exc}",
        ) from exc
    return [
        {"name": r[0], "type": str(r[1]), "role": _classify(str(r[1]))}
        for r in rows
    ]


def _resolve_columns(
    columns: list[dict[str, str]],
    requested: Iterable[Any],
    *,
    role: str | None,
    label: str,
) -> list[str]:
    """Map caller-supplied column names onto names the catalog actually reported.

    This is the real security boundary. A name that is not an exact match for a live column never
    reaches the composed SQL.
    """
    by_name = {c["name"]: c for c in columns}
    resolved: list[str] = []
    for raw in requested:
        if not isinstance(raw, str) or raw not in by_name:
            raise ApiError(
                400,
                "BAD_REQUEST",
                f"{label} {raw!r} is not a column of this table. "
                f"Known columns: {', '.join(sorted(by_name)) or 'none'}.",
            )
        if role is not None and by_name[raw]["role"] != role:
            raise ApiError(
                400,
                "BAD_REQUEST",
                f"{label} {raw!r} has role {by_name[raw]['role']!r}, expected {role!r} "
                f"(DuckDB type {by_name[raw]['type']}).",
            )
        if raw not in resolved:
            resolved.append(raw)
    return resolved


def _pick_time_column(columns: list[dict[str, str]], requested: Any) -> str:
    if requested is not None:
        return _resolve_columns(columns, [requested], role="time", label="timeColumn")[0]
    for col in columns:
        if col["role"] == "time":
            return col["name"]
    raise ApiError(
        400,
        "BAD_REQUEST",
        "This table has no timestamp column, so it cannot be charted over time.",
    )


def _window(body: dict[str, Any]) -> tuple[int, int]:
    t0, t1 = body.get("t0Ms"), body.get("t1Ms")
    if not isinstance(t0, int) or not isinstance(t1, int):
        raise ApiError(400, "BAD_REQUEST", "t0Ms and t1Ms must be integer epoch milliseconds.")
    if t1 <= t0:
        raise ApiError(400, "BAD_REQUEST", "t1Ms must be greater than t0Ms.")
    return t0, t1


def _epoch_ms_expr(column: str) -> str:
    """Epoch milliseconds as a BIGINT, for any DuckDB temporal type.

    epoch_us avoids depending on ICU or on a session TimeZone, which cannot be changed once
    lock_configuration is set.
    """
    return f"CAST(epoch_us({_quote_ident(column)}) / 1000 AS BIGINT)"


# --------------------------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------------------------


def op_buckets(cur: duckdb.DuckDBPyConnection, body: dict[str, Any], deadline: Deadline) -> dict:
    if not ALLOW_ANY_TABLE_BUCKET:
        return {
            "tableBuckets": sorted(ALLOWED_TABLE_BUCKETS),
            "allowAny": False,
            "region": TABLE_BUCKET_REGION,
        }
    # Only reachable when the stack granted s3tables:ListTableBuckets.
    import boto3  # imported lazily: the structured paths never need an AWS SDK call

    client = boto3.client("s3tables", region_name=TABLE_BUCKET_REGION)
    names: list[str] = []
    token: str | None = None
    while True:
        deadline.check()
        kwargs = {"maxBuckets": 100}
        if token:
            kwargs["continuationToken"] = token
        page = client.list_table_buckets(**kwargs)
        names.extend(b["name"] for b in page.get("tableBuckets", []))
        token = page.get("continuationToken")
        if not token:
            break
    return {"tableBuckets": sorted(names), "allowAny": True, "region": TABLE_BUCKET_REGION}


def op_catalog(cur: duckdb.DuckDBPyConnection, body: dict[str, Any], deadline: Deadline) -> dict:
    bucket = _validate_table_bucket(body.get("tableBucket"))
    _attach(cur, bucket)
    # duckdb_tables() rather than SHOW ALL TABLES: the latter's column names (database/schema/name)
    # are display-oriented, while this view exposes stable database_name/schema_name/table_name.
    rows = cur.execute(
        "SELECT schema_name, table_name FROM duckdb_tables() "
        "WHERE database_name = ? ORDER BY schema_name, table_name",
        [CATALOG_ALIAS],
    ).fetchall()
    grouped: dict[str, list[str]] = {}
    for schema, table in rows:
        grouped.setdefault(str(schema), []).append(str(table))
    return {
        "tableBucket": bucket,
        "namespaces": [
            {"namespace": ns, "tables": tables} for ns, tables in sorted(grouped.items())
        ],
    }


def op_schema(cur: duckdb.DuckDBPyConnection, body: dict[str, Any], deadline: Deadline) -> dict:
    bucket = _validate_table_bucket(body.get("tableBucket"))
    namespace = _validate_namespace(body.get("namespace"))
    table = _validate_table(body.get("table"))
    _attach(cur, bucket)
    return {
        "tableBucket": bucket,
        "namespace": namespace,
        "table": table,
        "columns": _describe(cur, namespace, table),
    }


def op_extent(cur: duckdb.DuckDBPyConnection, body: dict[str, Any], deadline: Deadline) -> dict:
    bucket = _validate_table_bucket(body.get("tableBucket"))
    namespace = _validate_namespace(body.get("namespace"))
    table = _validate_table(body.get("table"))
    _attach(cur, bucket)
    columns = _describe(cur, namespace, table)
    time_col = _pick_time_column(columns, body.get("timeColumn"))
    ref = f"{CATALOG_ALIAS}.{_quote_ident(namespace)}.{_quote_ident(table)}"
    ms = _epoch_ms_expr(time_col)
    deadline.check()
    row = cur.execute(f"SELECT min({ms}), max({ms}), count(*) FROM {ref}").fetchone()
    return {
        "minMs": row[0],
        "maxMs": row[1],
        "rowCount": row[2],
        "timeColumn": time_col,
    }


def op_distinct(cur: duckdb.DuckDBPyConnection, body: dict[str, Any], deadline: Deadline) -> dict:
    bucket = _validate_table_bucket(body.get("tableBucket"))
    namespace = _validate_namespace(body.get("namespace"))
    table = _validate_table(body.get("table"))
    _attach(cur, bucket)
    columns = _describe(cur, namespace, table)
    column = _resolve_columns(
        columns, [body.get("dimensionColumn")], role="dimension", label="dimensionColumn"
    )[0]
    limit = min(int(body.get("limit") or 200), 1000)
    ref = f"{CATALOG_ALIAS}.{_quote_ident(namespace)}.{_quote_ident(table)}"
    deadline.check()
    rows = cur.execute(
        f"SELECT DISTINCT {_quote_ident(column)} AS v FROM {ref} "
        f"WHERE v IS NOT NULL ORDER BY v LIMIT {limit + 1}"
    ).fetchall()
    values = [_jsonable(r[0]) for r in rows[:limit]]
    return {"column": column, "values": values, "truncated": len(rows) > limit}


def _series_sql(
    namespace: str,
    table: str,
    time_col: str,
    value_cols: list[str],
    dim_col: str | None,
) -> str:
    ref = f"{CATALOG_ALIAS}.{_quote_ident(namespace)}.{_quote_ident(table)}"
    ms = _epoch_ms_expr(time_col)
    # Integer-epoch bucketing rather than time_bucket(): no ICU dependency, no session TimeZone,
    # and the boundaries are predictable for any width.
    bucket = f"CAST(FLOOR(CAST({ms} AS DOUBLE) / ?) * ? AS BIGINT)"
    group_expr = _quote_ident(dim_col) if dim_col else "NULL"
    aggregates = ", ".join(
        f"avg(CAST({_quote_ident(c)} AS DOUBLE)), "
        f"min(CAST({_quote_ident(c)} AS DOUBLE)), "
        f"max(CAST({_quote_ident(c)} AS DOUBLE)), "
        f"count({_quote_ident(c)})"
        for c in value_cols
    )
    where = [f"{ms} >= ?", f"{ms} < ?"]
    if dim_col:
        where.append(f"{_quote_ident(dim_col)} IN (SELECT unnest(?::VARCHAR[]))")
    return (
        f"SELECT {bucket} AS bucket_ms, {group_expr} AS dim, {aggregates} "
        f"FROM {ref} WHERE {' AND '.join(where)} "
        "GROUP BY bucket_ms, dim ORDER BY dim, bucket_ms"
    )


def op_series(cur: duckdb.DuckDBPyConnection, body: dict[str, Any], deadline: Deadline) -> dict:
    bucket_name = _validate_table_bucket(body.get("tableBucket"))
    namespace = _validate_namespace(body.get("namespace"))
    table = _validate_table(body.get("table"))
    t0, t1 = _window(body)
    _attach(cur, bucket_name)
    columns = _describe(cur, namespace, table)

    time_col = _pick_time_column(columns, body.get("timeColumn"))
    requested_values = body.get("valueColumns") or []
    if not isinstance(requested_values, list) or not requested_values:
        raise ApiError(400, "BAD_REQUEST", "valueColumns must list at least one numeric column.")
    if len(requested_values) > MAX_VALUE_COLUMNS:
        raise ApiError(
            400, "BAD_REQUEST", f"At most {MAX_VALUE_COLUMNS} value columns per request."
        )
    value_cols = _resolve_columns(columns, requested_values, role="numeric", label="valueColumn")

    dim_col: str | None = None
    dim_values: list[str] = []
    if body.get("dimensionColumn"):
        dim_col = _resolve_columns(
            columns, [body["dimensionColumn"]], role="dimension", label="dimensionColumn"
        )[0]
        dim_values = [str(v) for v in (body.get("dimensionValues") or [])]
        if not dim_values:
            raise ApiError(
                400,
                "BAD_REQUEST",
                "dimensionValues is required when dimensionColumn is set. Call /api/distinct "
                "first to discover them.",
            )
        if len(dim_values) * len(value_cols) > MAX_SERIES:
            raise ApiError(
                400,
                "BAD_REQUEST",
                f"That combination would produce more than {MAX_SERIES} series.",
            )

    max_points = min(int(body.get("maxPoints") or MAX_POINTS_PER_SERIES), MAX_POINTS_PER_SERIES)
    bucket_ms = _snap_bucket_ms(int(body.get("bucketMs") or 1), t1 - t0, max_points)

    sql = _series_sql(namespace, table, time_col, value_cols, dim_col)
    params: list[Any] = [bucket_ms, bucket_ms, t0, t1]
    if dim_col:
        params.append(dim_values)

    deadline.check()
    rows = cur.execute(sql, params).fetchall()

    # key -> points; four aggregate columns per value column, after bucket_ms and dim.
    series: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket_start, dim = row[0], row[1]
        for idx, col in enumerate(value_cols):
            avg, lo, hi, n = row[2 + idx * 4 : 6 + idx * 4]
            if n in (0, None):
                continue
            key = f"{col} / {dim}" if dim_col else col
            entry = series.setdefault(
                key,
                {
                    "key": key,
                    "column": col,
                    "dimension": _jsonable(dim) if dim_col else None,
                    "points": [],
                },
            )
            entry["points"].append(
                [bucket_start, _jsonable(avg), _jsonable(lo), _jsonable(hi), n]
            )

    truncated = False
    for entry in series.values():
        if len(entry["points"]) > max_points:
            entry["points"] = entry["points"][:max_points]
            truncated = True

    return {
        "bucketMs": bucket_ms,
        "t0Ms": t0,
        "t1Ms": t1,
        "timeColumn": time_col,
        "series": list(series.values()),
        "truncated": truncated,
    }


def op_trend(cur: duckdb.DuckDBPyConnection, body: dict[str, Any], deadline: Deadline) -> dict:
    bucket_name = _validate_table_bucket(body.get("tableBucket"))
    namespace = _validate_namespace(body.get("namespace"))
    table = _validate_table(body.get("table"))
    t0, t1 = _window(body)
    _attach(cur, bucket_name)
    columns = _describe(cur, namespace, table)

    time_col = _pick_time_column(columns, body.get("timeColumn"))
    requested_values = body.get("valueColumns") or []
    if not isinstance(requested_values, list) or not requested_values:
        raise ApiError(400, "BAD_REQUEST", "valueColumns must list at least one numeric column.")
    value_cols = _resolve_columns(columns, requested_values, role="numeric", label="valueColumn")

    dim_col: str | None = None
    dim_values: list[str] = []
    if body.get("dimensionColumn"):
        dim_col = _resolve_columns(
            columns, [body["dimensionColumn"]], role="dimension", label="dimensionColumn"
        )[0]
        dim_values = [str(v) for v in (body.get("dimensionValues") or [])]
        if not dim_values:
            raise ApiError(400, "BAD_REQUEST", "dimensionValues is required with dimensionColumn.")

    ref = f"{CATALOG_ALIAS}.{_quote_ident(namespace)}.{_quote_ident(table)}"
    ms = _epoch_ms_expr(time_col)
    # x is seconds since the window start, not raw epoch millis: a 1.7e12 magnitude x destroys the
    # conditioning of the fit and makes the intercept meaningless.
    x = f"(CAST({ms} AS DOUBLE) - {float(t0)}) / 1000.0"
    where = [f"{ms} >= ?", f"{ms} < ?"]
    if dim_col:
        where.append(f"{_quote_ident(dim_col)} IN (SELECT unnest(?::VARCHAR[]))")
    group_expr = _quote_ident(dim_col) if dim_col else "NULL"

    # Argument order is regr_*(y, x) -- dependent variable FIRST. Reversing it returns a
    # plausible-looking wrong slope with no error.
    aggregates = ", ".join(
        f"regr_slope(CAST({_quote_ident(c)} AS DOUBLE), {x}), "
        f"regr_intercept(CAST({_quote_ident(c)} AS DOUBLE), {x}), "
        f"regr_r2(CAST({_quote_ident(c)} AS DOUBLE), {x}), "
        f"corr(CAST({_quote_ident(c)} AS DOUBLE), {x}), "
        f"regr_count(CAST({_quote_ident(c)} AS DOUBLE), {x})"
        for c in value_cols
    )
    sql = (
        f"SELECT {group_expr} AS dim, {aggregates} FROM {ref} "
        f"WHERE {' AND '.join(where)} GROUP BY dim ORDER BY dim"
    )
    params: list[Any] = [t0, t1]
    if dim_col:
        params.append(dim_values)

    deadline.check()
    rows = cur.execute(sql, params).fetchall()

    fits = []
    for row in rows:
        dim = row[0]
        for idx, col in enumerate(value_cols):
            slope, intercept, r2, corr, n = row[1 + idx * 5 : 6 + idx * 5]
            if not n:
                continue
            fits.append(
                {
                    "key": f"{col} / {dim}" if dim_col else col,
                    "column": col,
                    "dimension": _jsonable(dim) if dim_col else None,
                    "slopePerSecond": _jsonable(slope),
                    "intercept": _jsonable(intercept),
                    "r2": _jsonable(r2),
                    "corr": _jsonable(corr),
                    # regr_* aggregates silently skip rows where either input is NULL, so n is not
                    # the row count of the window.
                    "n": n,
                }
            )
    return {"xOriginMs": t0, "t0Ms": t0, "t1Ms": t1, "timeColumn": time_col, "fits": fits}


def _rows_payload(cur: duckdb.DuckDBPyConnection, limit: int) -> dict:
    names = [d[0] for d in cur.description]
    fetched = cur.fetchmany(limit + 1)
    truncated = len(fetched) > limit
    rows = [[_jsonable(v) for v in row] for row in fetched[:limit]]
    return {
        "columns": names,
        "rows": rows,
        "rowCount": len(rows),
        "truncated": truncated,
    }


def op_rows(cur: duckdb.DuckDBPyConnection, body: dict[str, Any], deadline: Deadline) -> dict:
    bucket_name = _validate_table_bucket(body.get("tableBucket"))
    namespace = _validate_namespace(body.get("namespace"))
    table = _validate_table(body.get("table"))
    _attach(cur, bucket_name)
    columns = _describe(cur, namespace, table)
    limit = min(int(body.get("limit") or 200), MAX_ROWS)
    ref = f"{CATALOG_ALIAS}.{_quote_ident(namespace)}.{_quote_ident(table)}"

    # Project temporal columns as epoch milliseconds rather than selecting them raw. Two reasons:
    # the API contract is epoch millis everywhere, and materialising a TIMESTAMPTZ into Python needs
    # pytz, whose absence would surface as an opaque InvalidInputException mid-fetch.
    projection = ", ".join(
        f"{_epoch_ms_expr(c['name'])} AS {_quote_ident(c['name'])}"
        if c["role"] == "time"
        else f"{_quote_ident(c['name'])}::VARCHAR AS {_quote_ident(c['name'])}"
        if c["role"] == "other"
        else _quote_ident(c["name"])
        for c in columns
    )

    params: list[Any] = []
    where = ""
    order = ""
    if body.get("t0Ms") is not None and body.get("t1Ms") is not None:
        t0, t1 = _window(body)
        time_col = _pick_time_column(columns, body.get("timeColumn"))
        ms = _epoch_ms_expr(time_col)
        where = f"WHERE {ms} >= ? AND {ms} < ?"
        order = f"ORDER BY {_quote_ident(time_col)} DESC"
        params = [t0, t1]
    elif any(c["role"] == "time" for c in columns):
        time_col = _pick_time_column(columns, body.get("timeColumn"))
        order = f"ORDER BY {_quote_ident(time_col)} DESC"

    deadline.check()
    cur.execute(f"SELECT {projection} FROM {ref} {where} {order} LIMIT {limit + 1}", params)
    return _rows_payload(cur, limit)


_FORBIDDEN_STATEMENTS = re.compile(
    r"^\s*(ATTACH|DETACH|COPY|INSTALL|LOAD|PRAGMA|SET|RESET|CALL|CREATE|DROP|ALTER|INSERT|UPDATE"
    r"|DELETE|EXPORT|IMPORT|CHECKPOINT|VACUUM|ANALYZE)\b",
    re.IGNORECASE,
)
_FORBIDDEN_FUNCTIONS = re.compile(
    r"\b(read_text|read_blob|read_csv|read_csv_auto|read_json|read_json_auto|read_parquet"
    r"|read_ndjson|glob|sniff_csv|parquet_scan|csv_scan|json_scan|delta_scan|iceberg_scan"
    r"|postgres_scan|mysql_scan|sqlite_scan)\s*\(",
    re.IGNORECASE,
)


def op_sql(cur: duckdb.DuckDBPyConnection, body: dict[str, Any], deadline: Deadline) -> dict:
    if not ALLOW_FREE_SQL:
        raise ApiError(
            403,
            "SQL_DISABLED",
            "Free-form SQL is disabled in this deployment. Redeploy with -c allowFreeSql=true to "
            "enable it, and read the security note in the README first.",
        )
    bucket_name = _validate_table_bucket(body.get("tableBucket"))
    sql = body.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise ApiError(400, "BAD_REQUEST", "sql must be a non-empty string.")

    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as exc:
        raise ApiError(400, "QUERY_ERROR", f"Could not parse the statement: {exc}") from exc
    if len(statements) != 1:
        raise ApiError(400, "BAD_REQUEST", "Send exactly one statement.")
    if _FORBIDDEN_STATEMENTS.match(sql) or _FORBIDDEN_FUNCTIONS.search(sql):
        raise ApiError(
            400,
            "BAD_REQUEST",
            "Only a single SELECT or WITH query over the attached catalog is accepted. "
            "Statements that change state, load extensions or read files are rejected.",
        )

    _attach(cur, bucket_name)
    limit = min(int(body.get("limit") or 1000), MAX_ROWS)
    deadline.check()
    cur.execute(sql)
    return _rows_payload(cur, limit)


ROUTES = {
    "/api/buckets": op_buckets,
    "/api/catalog": op_catalog,
    "/api/schema": op_schema,
    "/api/extent": op_extent,
    "/api/distinct": op_distinct,
    "/api/series": op_series,
    "/api/trend": op_trend,
    "/api/rows": op_rows,
    "/api/sql": op_sql,
}


# --------------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------------


def _cors_headers(event: dict) -> dict[str, str]:
    """Echo the request Origin when it is allowed, so more than one origin can be permitted."""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    origin = headers.get("origin")
    allowed = origin if origin and origin in CORS_ALLOW_ORIGINS else (
        CORS_ALLOW_ORIGINS[0] if CORS_ALLOW_ORIGINS else None
    )
    if not allowed:
        return {}
    return {
        "Access-Control-Allow-Origin": allowed,
        "Access-Control-Allow-Headers": CORS_ALLOW_HEADERS,
        "Access-Control-Allow-Methods": CORS_ALLOW_METHODS,
        "Access-Control-Max-Age": CORS_MAX_AGE,
        "Vary": "Origin",
    }


def _response(status: int, payload: dict, event: dict) -> dict:
    body = json.dumps(payload, separators=(",", ":"))
    if len(body.encode("utf-8")) > MAX_RESPONSE_BYTES:
        return _response(
            413,
            {
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "The result is too large to return. Reduce limit or maxPoints, or "
                    "widen bucketMs.",
                    "requestId": (event.get("requestContext") or {}).get("requestId", ""),
                }
            },
            event,
        )
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **_cors_headers(event)},
        "body": body,
    }


def _error(status: int, code: str, message: str, event: dict) -> dict:
    return _response(
        status,
        {
            "error": {
                "code": code,
                "message": message,
                # The API Gateway request id, not context.aws_request_id: this is the value in the
                # access log, so a user-reported id can actually be correlated.
                "requestId": (event.get("requestContext") or {}).get("requestId", ""),
            }
        },
        event,
    )


def _parse_body(event: dict) -> dict[str, Any]:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    content_type = (headers.get("content-type") or "").split(";")[0].strip().lower()
    # API Gateway skips body validation entirely when the Content-Type matches no declared media
    # type, so the validator can never be the boundary. Close that here.
    if content_type and content_type != "application/json":
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "Send Content-Type: application/json.")

    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(400, "BAD_REQUEST", f"Body is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ApiError(400, "BAD_REQUEST", "Body must be a JSON object.")
    return parsed


def handler(event: dict, context: Any) -> dict:  # noqa: ANN401 - Lambda signature
    # event.resource is the API Gateway resource path, matched server-side. Never route on a body
    # field, which is caller-controlled.
    resource = event.get("resource") or event.get("path") or ""

    if (event.get("httpMethod") or "").upper() == "OPTIONS":
        return {"statusCode": 204, "headers": _cors_headers(event), "body": ""}

    route = ROUTES.get(resource)
    if route is None:
        return _error(404, "NOT_FOUND", f"No such route: {resource}", event)

    try:
        body = _parse_body(event)
        deadline = Deadline(QUERY_DEADLINE_SECONDS)
        # One DuckDB instance per container; cursor() gives this request its own transaction while
        # sharing the hardened configuration and the attachment.
        with _LOCK:
            _ensure_ready()
            cur = CON.cursor()
            try:
                return _response(200, route(cur, body, deadline), event)
            finally:
                # Never leave a catalog attached: the alias would outlive this request in a warm
                # container and the next caller could read it.
                _detach(cur)
                cur.close()
    except ApiError as exc:
        LOG.info("%s %s: %s", resource, exc.code, exc.message)
        return _error(exc.status, exc.code, exc.message, event)
    except duckdb.Error as exc:
        LOG.exception("DuckDB error on %s", resource)
        try:
            CON.execute("ROLLBACK")
        except duckdb.Error:
            # A failed statement can leave an aborted transaction on the shared connection.
            pass
        return _error(400, "QUERY_ERROR", str(exc), event)
    except Exception as exc:  # noqa: BLE001 - always return the envelope
        LOG.exception("Unhandled error on %s", resource)
        return _error(500, "INTERNAL", f"Unhandled error: {exc}", event)
