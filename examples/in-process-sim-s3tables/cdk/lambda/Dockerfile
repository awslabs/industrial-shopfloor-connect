# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

FROM public.ecr.aws/lambda/python:3.12

# Pinned deliberately. Avoid exactly 1.5.3: its iceberg extension wrote invalid bare-blob Puffin
# deletion-vector files.
ARG DUCKDB_VERSION=1.5.5
# pytz is not a DuckDB dependency, but DuckDB needs it to materialise a TIMESTAMPTZ into Python.
# Without it, any query that returns a timezone-aware timestamp fails mid-fetch with
# "Required module 'pytz' failed to import". The structured routes return epoch milliseconds and so
# never hit this, but /api/sql can return any column type.
RUN pip install --no-cache-dir "duckdb==${DUCKDB_VERSION}" pytz

# Bake the extensions into the image so cold starts never download them. Only /tmp is writable at
# runtime, so a runtime install would fail anyway, and handler.py sets
# autoinstall_known_extensions=false to make that failure loud rather than silent.
#
# DuckDB has to do the installing itself, because the extension store is layout-sensitive
# (<dir>/<duckdb_version>/<platform>/<name>.duckdb_extension) -- copying files into a flat directory
# makes LOAD fail at cold start. The LOAD pass afterwards confirms the layout actually resolves with
# autoinstall off, i.e. under the same settings the handler uses.
#
# avro is a hard requirement of iceberg ("The iceberg extension requires the avro extension to be
# loaded!") and is missing from the current DuckDB documentation.
ENV DUCKDB_EXTENSION_DIR=/opt/duckdb_extensions
RUN python -c "\
import duckdb;\
con = duckdb.connect();\
con.execute(\"SET extension_directory='/opt/duckdb_extensions'\");\
exts = ('httpfs', 'aws', 'avro', 'iceberg');\
[con.install_extension(e) for e in exts];\
con.execute('SET autoinstall_known_extensions=false');\
con.execute('SET autoload_known_extensions=false');\
[con.execute(f'LOAD {e}') for e in exts];\
print('duckdb', duckdb.__version__, 'loaded', ', '.join(exts));\
con.close()"

COPY handler.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.handler"]
