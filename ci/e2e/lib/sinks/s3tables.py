# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""S3 Tables read-back through the Iceberg REST catalog, filtered by the run marker.

Table metadata cannot say which run wrote a snapshot - SFC adds no snapshot properties and data files are
named by UUID - and the fixture tables are shared by concurrent builds. So the verifier reads rows and keeps
those whose marker column equals this run's marker. Every case configuration maps ``$.metadata.marker`` into
the ``label`` column (or the column named by ``markerColumn``).

    {"kind": "s3tables", "table": "sim_a"}                                   fixture table
    {"kind": "s3tables", "namespace": "sfc_it_<marker>", "table": "t", "cleanup": "namespace"}   AutoCreate
    {"kind": "s3tables", "bucket": "sfc-it-<run>-s3t04-uj", "namespace": "...", "table": "t", "cleanup": "bucket"}

The catalog is the same public S3 Tables Iceberg REST endpoint SFC writes through, signed with SigV4 under
the signing name ``s3tables``.
"""

from __future__ import annotations

from . import Sink, SinkError


class S3TablesSink(Sink):
    kind = "s3tables"

    def prepare(self):
        env = self.ctx.env
        self.region = env.get("SFC_E2E_REGION") or env.get("AWS_REGION")
        account = env.get("SFC_E2E_ACCOUNT")
        bucket = self.spec.get("bucket")
        if bucket:
            bucket = bucket.replace("<run>", env["SFC_E2E_RUN_DASH"]).replace("<mode>", env["SFC_E2E_MODE_CODE"])
            self.bucket_arn = f"arn:aws:s3tables:{self.region}:{account}:bucket/{bucket}"
        else:
            self.bucket_arn = env["SFC_E2E_S3T_BUCKET_ARN"]
        self.namespace = self.spec.get("namespace", env.get("SFC_E2E_S3T_NAMESPACE", "sfc_it")).replace("<marker>", self.ctx.marker)
        self.table = self.spec["table"]
        self.marker_column = self.spec.get("markerColumn", "label")
        cleanup = self.spec.get("cleanup")
        if cleanup == "namespace" and self.ctx.cleanup is not None:
            self.ctx.cleanup.add("s3tables-namespace", table_bucket_arn=self.bucket_arn, namespace=self.namespace)
        elif cleanup == "bucket" and self.ctx.cleanup is not None:
            self.ctx.cleanup.add("s3tables-bucket", table_bucket_arn=self.bucket_arn)
        self._catalog = None
        out = {"SFC_E2E_S3T_RUN_NAMESPACE": self.namespace}
        if bucket:
            out["SFC_E2E_S3T_RUN_BUCKET"] = bucket
        return out

    def poll_interval(self):
        return 3.0

    def _catalog_handle(self):
        if self._catalog is None:
            from pyiceberg.catalog.rest import RestCatalog

            self._catalog = RestCatalog(
                "s3tables",
                uri=f"https://s3tables.{self.region}.amazonaws.com/iceberg",
                warehouse=self.bucket_arn,
                **{"rest.sigv4-enabled": "true", "rest.signing-name": "s3tables", "rest.signing-region": self.region},
            )
        return self._catalog

    def records(self) -> list:
        from pyiceberg.expressions import EqualTo

        try:
            table = self._catalog_handle().load_table(f"{self.namespace}.{self.table}")
        except Exception as e:  # noqa: BLE001 - the table may not exist yet in AutoCreate cases
            if "NoSuchTable" in type(e).__name__ or "NoSuchNamespace" in type(e).__name__ or "404" in str(e):
                return []
            raise
        rows = table.scan(row_filter=EqualTo(self.marker_column, self.ctx.marker)).to_arrow().to_pylist()
        return [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()} for r in rows]

    def schema(self) -> list:
        """The table's current schema as [(name, type, required)] - for AutoCreate assertions."""
        table = self._catalog_handle().load_table(f"{self.namespace}.{self.table}")
        return [(f.name, str(f.field_type), f.required) for f in table.schema().fields]

    def describe(self):
        return {"name": self.name, "kind": self.kind, "table": f"{self.namespace}.{self.table}", "bucket": self.bucket_arn}


def ensure(condition, message):
    if not condition:
        raise SinkError(message)
