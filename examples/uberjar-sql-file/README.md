# Uberjar: SQL to files

Runs three queries against PostgreSQL every 200 ms (a parameterised single-row SELECT, a multi-row SELECT, and a query on `clock_timestamp()` and `random()` that changes on every read) and writes the results as JSON files.

The configuration is the e2e test case [`ADP-SQL-PILOT`](../../ci/e2e/cases/adapters/sql.json) of SFC's integration tests. The scripts in this folder copy it out of the test collection, so this example runs exactly what CI tests.

## Prerequisites

- A Java 17 (or newer) runtime (Windows: `winget install EclipseAdoptium.Temurin.17.JDK`) and SFC, installed with [sfcup](../../README.md#1-install).
- `jq` on Linux / macOS (`brew install jq` or `apt install jq`); Windows needs nothing extra.
- A PostgreSQL server and `psql`.

## 1. Create the configuration

**Linux / macOS**

```shell
cd examples/uberjar-sql-file
./create.sh
```

**Windows (PowerShell)**

```powershell
cd examples\uberjar-sql-file
.\create.ps1
```

This writes `sql-to-file.json` and `seed.sql`: the case's configuration with its uberjar section, without the CI-only `Metadata` and `Metrics` sections. Its `${...}` placeholders are filled in by SFC from environment variables when it starts.

## 2. Prepare the database

The configuration logs in as `sfc_e2e` with the password `sfc_e2e`. As a PostgreSQL superuser, create that role and a database, then load `seed.sql` (the same commands in PowerShell):

```shell
psql -U postgres -c "CREATE ROLE sfc_e2e LOGIN PASSWORD 'sfc_e2e'"
psql -U postgres -c "CREATE DATABASE sfc_example OWNER sfc_e2e"
psql -h 127.0.0.1 -U sfc_e2e -d sfc_example -f seed.sql
```

## 3. Run SFC

**Linux / macOS**

```shell
mkdir -p out
export SFC_E2E_SINK=out SFC_E2E_DB_PORT=5432 SFC_E2E_DB_DB=sfc_example
sfcx -config sql-to-file.json -info
```

**Windows (PowerShell)**

```powershell
New-Item -ItemType Directory -Force out | Out-Null
$env:SFC_E2E_SINK = "out"; $env:SFC_E2E_DB_PORT = "5432"; $env:SFC_E2E_DB_DB = "sfc_example"
sfcx -config sql-to-file.json -info
```

SFC writes the reads as JSON files into `out/<year>/<month>/<day>/<hour>/<minute>/`. Stop it with `Ctrl-C`.

Docs used: [SQL adapter](../../docs/adapters/sql.md) · [File target](../../docs/targets/file.md) · [Uberjar mode](../../docs/sfc-deployment.md#uberjar) · [All examples](../../docs/examples/README.md)
