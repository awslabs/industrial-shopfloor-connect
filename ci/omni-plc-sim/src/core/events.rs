// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! The events log: one JSON line per connection event and per request,
//! `{"ts", "proto", "conn", "op", "detail", "status"}`.
//!
//! The harness keeps the file as evidence, and a case can read it through the `jsonl` sink, for
//! example to assert the exact requests an adapter sent. A dedicated thread writes and flushes each
//! line, so connection tasks never block on the file.

use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::sync::mpsc::{channel, Sender};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use anyhow::Context;
use serde_json::{json, Value};

use crate::core::clock::now_ms;

#[derive(Clone)]
pub struct Events {
    tx: Option<Sender<String>>,
    next_conn: Arc<AtomicU64>,
}

impl Events {
    /// No log; `emit` does nothing. Tests use this.
    pub fn disabled() -> Events {
        Events { tx: None, next_conn: Arc::new(AtomicU64::new(1)) }
    }

    /// Appends to `path`.
    pub fn to_file(path: &Path) -> anyhow::Result<Events> {
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
            .with_context(|| format!("opening events file {}", path.display()))?;
        let (tx, rx) = channel::<String>();
        std::thread::Builder::new().name("events".into()).spawn(move || {
            for line in rx {
                if file.write_all(line.as_bytes()).and_then(|_| file.write_all(b"\n")).and_then(|_| file.flush()).is_err() {
                    break;
                }
            }
        })?;
        Ok(Events { tx: Some(tx), next_conn: Arc::new(AtomicU64::new(1)) })
    }

    /// A new connection number, 1-based and unique within the process.
    pub fn next_conn(&self) -> u64 {
        self.next_conn.fetch_add(1, Ordering::Relaxed)
    }

    pub fn emit(&self, proto: &str, conn: u64, op: &str, detail: Value, status: &str) {
        if let Some(tx) = &self.tx {
            let line = json!({"ts": now_ms(), "proto": proto, "conn": conn, "op": op, "detail": detail, "status": status});
            let _ = tx.send(line.to_string());
        }
    }
}
