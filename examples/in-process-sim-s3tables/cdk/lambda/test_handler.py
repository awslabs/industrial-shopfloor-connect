# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Exercise the SQL the handler composes, without touching AWS.

Run inside the Lambda image, which already has DuckDB and the extensions:

    docker build --platform linux/amd64 -t sfc-duckdb-test lambda/
    docker run --rm --platform linux/amd64 --entrypoint python \
      -e TABLE_BUCKET_REGION=us-west-2 -e ACCOUNT_ID=111122223333 \
      -e ALLOWED_TABLE_BUCKETS=sfc-industrial-data-bucket \
      -e AWS_ACCESS_KEY_ID=x -e AWS_SECRET_ACCESS_KEY=y \
      -v "$PWD/lambda:/opt/test" sfc-duckdb-test /opt/test/test_handler.py

The real ATTACH is replaced by a local in-memory database under the same alias, so the composed SQL
-- time bucketing, the min/max band, the regression, the narrow-table pivot -- runs against data with
the same column types the SFC example writes to Iceberg. Everything else, including identifier
resolution against DESCRIBE, is the production code path.
"""

import json
import sys

import duckdb

import handler

BUCKET = "sfc-industrial-data-bucket"
FAILURES = []


def check(label, actual, expected):
    ok = actual == expected
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {actual!r}" + ("" if ok else f" != {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_that(label, condition, detail=""):
    print(f"{'ok  ' if condition else 'FAIL'} {label}{'' if condition else ' -- ' + str(detail)}")
    if not condition:
        FAILURES.append(label)


def install_fixture():
    """Replace _attach with one that builds a local catalog aliased the same way."""

    def fake_attach(cur, table_bucket):
        handler._validate_table_bucket(table_bucket)
        already = cur.execute(
            "SELECT count(*) FROM duckdb_databases() WHERE database_name = ?",
            [handler.CATALOG_ALIAS],
        ).fetchone()[0]
        if already:
            return
        cur.execute(f"ATTACH ':memory:' AS {handler.CATALOG_ALIAS}")
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {handler.CATALOG_ALIAS}.sfc")

        # Wide shape, exactly as simulator-to-s3tables.json declares it: timestamptz plus float
        # columns, 600 samples at 250 ms.
        cur.execute(
            f"""
            CREATE OR REPLACE TABLE {handler.CATALOG_ALIAS}.sfc.sim AS
            SELECT
              to_timestamp(1750000000 + i * 0.25)                  AS event_time,
              CAST(i % 101 AS FLOAT)                               AS counter,
              CAST(50 + 50 * sin(i / 20.0) AS FLOAT)               AS sinus,
              CAST(i * 0.1 AS FLOAT)                               AS triangle,
              {{'number': 'b1', 'version': 'v1'}}                  AS build_info
            FROM range(0, 600) t(i)
            """
        )

        # Narrow shape, the alternative the README discusses: one row per tag reading.
        cur.execute(
            f"""
            CREATE OR REPLACE TABLE {handler.CATALOG_ALIAS}.sfc.sim_readings AS
            SELECT
              to_timestamp(1750000000 + i * 0.25) AS event_time,
              tag,
              CAST(i * 0.5 AS FLOAT)              AS value
            FROM range(0, 300) t(i)
            CROSS JOIN (SELECT unnest(['spindle_speed', 'coolant_temp']) AS tag)
            """
        )

    handler._attach = fake_attach


def call(resource, body):
    event = {
        "resource": resource,
        "httpMethod": "POST",
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
        "requestContext": {"requestId": "test"},
    }
    response = handler.handler(event, None)
    return response["statusCode"], json.loads(response["body"])


def main():
    install_fixture()
    ref = {"tableBucket": BUCKET, "namespace": "sfc", "table": "sim"}

    status, catalog = call("/api/catalog", {"tableBucket": BUCKET})
    check("catalog status", status, 200)
    tables = {n["namespace"]: sorted(n["tables"]) for n in catalog["namespaces"]}
    check("catalog lists both tables", tables.get("sfc"), ["sim", "sim_readings"])

    status, schema = call("/api/schema", ref)
    check("schema status", status, 200)
    roles = {c["name"]: c["role"] for c in schema["columns"]}
    check("event_time classified as time", roles.get("event_time"), "time")
    check("counter classified as numeric", roles.get("counter"), "numeric")
    # A struct column must not be offered as a chart series.
    check("build_info classified as other", roles.get("build_info"), "other")

    status, extent = call("/api/extent", {**ref, "timeColumn": "event_time"})
    check("extent status", status, 200)
    check("extent row count", extent["rowCount"], 600)
    check("extent spans 150 s", extent["maxMs"] - extent["minMs"], 149750)
    check_that("extent returns epoch millis", isinstance(extent["minMs"], int), extent["minMs"])

    t0, t1 = extent["minMs"], extent["maxMs"] + 1

    # Series at 10 s buckets over 150 s -> 15 buckets.
    status, series = call(
        "/api/series",
        {
            **ref,
            "timeColumn": "event_time",
            "valueColumns": ["sinus", "triangle"],
            "t0Ms": t0,
            "t1Ms": t1,
            "bucketMs": 10_000,
        },
    )
    check("series status", status, 200)
    check("series bucket snapped to ladder", series["bucketMs"], 10_000)
    keys = sorted(s["key"] for s in series["series"])
    check("one series per value column", keys, ["sinus", "triangle"])
    triangle = next(s for s in series["series"] if s["key"] == "triangle")
    check("bucket count over 150 s at 10 s", len(triangle["points"]), 15)
    check("40 samples per 10 s bucket at 250 ms", triangle["points"][0][4], 40)
    first = triangle["points"][0]
    check_that(
        "min <= avg <= max within a bucket",
        first[2] <= first[1] <= first[3],
        first,
    )
    check_that(
        "bucket starts land on the bucket grid",
        all(p[0] % 10_000 == 0 for p in triangle["points"]),
        triangle["points"][0][0],
    )
    check_that(
        "buckets are ascending",
        all(b[0] < a[0] for b, a in zip(triangle["points"], triangle["points"][1:])),
    )

    # triangle is i * 0.1 every 250 ms, i.e. exactly 0.4 per second.
    status, trend = call(
        "/api/trend",
        {**ref, "timeColumn": "event_time", "valueColumns": ["triangle"], "t0Ms": t0, "t1Ms": t1},
    )
    check("trend status", status, 200)
    fit = trend["fits"][0]
    check_that(
        "slope is 0.4 per second",
        abs(fit["slopePerSecond"] - 0.4) < 1e-6,
        fit["slopePerSecond"],
    )
    check_that("a perfect line has r2 = 1", abs(fit["r2"] - 1.0) < 1e-9, fit["r2"])
    check("trend n counts every row", fit["n"], 600)
    check("x origin is the window start", trend["xOriginMs"], t0)

    # Narrow table: pivot on a dimension column.
    narrow = {"tableBucket": BUCKET, "namespace": "sfc", "table": "sim_readings"}
    status, distinct = call("/api/distinct", {**narrow, "dimensionColumn": "tag"})
    check("distinct status", status, 200)
    check("distinct tags", sorted(distinct["values"]), ["coolant_temp", "spindle_speed"])

    status, pivoted = call(
        "/api/series",
        {
            **narrow,
            "timeColumn": "event_time",
            "valueColumns": ["value"],
            "dimensionColumn": "tag",
            "dimensionValues": ["spindle_speed"],
            "t0Ms": t0,
            "t1Ms": t1,
            "bucketMs": 30_000,
        },
    )
    check("pivoted series status", status, 200)
    check("one series per selected tag", [s["key"] for s in pivoted["series"]], ["value / spindle_speed"])
    check("unselected tags are excluded", len(pivoted["series"]), 1)

    status, body = call("/api/series", {**narrow, "timeColumn": "event_time",
                                       "valueColumns": ["value"], "dimensionColumn": "tag",
                                       "t0Ms": t0, "t1Ms": t1, "bucketMs": 1000})
    check("dimensionValues required with dimensionColumn", status, 400)

    status, rows = call("/api/rows", {**ref, "timeColumn": "event_time", "t0Ms": t0, "t1Ms": t1,
                                     "limit": 5})
    check("rows status", status, 200)
    check("rows honours the limit", rows["rowCount"], 5)
    check("rows reports truncation", rows["truncated"], True)
    check_that("rows are newest first",
               rows["rows"][0][rows["columns"].index("event_time")]
               > rows["rows"][1][rows["columns"].index("event_time")])

    # Identifier resolution is the security boundary: only names DESCRIBE reported are accepted.
    status, body = call("/api/series", {**ref, "timeColumn": "event_time",
                                       "valueColumns": ["counter; DROP TABLE sim"],
                                       "t0Ms": t0, "t1Ms": t1, "bucketMs": 1000})
    check("injected column name rejected", status, 400)
    check_that("rejection names the known columns", "Known columns" in body["error"]["message"],
               body["error"]["message"])

    status, body = call("/api/series", {**ref, "timeColumn": "build_info",
                                       "valueColumns": ["counter"],
                                       "t0Ms": t0, "t1Ms": t1, "bucketMs": 1000})
    check("non-time column rejected as time axis", status, 400)

    status, body = call("/api/series", {**ref, "timeColumn": "event_time",
                                       "valueColumns": ["build_info"],
                                       "t0Ms": t0, "t1Ms": t1, "bucketMs": 1000})
    check("non-numeric column rejected as series", status, 400)

    # maxPoints must win over a bucket width finer than it allows.
    status, capped = call("/api/series", {**ref, "timeColumn": "event_time",
                                         "valueColumns": ["counter"], "t0Ms": t0, "t1Ms": t1,
                                         "bucketMs": 1, "maxPoints": 10})
    check("bucket widened to honour maxPoints", capped["bucketMs"], 15_000)
    check_that("point count respects maxPoints",
               len(capped["series"][0]["points"]) <= 10,
               len(capped["series"][0]["points"]))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
