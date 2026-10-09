// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! The scan engine: a PLC-style cycle that recomputes every dynamic tag.
//!
//! Scan `k = floor(elapsed_ms / cycle_ms)` (k = 0 at start) runs at `t = k · cycle_ms / 1000` s; a
//! late tick skips scans rather than shifting time. Each scan computes one [`Values`] bank and hands
//! it to every protocol image, which writes it under its own write lock. A request takes the read
//! lock once, so it sees one scan: `scan`, `t` and every signal agree.

use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant};

use crate::core::clock::{now_ms, parse_rfc3339_utc};
use crate::core::config::SimConfig;
use crate::core::signal::{Bank, Values};

pub const DEFAULT_CYCLE_MS: u64 = 10;

/// One scan, as every image sees it.
#[derive(Debug, Clone, Copy)]
pub struct Scan {
    /// Scan number since start.
    pub k: u64,
    /// Simulated seconds: `k · cycle_ms / 1000`.
    pub t: f64,
    pub cycle_ms: u64,
    /// PLC wall clock, Unix milliseconds UTC: `clock_base + k · cycle_ms`.
    pub wall_ms: i64,
    pub v: Values,
}

/// A protocol's memory image. `scan` writes the dynamic tags; it runs under the image's write lock.
pub trait Image: Send + Sync + 'static {
    fn scan(&mut self, s: &Scan);
}

/// What the engine drives: an image behind its lock.
pub trait ScanTarget: Send + Sync {
    fn apply(&self, s: &Scan);
}

impl<T: Image> ScanTarget for RwLock<T> {
    fn apply(&self, s: &Scan) {
        let mut image = self.write().unwrap_or_else(|poisoned| poisoned.into_inner());
        image.scan(s);
    }
}

/// Engine settings: from the command line, overridden by nothing (the CLI wins over sim.toml).
#[derive(Debug, Clone)]
pub struct Settings {
    pub cycle_ms: u64,
    pub clock_base_ms: i64,
}

impl Settings {
    /// `cli_cycle` and `cli_clock` win over sim.toml, which wins over the defaults.
    pub fn resolve(cfg: &SimConfig, cli_cycle: Option<u64>, cli_clock: Option<&str>) -> anyhow::Result<Settings> {
        let cycle_ms = cli_cycle.or(cfg.cycle_ms).unwrap_or(DEFAULT_CYCLE_MS);
        anyhow::ensure!(cycle_ms >= 1, "cycle_ms must be at least 1");
        let clock = cli_clock.map(str::to_string).or_else(|| cfg.clock_base.clone());
        let clock_base_ms = match clock {
            Some(s) => parse_rfc3339_utc(&s)?,
            None => now_ms(),
        };
        Ok(Settings { cycle_ms, clock_base_ms })
    }
}

pub struct Engine {
    bank: Bank,
    settings: Settings,
    targets: Vec<Arc<dyn ScanTarget>>,
    start: Instant,
    last_k: Option<u64>,
}

impl Engine {
    pub fn new(cfg: &SimConfig, settings: Settings, targets: Vec<Arc<dyn ScanTarget>>) -> anyhow::Result<Engine> {
        Ok(Engine { bank: Bank::new(&cfg.signals)?, settings, targets, start: Instant::now(), last_k: None })
    }

    /// The scan `k`, computed but not applied.
    pub fn compute(&mut self, k: u64) -> Scan {
        let cycle = self.settings.cycle_ms;
        let t = k as f64 * cycle as f64 / 1000.0;
        Scan {
            k,
            t,
            cycle_ms: cycle,
            wall_ms: self.settings.clock_base_ms + (k * cycle) as i64,
            v: self.bank.values(k, t),
        }
    }

    /// Computes scan `k` and writes it into every image.
    pub fn apply(&mut self, k: u64) -> Scan {
        let s = self.compute(k);
        for target in &self.targets {
            target.apply(&s);
        }
        self.last_k = Some(k);
        s
    }

    /// Restarts the clock and applies scan 0. Called once, before any listener accepts.
    pub fn start(&mut self) -> Scan {
        self.start = Instant::now();
        self.apply(0)
    }

    /// Applies the scan due now, if it is newer than the last one.
    pub fn step(&mut self) {
        let k = self.start.elapsed().as_millis() as u64 / self.settings.cycle_ms;
        if self.last_k.is_none_or(|last| k > last) {
            self.apply(k);
        }
    }

    /// Runs the cycle forever.
    pub async fn run(mut self) {
        let mut tick = tokio::time::interval(Duration::from_millis(self.settings.cycle_ms));
        tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            tick.tick().await;
            self.step();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Probe {
        seen: Vec<u64>,
    }

    impl Image for Probe {
        fn scan(&mut self, s: &Scan) {
            self.seen.push(s.k);
        }
    }

    #[test]
    fn applies_scans_to_every_target() {
        let probe = Arc::new(RwLock::new(Probe { seen: vec![] }));
        let settings = Settings { cycle_ms: 10, clock_base_ms: 1_000 };
        let target: Arc<dyn ScanTarget> = probe.clone();
        let mut e = Engine::new(&SimConfig::default(), settings, vec![target]).unwrap();
        let s0 = e.start();
        assert_eq!((s0.k, s0.t, s0.wall_ms), (0, 0.0, 1_000));
        let s = e.apply(150);
        assert_eq!((s.t, s.wall_ms), (1.5, 2_500));
        assert_eq!(probe.read().unwrap().seen, vec![0, 150]);
    }

    #[test]
    fn cli_wins_over_sim_toml() {
        let cfg = SimConfig::parse("cycle_ms = 20\nclock_base = \"2024-06-15T12:34:56Z\"\n").unwrap();
        let s = Settings::resolve(&cfg, None, None).unwrap();
        assert_eq!((s.cycle_ms, s.clock_base_ms), (20, 1_718_454_896_000));
        let s = Settings::resolve(&cfg, Some(5), Some("1970-01-01T00:00:01Z")).unwrap();
        assert_eq!((s.cycle_ms, s.clock_base_ms), (5, 1_000));
        assert!(Settings::resolve(&cfg, Some(0), None).is_err());
    }
}
