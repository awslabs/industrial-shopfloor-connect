// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! `sim.toml`: per-case overrides of the scan cycle, the clock and the signal parameters.
//!
//! ```toml
//! cycle_ms = 10
//! clock_base = "2024-06-15T12:34:56Z"
//! [signals.sine]
//! amplitude = 50.0
//! frequency_hz = 5.0
//! ```
//!
//! Unknown keys are rejected, so a typo fails the case at start-up instead of silently using a default.

use std::collections::BTreeMap;
use std::path::Path;

use anyhow::Context;
use serde::Deserialize;

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SimConfig {
    pub cycle_ms: Option<u64>,
    pub clock_base: Option<String>,
    #[serde(default)]
    pub signals: BTreeMap<String, SignalOverride>,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SignalOverride {
    pub amplitude: Option<f64>,
    pub offset: Option<f64>,
    pub frequency_hz: Option<f64>,
    pub phase_rad: Option<f64>,
    pub limit: Option<f64>,
}

impl SimConfig {
    pub fn parse(text: &str) -> anyhow::Result<SimConfig> {
        Ok(toml::from_str(text)?)
    }

    pub fn load(path: &Path) -> anyhow::Result<SimConfig> {
        let text = std::fs::read_to_string(path).with_context(|| format!("reading {}", path.display()))?;
        SimConfig::parse(&text).with_context(|| format!("parsing {}", path.display()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_and_rejects_unknown_keys() {
        let c = SimConfig::parse("cycle_ms = 20\n[signals.sine]\namplitude = 5.0\n").unwrap();
        assert_eq!(c.cycle_ms, Some(20));
        assert_eq!(c.signals["sine"].amplitude, Some(5.0));
        assert!(SimConfig::parse("cycle = 20\n").is_err());
        assert!(SimConfig::parse("[signals.sine]\namp = 5.0\n").is_err());
        assert!(SimConfig::parse("").unwrap().signals.is_empty());
    }
}
