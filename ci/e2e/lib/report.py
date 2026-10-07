# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Rendering ``results.json`` into a markdown report and a JUnit XML file.

``results.json`` is the single source of truth; both other formats are derived from it, so they cannot
drift apart. Anything that wants the data - a dashboard, a flakiness tracker - reads the JSON rather
than scraping the markdown.

The markdown is written for someone looking at a red build who wants to know, in order: did it pass,
what broke, and how do I reproduce it. Every failure therefore carries the exact
``<launcher> -config <path>`` command that produced it, because the fastest way to debug an end-to-end
failure is to run the one case by hand.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

PASS, FAIL, SKIP, ERROR = "pass", "fail", "skip", "error"

_MARK = {PASS: "✅", FAIL: "❌", SKIP: "—", ERROR: "💥"}


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.1f} s"
    return f"{int(seconds // 60)}m {seconds % 60:.0f}s"


def _truncate(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [{len(text) - limit} more characters, see the artifact]"


def _console_url(run: dict, key: str, folder: bool = True) -> str | None:
    """S3 console link to a key under the run's evidence location, or None without an S3 location.

    Console links rather than presigned URLs: they never expire, and only people with access to the
    stack's account can open them.
    """
    evidence, region = run.get("evidence") or "", run.get("region")
    if not evidence.startswith("s3://") or not region:
        return None
    bucket, _, prefix = evidence[len("s3://"):].partition("/")
    full = f"{prefix.rstrip('/')}/{key}" if prefix else key
    kind = "buckets" if folder else "object"
    return f"https://{region}.console.aws.amazon.com/s3/{kind}/{bucket}?region={region}&prefix={quote(full, safe='')}"


def _case_url(run: dict, c: dict | None) -> str | None:
    """The S3 console folder of one case run's evidence (evidence.py's layout). None for a unit that never
    ran and so has no folder of its own, such as a mode the case does not support."""
    if not c:
        return None
    case_dir = f"{c.get('id')}.{c.get('mode')}"
    if not str(c.get("artifacts", "")).rstrip("/").endswith(case_dir):
        return None
    return _console_url(run, f"cases/{case_dir}/")


def _link(text: str, url: str | None) -> str:
    return f"[{text}]({url})" if url else text


def _evidence_links(run: dict, case_dir: str) -> list[tuple[str, str]]:
    """All S3 console links to a case run's evidence, or none without an S3 location."""
    if _console_url(run, case_dir) is None:
        return []
    return [("case folder", _console_url(run, case_dir)), ("config.json", _console_url(run, case_dir + "config.json", False)),
            ("logs", _console_url(run, case_dir + "logs/")), ("collected records", _console_url(run, case_dir + "collected/")),
            ("metrics", _console_url(run, case_dir + "metrics.jsonl", False))]


def render_markdown(results: dict, budget_bytes: int | None = None) -> str:
    """Build the report. ``budget_bytes`` caps the output for GitHub's step summary.

    ``$GITHUB_STEP_SUMMARY`` truncates **silently** at 1 MiB, which would quietly cut the failure detail
    that matters most, so long sections are replaced with an explicit pointer instead of being cut.
    """
    cases: list[dict] = results.get("cases", [])
    run = results.get("run", {})
    # Every case run named below links to its evidence folder in the S3 console.
    units = {(c.get("id"), c.get("mode")): c for c in cases}

    counts = {v: sum(1 for c in cases if c.get("verdict") == v) for v in (PASS, FAIL, SKIP, ERROR)}
    total = len(cases)
    failed = counts[FAIL] + counts[ERROR]
    overall = "FAILED" if failed else "PASSED"
    badge = "❌" if failed else "✅"

    out: list[str] = []
    w = out.append

    # ------------------------------------------------------------------ 1. verdict
    w(f"# SFC integration tests — {badge} {overall}")
    w("")
    w(
        f"**{counts[PASS]} passed · {counts[FAIL]} failed · {counts[ERROR]} errored · "
        f"{counts[SKIP]} skipped** of {total} in {_fmt_duration(run.get('durationSeconds'))}"
    )
    w("")

    # ------------------------------------------------------------------ 2. matrix
    modes = run.get("modes", [])
    areas = sorted({c.get("area", "?") for c in cases})
    if modes and areas:
        w("## Matrix")
        w("")
        w("| Area | " + " | ".join(modes) + " |")
        w("|---|" + "---|" * len(modes))
        for area in areas:
            row = [f"`{area}`"]
            for mode in modes:
                subset = [c for c in cases if c.get("area") == area and c.get("mode") == mode]
                if not subset:
                    row.append("·")
                    continue
                ok = sum(1 for c in subset if c.get("verdict") == PASS)
                bad = sum(1 for c in subset if c.get("verdict") in (FAIL, ERROR))
                skipped = sum(1 for c in subset if c.get("verdict") == SKIP)
                mark = _MARK[FAIL] if bad else (_MARK[SKIP] if skipped == len(subset) else _MARK[PASS])
                row.append(f"{ok}/{len(subset)} {mark}")
            w("| " + " | ".join(row) + " |")
        w("")
        w("`·` means the area was not run in that mode. Counts are passed / attempted.")
        w("")

    # ------------------------------------------------------------------ 3. mode parity
    parity = results.get("modeParity")
    if parity:
        w("## Mode parity")
        w("")
        w("Identical output across in-process, IPC and uberjar for the same case and configuration. "
          "A divergence here means a component behaves differently depending on how it was loaded.")
        w("")
        w("| Case | Modes compared | Result |")
        w("|---|---|---|")
        for p in parity:
            mark = _MARK[PASS] if p.get("identical") else _MARK[FAIL]
            modes_cell = ", ".join(_link(m, _case_url(run, units.get((p.get("id"), m)))) for m in p.get("modes", []))
            w(f"| `{p.get('id')}` | {modes_cell} | {mark} {p.get('detail', '')} |")
        w("")

    # ------------------------------------------------------------------ 4. failures
    broken = [c for c in cases if c.get("verdict") in (FAIL, ERROR)]
    if broken:
        w("## Failures")
        w("")
        for c in broken:
            w(f"### {_MARK[c['verdict']]} `{c.get('id')}` ({c.get('mode')}) — {c.get('title', '')}")
            w("")
            if c.get("intent"):
                w(f"*{c['intent']}*")
                w("")
            if c.get("pins"):
                w("Guards: " + ", ".join(f"`{p}`" for p in c["pins"]))
                w("")
            if c.get("error"):
                w("```")
                w(_truncate(str(c["error"])))
                w("```")
                w("")
            bad_assertions = [a for a in c.get("assertions", []) if not a.get("ok")]
            if bad_assertions:
                w("| Assertion | Detail | Expected | Actual |")
                w("|---|---|---|---|")
                for a in bad_assertions:
                    exp = json.dumps(a.get("expected"), default=str)
                    act = json.dumps(a.get("actual"), default=str)
                    note = " *(could not evaluate)*" if a.get("invalid") else ""
                    detail = _truncate(str(a.get("detail") or ""), 200).replace("|", "\\|").replace("\n", " ")
                    w(f"| `{a.get('kind')}`{note} | {detail} | `{_truncate(exp, 300)}` | `{_truncate(act, 300)}` |")
                w("")
            if c.get("repro"):
                w("Reproduce:")
                w("")
                w("```shell")
                w(c["repro"])
                w("```")
                w("")
            links = _evidence_links(run, f"cases/{c.get('id')}.{c.get('mode')}/")
            if links:
                w("Evidence (S3 console): " + " · ".join(f"[{name}]({url})" for name, url in links))
                w("")
            elif c.get("artifacts"):
                w(f"Artifacts: `{c['artifacts']}`")
                w("")

    # ------------------------------------------------------------------ 5. SFC's own counters
    counters = [c for c in cases if c.get("metrics")]
    if counters:
        w("## SFC target counters")
        w("")
        w("Read from SFC's own metrics, not from the destination. A case whose payload assertions pass "
          "while `WriteError` is non-zero is reported as a failure — that combination is the signature "
          "of a target that drops data and still exits 0.")
        w("")
        w("| Case | Mode | Target | Writes | WriteSuccess | WriteError | Messages | BytesWritten |")
        w("|---|---|---|---:|---:|---:|---:|---:|")
        for c in counters:
            case_cell = _link(f"`{c.get('id')}`", _case_url(run, c))
            for row in c["metrics"]:
                flag = " ⚠️" if row.get("WriteError") else ""
                w(
                    f"| {case_cell} | {c.get('mode')} | `{row.get('target')}` | "
                    f"{row.get('Writes', 0):g} | {row.get('WriteSuccess', 0):g} | "
                    f"{row.get('WriteError', 0):g}{flag} | "
                    f"{row.get('Messages', 0):g} | {row.get('BytesWritten', 0):g} |"
                )
        w("")

    # ------------------------------------------------------------------ 6. skips
    skips = [c for c in cases if c.get("verdict") == SKIP]
    if skips:
        w("## Skipped")
        w("")
        w("| Case | Mode | Reason |")
        w("|---|---|---|")
        for c in skips:
            case_cell = _link(f"`{c.get('id')}`", _case_url(run, c))
            w(f"| {case_cell} | {c.get('mode')} | {c.get('skipReason', 'no reason given')} |")
        w("")

    # ------------------------------------------------------------------ 7. AWS resources
    aws = results.get("aws")
    if aws:
        w("## AWS resources")
        w("")
        w(f"Stack: `{aws.get('stack', '-')}` · region `{aws.get('region', '-')}` · "
          f"run scope `{aws.get('runId', '-')}`")
        w("")
        w("| Resource | Created | Destroyed |")
        w("|---|---|---|")
        for r in aws.get("resources", []):
            w(f"| `{r.get('id')}` | {r.get('created', '-')} | {r.get('destroyed', '-')} |")
        w("")
        if aws.get("leaked"):
            w(f"> ⚠️ **{len(aws['leaked'])} resource(s) were not destroyed:** "
              + ", ".join(f"`{x}`" for x in aws["leaked"]))
            w("")

    # ------------------------------------------------------------------ 8. not testable here
    untestable = results.get("untestable") or []
    if untestable:
        w("## Not testable here")
        w("")
        w("| Area | Why |")
        w("|---|---|")
        for u in untestable:
            w(f"| {u.get('what')} | {u.get('why')} |")
        w("")

    # ------------------------------------------------------------------ 9. all cases
    by_id: dict[str, dict] = {}
    for c in cases:
        row = by_id.setdefault(c.get("id"), {"case": c, "modes": {}})
        row["modes"][c.get("mode")] = c
    w("## All cases")
    w("")
    w("| Case | Area | Priority | " + " | ".join(modes) + " | Title |")
    w("|---|---|---|" + "---|" * len(modes) + "---|")
    for case_id, row in by_id.items():
        c = row["case"]
        cells = []
        for mode in modes:
            r = row["modes"].get(mode)
            cells.append("·" if r is None else _link(f"{_MARK.get(r.get('verdict'), '?')} {_fmt_duration(r.get('durationSeconds'))}",
                                                     _case_url(run, r)))
        w(f"| `{case_id}` | `{c.get('area')}` | {c.get('priority', '-')} | " + " | ".join(cells) + f" | {c.get('title', '')} |")
    w("")

    # ------------------------------------------------------------------ provenance
    env = run.get("environment") or {}
    if env:
        w("## Environment")
        w("")
        for k in sorted(env):
            w(f"- **{k}**: `{env[k]}`")
        w("")

    text = "\n".join(out)

    if budget_bytes is not None and len(text.encode("utf-8")) > budget_bytes:
        # Re-render without the two unbounded sections rather than cutting mid-table.
        trimmed = dict(results)
        trimmed["cases"] = [
            {k: v for k, v in c.items() if k != "assertions"} if c.get("verdict") == PASS else c
            for c in cases
        ]
        short = render_markdown(trimmed, budget_bytes=None)
        if len(short.encode("utf-8")) > budget_bytes:
            keep = [c for c in cases if c.get("verdict") in (FAIL, ERROR, SKIP)]
            minimal = dict(results, cases=keep)
            short = render_markdown(minimal, budget_bytes=None)
            short += ("\n\n> Report truncated to fit the step-summary limit. "
                      "The full report and per-case artifacts are attached to this run.\n")
        return short

    return text


def render_junit(results: dict) -> str:
    """One ``<testsuite>`` per area+mode, so CI shows area-level pass rates without parsing markdown."""
    cases = results.get("cases", [])
    suites: dict[tuple[str, str], list[dict]] = {}
    for c in cases:
        suites.setdefault((c.get("area", "?"), c.get("mode", "?")), []).append(c)

    root = ET.Element("testsuites")
    for (area, mode), members in sorted(suites.items()):
        suite = ET.SubElement(
            root,
            "testsuite",
            {
                "name": f"sfc-e2e.{area}.{mode}",
                "tests": str(len(members)),
                "failures": str(sum(1 for c in members if c.get("verdict") == FAIL)),
                "errors": str(sum(1 for c in members if c.get("verdict") == ERROR)),
                "skipped": str(sum(1 for c in members if c.get("verdict") == SKIP)),
                "time": f"{sum(c.get('durationSeconds') or 0 for c in members):.3f}",
            },
        )
        props = ET.SubElement(suite, "properties")
        for key in ("commit", "sfcVersion", "uberjarSha256", "runId"):
            value = results.get("run", {}).get(key)
            if value:
                ET.SubElement(props, "property", {"name": key, "value": str(value)})

        for c in members:
            # The display name starts with the stable case id so any tool can key on it while a human
            # still reads the title.
            tc = ET.SubElement(
                suite,
                "testcase",
                {
                    "name": f"{c.get('id')} — {c.get('title', '')}",
                    "classname": f"sfc-e2e.{area}.{mode}",
                    "time": f"{c.get('durationSeconds') or 0:.3f}",
                },
            )
            verdict = c.get("verdict")
            if verdict == SKIP:
                ET.SubElement(tc, "skipped", {"message": c.get("skipReason", "")})
            elif verdict in (FAIL, ERROR):
                lines = []
                for a in c.get("assertions", []):
                    if not a.get("ok"):
                        lines.append(
                            f"{a.get('kind')}: {a.get('detail')}\n"
                            f"  expected: {json.dumps(a.get('expected'), default=str)}\n"
                            f"  actual:   {json.dumps(a.get('actual'), default=str)}"
                        )
                if c.get("error"):
                    lines.append(str(c["error"]))
                tag = "failure" if verdict == FAIL else "error"
                node = ET.SubElement(tc, tag, {"message": (lines[0].splitlines()[0] if lines else "failed")})
                node.text = "\n\n".join(lines)

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def write_all(results: dict, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "results": out_dir / "results.json",
        "markdown": out_dir / "REPORT.md",
        "junit": out_dir / "junit.xml",
    }
    paths["results"].write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    paths["markdown"].write_text(render_markdown(results) + "\n", encoding="utf-8")
    paths["junit"].write_text(render_junit(results), encoding="utf-8")
    return paths


def main(argv: list[str] | None = None) -> int:
    """``python -m lib.report results.json [--step-summary] [--budget BYTES]``"""
    import argparse

    ap = argparse.ArgumentParser(description="Render an SFC e2e results.json")
    ap.add_argument("results", type=Path)
    ap.add_argument("--budget", type=int, default=None,
                    help="byte budget, for GitHub's 1 MiB step-summary cap")
    args = ap.parse_args(argv)

    data = json.loads(args.results.read_text(encoding="utf-8"))
    print(render_markdown(data, budget_bytes=args.budget))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
