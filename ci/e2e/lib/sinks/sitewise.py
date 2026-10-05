# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""SiteWise read-back: property value history, joined across properties by timestamp.

Two modes:

* **alias** (fixture assets) - ``{"kind": "sitewise", "aliasPrefix": "${SFC_E2E_SW_ALIAS_A1}",
  "properties": ["counter", "value", "label", "ok"]}``. Before SFC starts, the fixture asset (``"assetId"``, or
  the ``SFC_E2E_SW_ASSET_A<n>_ID`` paired with that prefix) must carry every ``<aliasPrefix>/<property>`` alias
  (``DescribeAsset``), and the history is read by asset and property id: writing to an alias that is not on an
  asset property silently creates a disassociated data stream, which reading by id can never mistake for the
  asset's data. ``DescribeTimeSeries`` cannot do this check - SiteWise creates a property's time series only
  with its first value, so on a fresh stack it fails for every alias ("didn't contain timeSeries").
* **created** (AssetCreation) - ``{"kind": "sitewise", "assetName": "sfc-it-<marker>-sim", ...}``: the asset
  SFC created is found by name, read by assetId + propertyId, and registered for cleanup together with its
  model.

The fixture assets are shared by concurrent builds, so rows are attributed by the string property that
carries the run marker (``label``): one SFC record writes every property with the same timestamp (cases set
``TimestampPath`` to the record timestamp), so the join by timestamp keeps exactly this run's rows.

SFC counts per-entry rejections as WriteSuccess, so reading values back is the only real verification.
"""

from __future__ import annotations

import datetime as dt
import time

from . import Sink, SinkError


def _variant(v: dict):
    for key in ("doubleValue", "integerValue", "stringValue", "booleanValue"):
        if key in v:
            return v[key]
    return None


def _ts(tqv: dict) -> str:
    t = tqv["timestamp"]
    return f"{t['timeInSeconds']}.{t.get('offsetInNanos', 0):09d}"


class SiteWiseSink(Sink):
    kind = "sitewise"

    def prepare(self):
        import boto3

        self.sw = boto3.client("iotsitewise")
        self.properties = list(self.spec.get("properties", ["counter", "value", "label", "ok"]))
        self.marker_property = self.spec.get("markerProperty", "label")
        self.alias_prefix = self.spec.get("aliasPrefix")
        self._ids: dict[str, dict] = self._fixture_ids() if self.alias_prefix else {}
        self.asset_name = (self.spec.get("assetName") or "").replace("<marker>", self.ctx.marker)
        return {}

    def _fixture_ids(self) -> dict[str, dict]:
        """Each property of the fixture asset that carries ``<aliasPrefix>/<property>``, as asset and property id."""
        env = self.ctx.env
        asset_id = self.spec.get("assetId") or next(
            (env.get(f"SFC_E2E_SW_ASSET_A{n}_ID") for n in (1, 2) if env.get(f"SFC_E2E_SW_ALIAS_A{n}") == self.alias_prefix),
            None)
        if not asset_id:
            raise SinkError(f"no fixture asset for aliasPrefix {self.alias_prefix!r}: set \"assetId\" in the sink spec")
        desc = self.sw.describe_asset(assetId=asset_id)
        by_alias = {p["alias"]: p for p in desc.get("assetProperties", []) if p.get("alias")}
        ids = {}
        for prop in self.properties:
            alias = f"{self.alias_prefix}/{prop}"
            if alias not in by_alias:
                raise SinkError(f"asset {desc.get('assetName')!r} has no property with alias {alias!r} (it has "
                                f"{sorted(by_alias)}): SFC's writes would land in a disassociated data stream")
            ids[prop] = {"assetId": asset_id, "propertyId": by_alias[alias]["id"], "alias": alias}
        return ids

    def poll_interval(self):
        return 3.0

    def _locate_created(self) -> bool:
        if self._ids:
            return True
        for page in self.sw.get_paginator("list_asset_models").paginate():
            for model in page.get("assetModelSummaries", []):
                if not model["name"].startswith(f"sfc-it-{self.ctx.marker}-"):  # "_ip" is a prefix of "_ipc"
                    continue
                for apage in self.sw.get_paginator("list_assets").paginate(assetModelId=model["id"]):
                    for asset in apage.get("assetSummaries", []):
                        if asset["name"] != self.asset_name or asset["status"]["state"] != "ACTIVE":
                            continue
                        desc = self.sw.describe_asset(assetId=asset["id"])
                        self._ids = {p["name"]: {"assetId": asset["id"], "propertyId": p["id"], "alias": p.get("alias")}
                                     for p in desc["assetProperties"]}
                        if self.ctx.cleanup is not None:
                            self.ctx.cleanup.add("sitewise", asset_id=asset["id"], model_id=model["id"])
                        self.created = {"asset": desc, "modelId": model["id"]}
                        return True
        return False

    def _history(self, **ident) -> list[dict]:
        # Whole seconds: SiteWise rejects a fractional date ("The date can only be in seconds"), and botocore
        # sends a datetime's microseconds.
        start = dt.datetime.fromtimestamp(int(self.ctx.started_at) - 5, dt.timezone.utc)
        end = dt.datetime.fromtimestamp(int(time.time()) + 60, dt.timezone.utc)
        out, token = [], None
        while True:
            kw = dict(startDate=start, endDate=end, timeOrdering="ASCENDING", maxResults=20000, **ident)
            if token:
                kw["nextToken"] = token
            try:
                resp = self.sw.get_asset_property_value_history(**kw)
            except self.sw.exceptions.ResourceNotFoundException:
                return out  # no data stream yet: SiteWise creates it with the property's first value
            out.extend(resp.get("assetPropertyValueHistory", []))
            token = resp.get("nextToken")
            if not token:
                return out

    def records(self) -> list:
        if self.alias_prefix:
            idents = {p: {"assetId": i["assetId"], "propertyId": i["propertyId"]} for p, i in self._ids.items()}
        else:
            if not self._locate_created():
                return []
            idents = {p: {"assetId": self._ids[p]["assetId"], "propertyId": self._ids[p]["propertyId"]}
                      for p in self.properties if p in self._ids}
        by_ts: dict[str, dict] = {}
        for prop, ident in idents.items():
            for tqv in self._history(**ident):
                by_ts.setdefault(_ts(tqv), {"_ts": _ts(tqv)})[prop] = _variant(tqv["value"])
        rows = [r for _, r in sorted(by_ts.items())]
        if self.marker_property in self.properties:
            rows = [r for r in rows if r.get(self.marker_property) == self.ctx.marker]
        return rows

    def describe(self):
        return {"name": self.name, "kind": self.kind, "alias": self.alias_prefix, "asset": self.asset_name}


def wait_active(sw, asset_id: str, timeout: float = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if sw.describe_asset(assetId=asset_id)["assetStatus"]["state"] == "ACTIVE":
            return
        time.sleep(2)
    raise SinkError(f"asset {asset_id} not ACTIVE within {timeout}s")
