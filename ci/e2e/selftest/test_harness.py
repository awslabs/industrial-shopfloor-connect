# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for harness pieces whose failure would make cases pass or fail for the wrong reason."""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import asserts, deploy, modes, sfcproc, steps  # noqa: E402
from lib.artifacts import Artifacts  # noqa: E402
from lib.sinks import SinkContext  # noqa: E402
from lib.sinks.jsonl import StubAcceptedSink, StubRequestSink  # noqa: E402


def rec(ctr, **extra):
    return {"sources": {"sim": {"values": {"ctr": {"value": ctr}}}}, **extra}


class AssertionsTest(unittest.TestCase):
    def run_one(self, spec, records):
        return asserts.evaluate(asserts.Context(records=records), [spec])[0]

    def test_channel_value_run_detects_duplicates_and_gaps(self):
        self.assertTrue(self.run_one({"kind": "channelValueRun", "source": "sim", "channel": "ctr"},
                                     [rec(3), rec(1), rec(2)]).ok)
        self.assertFalse(self.run_one({"kind": "channelValueRun", "source": "sim", "channel": "ctr"},
                                      [rec(1), rec(2), rec(2)]).ok)
        self.assertFalse(self.run_one({"kind": "channelValueRun", "source": "sim", "channel": "ctr"},
                                      [rec(1), rec(3)]).ok)

    def test_channel_sequence_is_order_sensitive(self):
        spec = {"kind": "channelSequence", "source": "sim", "channel": "ctr", "step": 1}
        self.assertTrue(self.run_one(spec, [rec(1), rec(2), rec(3)]).ok)
        self.assertFalse(self.run_one(spec, [rec(1), rec(3), rec(2)]).ok)

    def test_strict_types_separate_int_and_float(self):
        spec = {"kind": "everyRecord", "path": "sources.sim.values.ctr.value", "equals": 1, "strictTypes": True}
        self.assertTrue(self.run_one(spec, [rec(1)]).ok)
        self.assertFalse(self.run_one(spec, [rec(1.0)]).ok)

    def test_value_set_by_path(self):
        spec = {"kind": "valueSet", "path": "values.a", "values": [1, 2]}
        self.assertTrue(self.run_one(spec, [{"values": {"a": 1}}, {"values": {"a": 2}}, {"values": {"a": 1}}]).ok)
        self.assertFalse(self.run_one(spec, [{"values": {"a": 1}}]).ok)
        tol = {"kind": "valueSet", "path": "v", "values": [0.3], "tolerance": 1e-9}
        self.assertTrue(self.run_one(tol, [{"v": 0.1 + 0.2}]).ok)

    def test_where_filters_before_counting(self):
        spec = {"kind": "recordCount", "equals": 1, "where": {"schedule": "B"}}
        self.assertTrue(self.run_one(spec, [{"schedule": "A"}, {"schedule": "B"}]).ok)

    def test_key_order(self):
        spec = {"kind": "keyOrder", "keys": ["a", "b"]}
        self.assertTrue(self.run_one(spec, [{"a": 1, "b": 2}]).ok)
        self.assertFalse(self.run_one(spec, [{"b": 2, "a": 1}]).ok)

    def test_unknown_kind_is_a_case_bug_not_a_failure(self):
        with self.assertRaises(asserts.AssertError):
            asserts.evaluate(asserts.Context(records=[]), [{"kind": "nope"}])


class StepsTest(unittest.TestCase):
    def test_merge_patch(self):
        base = {"a": {"b": 1, "c": 2}, "d": 3}
        steps._merge(base, {"a": {"b": 9, "c": None}, "e": [1]})
        self.assertEqual(base, {"a": {"b": 9}, "d": 3, "e": [1]})

    def test_expand(self):
        out = steps._expand("${COUNTERPARTS}/x ${SFC_E2E_A}", {"SFC_E2E_A": "1"})
        self.assertTrue(out.endswith("counterparts/x 1"), out)


class ScanTest(unittest.TestCase):
    def test_scan_is_incremental_and_line_complete(self):
        with tempfile.TemporaryDirectory() as d:
            out, err = Path(d) / "o", Path(d) / "e"
            out.write_text("")
            err.write_text("")
            proc = sfcproc.RunningProcess(sfcproc.Launch("p", [], Path(d), {}, out, err), popen=None)
            with open(err, "a") as f:
                f.write("x\nhalf a line Error creating inst")
            self.assertIsNone(proc.scan(["Error creating instance of"]))
            with open(err, "a") as f:
                f.write("ance of Foo\n")
            self.assertIn("Error creating instance of Foo", proc.scan(["Error creating instance of"]))
            self.assertIsNone(proc.scan(["Error creating instance of"]))  # consumed


