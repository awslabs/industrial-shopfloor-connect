// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! The signals behind every dynamic tag: deterministic functions of the scan number.
//!
//! With `x = 2π·f·t + φ` and `p = frac(f·t + φ/2π)`:
//!
//! | signal | value |
//! |---|---|
//! | sine, cosine | c + A·sin x, c + A·cos x |
//! | tangent, cotangent | c + A·clamp(tan x, ±L), c + A·clamp(cos x / sin x, ±L); sin x = 0 gives c + A·L·sign(cos x) |
//! | exp | c + A·e^(3(p−1)) |
//! | quadratic | c + A·(2p−1)² |
//! | sawtooth, triangle | c + A·(2p−1), c + A·(1 − 4·\|p − ½\|) |
//! | square | c + A while p < ½, else c − A |
//! | damped | c + A·e^(−4p)·sin(2π·5p) |
//! | noise | c + A·(2u − 1), u = splitmix64(0xC0FFEE ⊕ k) |
//! | randomwalk | x₀ = c, then x += 0.02·A·(2u − 1) every scan, u = splitmix64(0x5EED ⊕ k), reflected at c ± A |
//! | blink_1hz, blink_5hz | p < ½ |
//!
//! Every value is finite: SFC's float transformations return null for NaN, and ±Inf is not JSON.

use std::collections::BTreeMap;
use std::f64::consts::TAU;

use anyhow::bail;
use serde::Serialize;

use crate::core::config::SignalOverride;

/// The named signals, in the order of [`Values`].
pub const NAMES: [&str; 14] = [
    "sine", "cosine", "tangent", "cotangent", "exp", "quadratic", "sawtooth", "triangle", "square",
    "damped", "noise", "randomwalk", "blink_1hz", "blink_5hz",
];

const NOISE_SEED: u64 = 0xC0FFEE;
const WALK_SEED: u64 = 0x5EED;

/// One scan's signal values. Every protocol encodes these into its own address space.
#[derive(Debug, Clone, Copy, PartialEq, Default, Serialize)]
pub struct Values {
    pub sine: f64,
    pub cosine: f64,
    pub tangent: f64,
    pub cotangent: f64,
    pub exp: f64,
    pub quadratic: f64,
    pub sawtooth: f64,
    pub triangle: f64,
    pub square: f64,
    pub damped: f64,
    pub noise: f64,
    pub randomwalk: f64,
    pub blink_1hz: bool,
    pub blink_5hz: bool,
}

/// Parameters of one signal.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Params {
    pub amplitude: f64,
    pub offset: f64,
    pub frequency_hz: f64,
    pub phase_rad: f64,
    /// The clamp of tangent and cotangent, in units of the amplitude.
    pub limit: f64,
}

impl Params {
    fn with_frequency(frequency_hz: f64) -> Params {
        Params { amplitude: 100.0, offset: 0.0, frequency_hz, phase_rad: 0.0, limit: 10.0 }
    }
}

/// The default parameters of a named signal.
pub fn default_params(name: &str) -> Option<Params> {
    let f = match name {
        "sine" | "cosine" | "square" | "blink_1hz" => 1.0,
        "tangent" | "cotangent" => 0.25,
        "exp" | "quadratic" | "damped" => 0.5,
        "sawtooth" | "triangle" => 2.0,
        "blink_5hz" => 5.0,
        "noise" | "randomwalk" => 0.0,
        _ => return None,
    };
    Some(Params::with_frequency(f))
}

