#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Accepts TCP connections and never sends a byte: a peer that hangs rather than refuses.

Used to exercise connect and read timeouts deterministically - a closed port fails at once, a silent one
makes the client wait for its own timeout.
"""
import argparse
import socket
import threading

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
a = ap.parse_args()
srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", a.port))
srv.listen(64)
held = []
print(f"silent listener on {a.port}", flush=True)
while True:
    conn, _ = srv.accept()
    held.append(conn)  # keep it open, say nothing