class IpcStartTest(unittest.TestCase):
    """How an IPC service is known to be up, and the guard that keeps its fixed port free."""

    def _proc(self, d, script):
        out, err = Path(d) / "o", Path(d) / "e"
        return sfcproc.start(sfcproc.Launch("svc", [sys.executable, "-c", script], Path(d), dict(os.environ), out, err))

    def test_the_listening_line_gives_the_bound_address(self):
        with tempfile.TemporaryDirectory() as d:
            # IpcTargetServer.kt:92 writes two spaces after "on".
            p = self._proc(d, "import time; print('Target IPC service started, listening on  10.1.2.3:50001, "
                              "connection type is PlainText', flush=True); time.sleep(30)")
            try:
                self.assertEqual(sfcproc.wait_for_listening(p, 10), "10.1.2.3")
            finally:
                p.stop()

    def test_a_failed_bind_is_told_apart(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._proc(d, "import sys; print('Failed to start server, java.io.IOException: Failed to bind to "
                              "address /10.1.2.3:50000', file=sys.stderr); sys.exit(1)")
            with self.assertRaises(sfcproc.BindError):
                sfcproc.wait_for_listening(p, 10)
            p = self._proc(d, "import sys; sys.exit(1)")
            with self.assertRaises(sfcproc.ProcessError) as e:
                sfcproc.wait_for_listening(p, 10)
            self.assertNotIsInstance(e.exception, sfcproc.BindError)

    def test_a_service_binds_and_listens_over_the_hold(self):
        guard, port = sfcproc.PortGuard(), sfcproc.free_port()
        guard.reserve([port])
        try:
            for _ in range(2):  # and again once the first service has gone
                guard.before_start(port)
                with socket.socket() as srv, socket.socket() as cli:
                    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # as Netty and java.nio do
                    srv.bind(("127.0.0.1", port))
                    srv.listen()
                    cli.connect(("127.0.0.1", port))
            self.assertTrue(guard.bind_over)
        finally:
            guard.release(port)

    def test_after_a_failed_bind_over_the_hold_ports_are_released_before_start(self):
        guard, port = sfcproc.PortGuard(), sfcproc.free_port()
        guard.reserve([port])
        guard.bind_failed(port)
        self.assertFalse(guard.bind_over)
        guard.before_start(port)
        with socket.socket() as srv:  # without SO_REUSEADDR: binds only if nothing holds the port
            srv.bind(("127.0.0.1", port))


class StubSinkTest(unittest.TestCase):
    def test_accepted_records_and_requests(self):
        with tempfile.TemporaryDirectory() as d:
            svc = Path(d) / "services" / "stub"
            svc.mkdir(parents=True)
            body = json.dumps({"metadata": {"marker": "m1"}, "v": 1})
            other = json.dumps({"metadata": {"marker": "m2"}, "v": 2})
            (svc / "capture.jsonl").write_text("\n".join(json.dumps(x) for x in [
                {"op": "SendMessageBatch", "attempt": 1, "status": 400, "entries": [{"id": "a", "body": body, "accepted": False}]},
                {"op": "SendMessageBatch", "attempt": 2, "status": 200, "entries": [
                    {"id": "a", "body": body, "accepted": True}, {"id": "b", "body": other, "accepted": True}]},
            ]) + "\n")
            ctx = SinkContext(case_id="C", mode="uberjar", run_id="b_1", marker="m1", workdir=Path(d), env={}, started_at=0)
            accepted = StubAcceptedSink("main", {"service": "stub"}, ctx)
            accepted.prepare()
            self.assertEqual([r["v"] for r in accepted.records()], [1])  # foreign marker filtered
            requests = StubRequestSink("req", {"service": "stub"}, ctx)
            requests.prepare()
            self.assertEqual([r["status"] for r in requests.records()], [400, 200])


class DeployTest(unittest.TestCase):
    """The three deployment styles (deploy.py) and the rule check that guards every case."""

    UBERJAR = {"AdapterTypes": {"SIM": {"FactoryClassName": "com.amazonaws.sfc.simulator.SimulatorAdapter"}},
               "TargetTypes": {"FILE": {"FactoryClassName": "com.amazonaws.sfc.filetarget.FileTargetWriter"}},
               "ProtocolAdapters": {"Sim": {"AdapterType": "SIM"}}, "Targets": {"File": {"TargetType": "FILE"}}}
    INPROCESS = {"AdapterTypes": {"SIM": {"FactoryClassName": "com.amazonaws.sfc.simulator.SimulatorAdapter",
                                          "JarFiles": ["${SFC_DEPLOYMENT_DIR}/simulator/lib"]}},
                 "TargetTypes": {"FILE": {"FactoryClassName": "com.amazonaws.sfc.filetarget.FileTargetWriter",
                                          "JarFiles": ["${SFC_DEPLOYMENT_DIR}/file-target/lib"]}},
                 "ProtocolAdapters": {"Sim": {"AdapterType": "SIM"}}, "Targets": {"File": {"TargetType": "FILE"}}}
    IPC = {"ProtocolAdapters": {"Sim": {"AdapterType": "SIM", "AdapterServer": "SimServer"}},
           "Targets": {"File": {"TargetType": "FILE", "TargetServer": "FileServer"}},
           "AdapterServers": {"SimServer": {"Address": "${SFC_E2E_IPC_HOST}", "Port": 50000}},
           "TargetServers": {"FileServer": {"Address": "${SFC_E2E_IPC_HOST}", "Port": 50001}}}

    def test_well_formed_configs_pass(self):
        self.assertEqual(deploy.check("uberjar", self.UBERJAR), [])
        self.assertEqual(deploy.check("inprocess", self.INPROCESS), [])
        self.assertEqual(deploy.check("ipc", self.IPC), [])

    def test_each_rule_is_enforced(self):
        self.assertTrue(deploy.check("uberjar", self.INPROCESS))       # JarFiles in an uberjar config
        self.assertTrue(deploy.check("inprocess", self.UBERJAR))       # no JarFiles in an in-process config
        self.assertTrue(deploy.check("ipc", {**self.IPC, "TargetTypes": self.UBERJAR["TargetTypes"]}))  # types in IPC
        no_server = json.loads(json.dumps(self.IPC))
        del no_server["Targets"]["File"]["TargetServer"]
        self.assertTrue(deploy.check("ipc", no_server))
        self.assertTrue(deploy.check("uberjar", {**self.UBERJAR, "AdapterServers": {}}))

    def test_every_case_in_the_repo_follows_the_rules(self):
        from lib import runner

        bad = [(c.id, m, deploy.check(m, c.config_for(m))) for c in runner.discover(None, None, None, None)
               for m in c.modes(list(modes.MODES)) if deploy.check(m, c.config_for(m))]
        self.assertEqual(bad, [])

    def _arts(self, root, modules=()):
        mods = {}
        for m in ("sfc-main", *modules):
            (root / m / "bin").mkdir(parents=True)
            (root / m / "bin" / m).write_text("")
            (root / m / "lib").mkdir()
            mods[m] = root / m
        return Artifacts(root=root, workdir=root, uberjar=root / "u.jar", modules=mods)

    def test_ipc_plan_starts_one_service_per_server_and_leaves_the_config_alone(self):
        with tempfile.TemporaryDirectory() as d:
            arts = self._arts(Path(d), ("simulator", "file-target"))
            env = {}
            plan = deploy.build_plan(mode="ipc", config=json.loads(json.dumps(self.IPC)), artifacts=arts,
                                     case_dir=Path(d) / "c", env=env, other_configs=[self.UBERJAR],
                                     services={"SimServer": {"args": ["-connection", "ServerSideTLS"]}})
            self.assertEqual(json.loads(plan.config_path.read_text()), self.IPC)
            self.assertEqual([s.name for s in plan.services], ["adapter-Sim", "target-File"])
            self.assertTrue(plan.services[0].argv[0].endswith("simulator/bin/simulator"))
            self.assertIn("ServerSideTLS", plan.services[0].argv)
            self.assertEqual(plan.services[0].argv[1:3], ["-port", "50000"])
            self.assertEqual(plan.services[1].argv[1:3], ["-port", "50001"])
            self.assertNotIn("-interface", plan.services[0].argv)

    def test_ipc_module_must_be_known(self):
        with tempfile.TemporaryDirectory() as d:
            arts = self._arts(Path(d))
            with self.assertRaises(modes.ModeError):
                deploy.build_plan(mode="ipc", config=json.loads(json.dumps(self.IPC)), artifacts=arts,
                                  case_dir=Path(d) / "c", env={})

    def test_inprocess_plan_sets_the_deployment_dir(self):
        with tempfile.TemporaryDirectory() as d:
            arts = self._arts(Path(d))
            env = {}
            plan = deploy.build_plan(mode="inprocess", config=json.loads(json.dumps(self.INPROCESS)), artifacts=arts,
                                     case_dir=Path(d) / "c", env=env)
            self.assertEqual(env["SFC_DEPLOYMENT_DIR"], str(arts.workdir))
            self.assertEqual(deploy.required_modules("inprocess", self.INPROCESS, {}, []),
                             {"sfc-main", "simulator", "file-target"})
            self.assertEqual(plan.services, [])

    def test_uberjar_plan_is_java_with_the_uberjar_and_jvm_bounds(self):
        with tempfile.TemporaryDirectory() as d:
            arts = self._arts(Path(d))
            plan = deploy.build_plan(mode="uberjar", config=json.loads(json.dumps(self.UBERJAR)), artifacts=arts,
                                     case_dir=Path(d) / "c", env={})
            for flag in modes.JVM_BOUNDS + ["-nocolor", "com.amazonaws.sfc.MainController"]:
                self.assertIn(flag, plan.main.argv)
            self.assertIn(str(arts.uberjar), plan.main.argv[plan.main.argv.index("-cp") + 1])


if __name__ == "__main__":
    unittest.main()