/// SplitMix64, the deterministic source of noise and the random walk.
pub fn splitmix64(seed: u64) -> u64 {
    let mut z = seed.wrapping_add(0x9E37_79B9_7F4A_7C15);
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

/// A uniform number in [0, 1) for scan `k`.
pub fn unit(seed: u64, k: u64) -> f64 {
    (splitmix64(seed ^ k) >> 11) as f64 / (1u64 << 53) as f64
}

fn frac(v: f64) -> f64 {
    v - v.floor()
}

/// A periodic signal at time `t` (all but noise and the random walk).
pub fn periodic(name: &str, p: &Params, t: f64) -> f64 {
    let (a, c, l) = (p.amplitude, p.offset, p.limit);
    let x = TAU * p.frequency_hz * t + p.phase_rad;
    let ph = frac(p.frequency_hz * t + p.phase_rad / TAU);
    let v = match name {
        "sine" => c + a * x.sin(),
        "cosine" => c + a * x.cos(),
        "tangent" => c + a * x.tan().clamp(-l, l),
        "cotangent" => {
            let s = x.sin();
            if s == 0.0 {
                c + a * l * x.cos().signum()
            } else {
                c + a * (x.cos() / s).clamp(-l, l)
            }
        }
        "exp" => c + a * (3.0 * (ph - 1.0)).exp(),
        "quadratic" => c + a * (2.0 * ph - 1.0).powi(2),
        "sawtooth" => c + a * (2.0 * ph - 1.0),
        "triangle" => c + a * (1.0 - 4.0 * (ph - 0.5).abs()),
        "square" => {
            if ph < 0.5 {
                c + a
            } else {
                c - a
            }
        }
        "damped" => c + a * (-4.0 * ph).exp() * (TAU * 5.0 * ph).sin(),
        _ => c,
    };
    if v.is_finite() {
        v
    } else {
        c
    }
}

/// All signals with their parameters, plus the random walk's state.
#[derive(Debug, Clone)]
pub struct Bank {
    params: BTreeMap<&'static str, Params>,
    walk_k: u64,
    walk_x: f64,
}

impl Bank {
    /// The defaults, with `overrides` (from sim.toml) applied. An unknown signal name is an error.
    pub fn new(overrides: &BTreeMap<String, SignalOverride>) -> anyhow::Result<Bank> {
        let mut params = BTreeMap::new();
        for name in NAMES {
            params.insert(name, default_params(name).expect("every name has defaults"));
        }
        for (name, o) in overrides {
            let Some(p) = params.get_mut(name.as_str()) else {
                bail!("unknown signal {name:?} in [signals]; known: {}", NAMES.join(", "));
            };
            if let Some(v) = o.amplitude {
                p.amplitude = v;
            }
            if let Some(v) = o.offset {
                p.offset = v;
            }
            if let Some(v) = o.frequency_hz {
                p.frequency_hz = v;
            }
            if let Some(v) = o.phase_rad {
                p.phase_rad = v;
            }
            if let Some(v) = o.limit {
                p.limit = v;
            }
            for (field, v) in [("amplitude", p.amplitude), ("offset", p.offset), ("frequency_hz", p.frequency_hz),
                               ("phase_rad", p.phase_rad), ("limit", p.limit)] {
                if !v.is_finite() {
                    bail!("[signals.{name}] {field} must be finite");
                }
            }
        }
        let walk_x = params["randomwalk"].offset;
        Ok(Bank { params, walk_k: 0, walk_x })
    }

    pub fn params(&self, name: &str) -> Option<&Params> {
        self.params.get(name)
    }

    /// The random walk at scan `k`: x₀ = c, then one step per scan, reflected at c ± A. Scans only
    /// move forward; going back recomputes from 0, so the value is a pure function of `k`.
    fn walk(&mut self, k: u64) -> f64 {
        let p = self.params["randomwalk"];
        if k < self.walk_k {
            self.walk_k = 0;
            self.walk_x = p.offset;
        }
        let (lo, hi) = (p.offset - p.amplitude.abs(), p.offset + p.amplitude.abs());
        let step = 0.02 * p.amplitude.abs();
        let mut x = self.walk_x;
        for j in (self.walk_k + 1)..=k {
            x += step * (2.0 * unit(WALK_SEED, j) - 1.0);
            if x > hi {
                x = 2.0 * hi - x;
            }
            if x < lo {
                x = 2.0 * lo - x;
            }
            x = x.clamp(lo, hi);
        }
        self.walk_k = k;
        self.walk_x = x;
        x
    }

    /// Every signal at scan `k`, time `t` seconds.
    pub fn values(&mut self, k: u64, t: f64) -> Values {
        let p = |name: &str| self.params[name];
        let per = |name: &str| periodic(name, &p(name), t);
        let blink = |name: &str| {
            let q = p(name);
            frac(q.frequency_hz * t + q.phase_rad / TAU) < 0.5
        };
        let n = p("noise");
        let noise = n.offset + n.amplitude * (2.0 * unit(NOISE_SEED, k) - 1.0);
        let mut v = Values {
            sine: per("sine"),
            cosine: per("cosine"),
            tangent: per("tangent"),
            cotangent: per("cotangent"),
            exp: per("exp"),
            quadratic: per("quadratic"),
            sawtooth: per("sawtooth"),
            triangle: per("triangle"),
            square: per("square"),
            damped: per("damped"),
            noise,
            randomwalk: 0.0,
            blink_1hz: blink("blink_1hz"),
            blink_5hz: blink("blink_5hz"),
        };
        v.randomwalk = self.walk(k);
        v
    }
}

/// `round(v · scale)`, saturated to i16, the integer form of a signal (`sine_int`).
pub fn scaled_i16(v: f64, scale: f64) -> i16 {
    (v * scale).round().clamp(i16::MIN as f64, i16::MAX as f64) as i16
}

/// `round(v · scale)`, saturated to i32.
pub fn scaled_i32(v: f64, scale: f64) -> i32 {
    (v * scale).round().clamp(i32::MIN as f64, i32::MAX as f64) as i32
}

#[cfg(test)]
mod tests {
    use super::*;

    fn bank() -> Bank {
        Bank::new(&BTreeMap::new()).unwrap()
    }

    #[test]
    fn fixed_points() {
        let mut b = bank();
        let v = b.values(25, 0.25); // a quarter period of the 1 Hz signals
        assert!((v.sine - 100.0).abs() < 1e-9);
        assert!(v.cosine.abs() < 1e-9);
        assert!(v.blink_1hz);
        let v = b.values(75, 0.75);
        assert!((v.sine + 100.0).abs() < 1e-9);
        assert!(!v.blink_1hz);
        assert_eq!(v.square, -100.0);
        let v0 = b.values(0, 0.0);
        assert_eq!(v0.square, 100.0);
        assert_eq!(v0.randomwalk, 0.0);
        assert!((v0.exp - 100.0 * (-3.0f64).exp()).abs() < 1e-9);
        assert!((v0.quadratic - 100.0).abs() < 1e-9);
        assert!((v0.sawtooth + 100.0).abs() < 1e-9);
        assert!((v0.triangle + 100.0).abs() < 1e-9);
        assert_eq!(v0.tangent, 0.0);
        assert_eq!(v0.cotangent, 1000.0); // sin 0 = 0: +L·sign(cos 0)
    }

    #[test]
    fn finite_and_in_range_over_a_million_scans() {
        let mut b = bank();
        for k in 0..1_000_000u64 {
            let t = k as f64 * 0.01;
            let v = b.values(k, t);
            for (name, x, lo, hi) in [
                ("sine", v.sine, -100.0, 100.0), ("cosine", v.cosine, -100.0, 100.0),
                ("tangent", v.tangent, -1000.0, 1000.0), ("cotangent", v.cotangent, -1000.0, 1000.0),
                ("exp", v.exp, 4.97, 100.0), ("quadratic", v.quadratic, 0.0, 100.0),
                ("sawtooth", v.sawtooth, -100.0, 100.0), ("triangle", v.triangle, -100.0, 100.0),
                ("damped", v.damped, -100.0, 100.0), ("noise", v.noise, -100.0, 100.0),
                ("randomwalk", v.randomwalk, -100.0, 100.0),
            ] {
                assert!(x.is_finite() && x >= lo && x <= hi, "{name} = {x} at k = {k}");
            }
            assert!(v.square == 100.0 || v.square == -100.0);
        }
    }

    #[test]
    fn walk_and_noise_are_pure_functions_of_k() {
        let mut a = bank();
        let mut b = bank();
        let x = a.values(500, 5.0);
        for k in 0..=500 {
            b.values(k, k as f64 * 0.01);
        }
        assert_eq!(x.randomwalk, b.values(500, 5.0).randomwalk);
        assert_eq!(x.noise, b.values(500, 5.0).noise);
        assert_ne!(a.values(501, 5.01).randomwalk, x.randomwalk);
    }

    #[test]
    fn overrides() {
        let mut o = BTreeMap::new();
        o.insert("sine".to_string(), SignalOverride { amplitude: Some(50.0), frequency_hz: Some(5.0), ..Default::default() });
        let mut b = Bank::new(&o).unwrap();
        assert!((b.values(5, 0.05).sine - 50.0).abs() < 1e-9);
        o.insert("nope".to_string(), SignalOverride::default());
        assert!(Bank::new(&o).is_err());
    }

    #[test]
    fn scaling_saturates() {
        assert_eq!(scaled_i16(100.0, 100.0), 10000);
        assert_eq!(scaled_i16(1000.0, 100.0), i16::MAX);
        assert_eq!(scaled_i16(-0.005, 100.0), -1); // round half away from zero
        assert_eq!(scaled_i32(-98765.4375, 1.0), -98765);
    }
}
