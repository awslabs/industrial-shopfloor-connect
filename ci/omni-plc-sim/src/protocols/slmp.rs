// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! Mitsubishi SLMP / MC protocol server, binary code (SLMP Reference Manual SH-080956ENG; MELSEC
//! Communication Protocol Reference Manual SH-080008 for the QnA-compatible 3E frame of the Q and L CPUs).
//!
//! What SFC's slmp adapter needs: 3E frames framed by their declared length, the routing fields echoed,
//! 0401 batch reads in word and bit units, 0403 random reads with word and double-word entries, the 35
//! device codes of SlmpDevice.kt, and error replies carrying the 9-byte error information. Any end code
//! other than 0000 makes SFC close the connection and wait (SlmpSource.kt:148-176), so every error must be
//! the one the CPU would send. On top of that, as the real CPUs do: 4E frames and the iQ-R device format
//! on iq-r, 0101 Read Type Name, 0619 loopback, the special relays and registers, a running timer and
//! counter, and four CPU profiles with their device ranges and limits. Writes and every other command
//! answer C059, as from a CPU without them.
//!
//! The spec's `[slmp]` section of sim.toml (§3.3) is not read: its defaults are built in (C056 for ranges,
//! long-device codes accepted in the Q/L format, no connection limit, no END-processing delay).
//!
//! Address map: see `--print-map slmp`.

use std::sync::{Arc, RwLock};

use anyhow::bail;
use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

use crate::core::clock::civil;
use crate::core::codec::{hex, Reader};
use crate::core::engine::{Image as ScanImage, Scan, ScanTarget};
use crate::core::events::Events;
use crate::core::signal::scaled_i16;

pub const NAME: &str = "slmp";
pub const DEFAULT_PROFILE: &str = "iq-r";
pub const PROFILES: &[&str] = &["q", "l", "iq-r", "iq-f"];

/// The longest request data length (L) accepted. Every real request is shorter; a longer one means the
/// stream is not SLMP binary any more [policy].
const MAX_LENGTH: usize = 8192;

// End codes. SFC prints the manual's text for each (SlmpError.kt:15-37).
const C051: u16 = 0xC051;
const C052: u16 = 0xC052;
const C054: u16 = 0xC054;
const C056: u16 = 0xC056;
const C059: u16 = 0xC059;
const C05B: u16 = 0xC05B;
const C05C: u16 = 0xC05C;
const C061: u16 = 0xC061;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Clock {
    /// SD210-SD213 in BCD: year/month, day/hour, minute/second, century/day of week (Q, L).
    Bcd,
    /// SD210-SD216 in binary: year, month, day, hour, minute, second, day of week (iQ-R, iQ-F).
    Binary,
}

#[derive(Debug, Clone)]
pub struct Profile {
    pub name: &'static str,
    pub title: &'static str,
    /// 0101 Read Type Name: model name and model code. `None` answers C059, as the Q and L built-in ports
    /// do (plc-comm-slmp records the command as blocked there; the code itself is policy).
    pub type_name: Option<(&'static str, u16)>,
    /// 4E frames (subheader 54 00 with a serial number) besides 3E.
    pub frame_4e: bool,
    /// The iQ-R device format (0401/0002 and 0003, 0403/0002) with its 0403 entry limit.
    pub iqr_format: Option<usize>,
    /// 0401 limit and the end code for exceeding it, in word units and in bit units. Q, L and iQ-R answer
    /// C051 for words and C052 for bits, the opposite of the manual's texts; iQ-F answers as the texts say
    /// [observed on hardware by plc-comm-slmp].
    pub word_units: (u16, u16),
    pub bit_units: (u16, u16),
    /// 0403 entry limit in the Q/L format. 192 on iQ-R is assumed: it was only measured in the iQ-R
    /// format, where it is 96 (spec §9.3).
    pub random: usize,
    pub clock: Clock,
    /// X and Y numbers are octal in MELSEC notation (iQ-F); everywhere else they are hex.
    pub xy_octal: bool,
    /// The FX-compatible extras: SM8000-SM8014 and the SD8013-SD8019 clock.
    pub fx: bool,
    /// Device points by family. A family that is not listed is absent and answers C05B.
    pub points: &'static [(&'static str, u32)],
    /// Device-point registers: (SD number, family, 1 for a word or 2 for a pair, low word first).
    pub point_registers: &'static [(u32, &'static str, u32)],
}

impl Profile {
    fn points_of(&self, family: &str) -> Option<u32> {
        self.points.iter().find(|(f, _)| *f == family).map(|(_, n)| *n)
    }
}

// Device points (spec §3.2): the GX Works2 defaults of QnUDV and LCPU, the GX Works3 defaults of R04 and
// FX5U, and the observed SM/SD sizes of FX5U. R/ZR (32 K words) is a policy size on Q, L and iQ-R, where
// the file register size is a parameter. The iQ-R sizes of LT, LST, LC and S are unverified.
const POINTS_QL: &[(&str, u32)] = &[
    ("SM", 2048), ("SD", 2048), ("X", 8192), ("Y", 8192), ("DX", 8192), ("DY", 8192), ("M", 8192), ("L", 8192),
    ("F", 2048), ("V", 2048), ("B", 8192), ("SB", 2048), ("SW", 2048), ("S", 8192), ("T", 2048), ("ST", 0),
    ("C", 1024), ("D", 12288), ("W", 8192), ("Z", 20), ("R", 32768), ("ZR", 32768),
];
const POINTS_IQR: &[(&str, u32)] = &[
    ("SM", 4096), ("SD", 4096), ("X", 12288), ("Y", 12288), ("DX", 12288), ("DY", 12288), ("M", 12288),
    ("L", 8192), ("F", 2048), ("V", 2048), ("B", 8192), ("SB", 2048), ("SW", 2048), ("S", 0), ("T", 1024),
    ("ST", 0), ("C", 512), ("D", 18432), ("W", 8192), ("Z", 20), ("R", 32768), ("ZR", 32768), ("LT", 1024),
    ("LST", 32), ("LC", 512), ("LZ", 2), ("RD", 0),
];
const POINTS_IQF: &[(&str, u32)] = &[
    ("SM", 10000), ("SD", 12000), ("X", 1024), ("Y", 1024), ("M", 7680), ("L", 7680), ("F", 128), ("B", 256),
    ("SB", 512), ("SW", 512), ("S", 4096), ("T", 512), ("ST", 16), ("C", 256), ("D", 8000), ("W", 512),
    ("Z", 20), ("R", 32768), ("LC", 64), ("LZ", 2),
];

// Device-point registers (spec §4.4, [observed] device-ranges page). Absent families read 0.
const SD_POINTS_QL: &[(u32, &str, u32)] = &[
    (286, "M", 2), (288, "B", 2), (290, "X", 1), (291, "Y", 1), (292, "M", 1), (293, "L", 1), (294, "B", 1),
    (295, "F", 1), (296, "SB", 1), (297, "V", 1), (298, "S", 1), (299, "T", 1), (300, "ST", 1), (301, "C", 1),
    (302, "D", 1), (303, "W", 1), (304, "SW", 1), (306, "ZR", 2), (308, "D", 2), (310, "W", 2),
];
const SD_POINTS_IQR: &[(u32, &str, u32)] = &[
    (260, "X", 2), (262, "Y", 2), (264, "M", 2), (266, "B", 2), (268, "SB", 2), (270, "F", 2), (272, "V", 2),
    (274, "L", 2), (276, "S", 2), (280, "D", 2), (282, "W", 2), (284, "SW", 2), (288, "T", 2), (290, "ST", 2),
    (292, "C", 2), (294, "LT", 2), (296, "LST", 2), (298, "LC", 2), (300, "Z", 1), (302, "LZ", 1),
    (306, "ZR", 2), (308, "RD", 2),
];
const SD_POINTS_IQF: &[(u32, &str, u32)] = &[
    (260, "X", 2), (262, "Y", 2), (264, "M", 2), (266, "B", 2), (268, "SB", 2), (270, "F", 2), (272, "V", 2),
    (274, "L", 2), (276, "S", 2), (280, "D", 2), (282, "W", 2), (284, "SW", 2), (288, "T", 2), (290, "ST", 2),
    (292, "C", 2), (294, "LT", 2), (296, "LST", 2), (298, "LC", 2), (300, "Z", 1), (302, "LZ", 1),
    (304, "R", 2), (306, "ZR", 2), (308, "RD", 2),
];

pub fn profile(name: &str) -> anyhow::Result<Profile> {
    let ql = |name: &'static str, title: &'static str| Profile {
        name,
        title,
        type_name: None,
        frame_4e: false,
        iqr_format: None,
        word_units: (960, C051),
        bit_units: (7168, C052),
        random: 192,
        clock: Clock::Bcd,
        xy_octal: false,
        fx: false,
        points: POINTS_QL,
        point_registers: SD_POINTS_QL,
    };
    Ok(match name {
        "q" => ql("q", "MELSEC-Q Q03UDVCPU, built-in Ethernet port"),
        "l" => ql("l", "MELSEC-L L06CPU, built-in Ethernet port"),
        "iq-r" => Profile {
            name: "iq-r",
            title: "MELSEC iQ-R R04CPU, built-in Ethernet port",
            // The model code is from the manual and unverified on hardware (spec §9.4).
            type_name: Some(("R04CPU", 0x4800)),
            frame_4e: true,
            iqr_format: Some(96),
            word_units: (960, C051),
            bit_units: (7168, C052),
            random: 192,
            clock: Clock::Binary,
            xy_octal: false,
            fx: false,
            points: POINTS_IQR,
            point_registers: SD_POINTS_IQR,
        },
        "iq-f" => Profile {
            name: "iq-f",
            title: "MELSEC iQ-F FX5U-32MR/ES, built-in Ethernet port",
            // Unverified model code; 4E stays off because FX5 support for it is unverified (spec §9.4).
            type_name: Some(("FX5U-32MR/ES", 0x4A21)),
            frame_4e: false,
            iqr_format: None,
            word_units: (960, C052),
            bit_units: (3584, C051),
            random: 192,
            clock: Clock::Binary,
            xy_octal: true,
            fx: true,
            points: POINTS_IQF,
            point_registers: SD_POINTS_IQF,
        },
        other => bail!("unknown slmp profile {other:?}; known: {}", PROFILES.join(", ")),
    })
}

/// What one device point holds.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Unit {
    Bit,
    Word,
    /// The long devices LTN, LSTN, LCN and LZ.
    DWord,
}

/// A memory area. DX, DY and ZR have none of their own: they are views of X, Y and R.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Store {
    Sm, Sd, X, Y, M, L, F, V, B, D, W, Ts, Tc, Tn, Sts, Stc, Stn, Cs, Cc, Cn, Sb, Sw, S, Z, R, Lts, Ltc, Ltn,
    Lsts, Lstc, Lstn, Lcs, Lcc, Lcn, Lz, Rd,
}

const STORES: usize = Store::Rd as usize + 1;

// Access rules of the long devices [observed: plc-comm-slmp's guards in client_rules.rs]. They are requests
// that library refuses to send, not recorded CPU replies, so the C05B they get here is policy.
/// No 0401 in bit units.
const NO_BIT_READ: u8 = 1;
/// No 0401 in word units.
const NO_WORD_READ: u8 = 2;
/// No 0403 entry at all.
const NO_RANDOM: u8 = 4;
/// No 0403 word entry.
const NO_RANDOM_WORD: u8 = 8;
/// 0401 in word units reads 4 words per device: value low, value high, status (bit 0 coil, bit 1 contact), 0.
const BLOCK4: u8 = 16;
/// LTS, LTC, LSTS, LSTC: only through the LTN/LSTN status word. The guard names bit-unit reads; word-unit
/// reads are refused too, following the spec's device table ("status block or dword entry only").
const LONG_TIMER_BIT: u8 = NO_BIT_READ | NO_WORD_READ | NO_RANDOM;
/// LTN, LSTN: 4-word blocks or a double-word entry.
const LONG_TIMER_VALUE: u8 = BLOCK4 | NO_RANDOM_WORD;
/// LCS, LCC: a direct bit read only.
const LONG_COUNTER_BIT: u8 = NO_WORD_READ | NO_RANDOM;
/// LCN, LZ: a double-word entry only.
const LONG_VALUE: u8 = NO_WORD_READ | NO_RANDOM_WORD;

/// One device code.
#[derive(Debug)]
struct Dev {
    name: &'static str,
    /// The Q/L-format code; the iQ-R format sends the same value in 2 bytes.
    code: u8,
    unit: Unit,
    store: Store,
    /// The family whose point count applies: TS, TC and TN are all "T".
    family: &'static str,
    /// The MELSEC number is hex (except X and Y on iQ-F, which are octal).
    hex: bool,
    rules: u8,
}

const fn dv(name: &'static str, code: u8, unit: Unit, store: Store, family: &'static str, hex: bool, rules: u8) -> Dev {
    Dev { name, code, unit, store, family, hex, rules }
}

/// The 35 codes SFC can send (SlmpDevice.kt:9-217), plus STS/STC/STN and RD. The codes are the manual's and
/// match pymcprotocol. Long-device codes are accepted in the Q/L format wherever the CPU has the family:
/// observed on iQ-F, assumed on iQ-R (spec §9.1).
static DEVICES: [Dev; 39] = {
    use Store::*;
    use Unit::*;
    [
        dv("SM", 0x91, Bit, Sm, "SM", false, 0),
        dv("SD", 0xA9, Word, Sd, "SD", false, 0),
        dv("X", 0x9C, Bit, X, "X", true, 0),
        dv("Y", 0x9D, Bit, Y, "Y", true, 0),
        dv("M", 0x90, Bit, M, "M", false, 0),
        dv("L", 0x92, Bit, L, "L", false, 0),
        dv("F", 0x93, Bit, F, "F", false, 0),
        dv("V", 0x94, Bit, V, "V", false, 0),
        dv("B", 0xA0, Bit, B, "B", true, 0),
        dv("D", 0xA8, Word, D, "D", false, 0),
        dv("W", 0xB4, Word, W, "W", true, 0),
        dv("TS", 0xC1, Bit, Ts, "T", false, 0),
        dv("TC", 0xC0, Bit, Tc, "T", false, 0),
        dv("TN", 0xC2, Word, Tn, "T", false, 0),
        dv("STS", 0xC7, Bit, Sts, "ST", false, 0),
        dv("STC", 0xC6, Bit, Stc, "ST", false, 0),
        dv("STN", 0xC8, Word, Stn, "ST", false, 0),
        dv("CS", 0xC4, Bit, Cs, "C", false, 0),
        dv("CC", 0xC3, Bit, Cc, "C", false, 0),
        dv("CN", 0xC5, Word, Cn, "C", false, 0),
        dv("SB", 0xA1, Bit, Sb, "SB", true, 0),
        dv("SW", 0xB5, Word, Sw, "SW", true, 0),
        dv("S", 0x98, Bit, S, "S", false, 0),
        dv("DX", 0xA2, Bit, X, "DX", true, 0),
        dv("DY", 0xA3, Bit, Y, "DY", true, 0),
        dv("Z", 0xCC, Word, Z, "Z", false, 0),
        dv("R", 0xAF, Word, R, "R", false, 0),
        dv("ZR", 0xB0, Word, R, "ZR", false, 0),
        dv("LTS", 0x51, Bit, Lts, "LT", false, LONG_TIMER_BIT),
        dv("LTC", 0x50, Bit, Ltc, "LT", false, LONG_TIMER_BIT),
        dv("LTN", 0x52, DWord, Ltn, "LT", false, LONG_TIMER_VALUE),
        dv("LSTS", 0x59, Bit, Lsts, "LST", false, LONG_TIMER_BIT),
        dv("LSTC", 0x58, Bit, Lstc, "LST", false, LONG_TIMER_BIT),
        dv("LSTN", 0x5A, DWord, Lstn, "LST", false, LONG_TIMER_VALUE),
        dv("LCS", 0x55, Bit, Lcs, "LC", false, LONG_COUNTER_BIT),
        dv("LCC", 0x54, Bit, Lcc, "LC", false, LONG_COUNTER_BIT),
        dv("LCN", 0x56, DWord, Lcn, "LC", false, LONG_VALUE),
        dv("LZ", 0x62, DWord, Lz, "LZ", false, LONG_VALUE),
        dv("RD", 0x2C, Word, Rd, "RD", false, 0),
    ]
};

fn device(code: u16) -> Option<&'static Dev> {
    DEVICES.iter().find(|d| d.code as u16 == code)
}

/// The device that owns a store's memory: X rather than DX, R rather than ZR.
fn owner(store: Store) -> &'static Dev {
    DEVICES.iter().find(|d| d.store == store).expect("every store has a device")
}

/// The contact and coil of a long timer, which its 4-word block reports in the status word.
fn status_stores(store: Store) -> Option<(Store, Store)> {
    match store {
        Store::Ltn => Some((Store::Ltc, Store::Lts)),
        Store::Lstn => Some((Store::Lstc, Store::Lsts)),
        _ => None,
    }
}

/// A 32-bit value as two words, low word first (MELSEC double words).
fn dw(v: u32) -> [u16; 2] {
    [v as u16, (v >> 16) as u16]
}

/// A 64-bit value as four words, lowest first.
fn qw(v: u64) -> [u16; 4] {
    [v as u16, (v >> 16) as u16, (v >> 32) as u16, (v >> 48) as u16]
}

/// Two bytes to a word with the first in the low byte, as MELSEC strings are stored, NUL-padded to `words`.
fn text(bytes: &[u8], words: usize) -> Vec<u16> {
    let mut b = bytes.to_vec();
    b.resize(words * 2, 0);
    b.chunks(2).map(|p| u16::from_le_bytes([p[0], p[1]])).collect()
}

/// UTF-16LE, one character per word, NUL-padded to `words`.
fn wtext(s: &str, words: usize) -> Vec<u16> {
    let mut w: Vec<u16> = s.encode_utf16().collect();
    w.resize(words, 0);
    w
}

fn bits(pattern: u32, n: usize) -> Vec<bool> {
    (0..n).map(|i| pattern >> i & 1 == 1).collect()
}

fn bcd2(v: u32) -> u16 {
    (((v / 10 % 10) << 4) | (v % 10)) as u16
}

/// How a static tag is laid out from its first device.
#[derive(Debug, Clone)]
enum Init {
    Words(Vec<u16>),
    Bits(Vec<bool>),
    DWords(Vec<u32>),
}

struct StaticTag {
    store: Store,
    no: u32,
    tag: &'static str,
    kind: &'static str,
    /// The SFC DataType that reads the tag (`""` where SFC has none).
    sfc: &'static str,
    value: Value,
    init: Init,
}

fn st(
    store: Store, no: u32, tag: &'static str, kind: &'static str, sfc: &'static str, value: Value, init: Init,
) -> StaticTag {
    StaticTag { store, no, tag, kind, sfc, value, init }
}

/// The static map (spec §4.1, §4.2). Every D address below D1000 that is not listed here reads 0.
fn statics(p: &Profile) -> Vec<StaticTag> {
    use Store::*;
    let words = |w: &[u16]| Init::Words(w.to_vec());
    let concat = |parts: &[&[u16]]| Init::Words(parts.concat());
    let tail = p.points_of("D").unwrap_or(0).saturating_sub(8);
    let int_array = [1i16, -2, 3, -4, 500, -600, 7000, -8000, 32767, -32768].map(|v| v as u16);
    let dint_array = [1i32, -1, 100_000, 305_419_896].map(|v| dw(v as u32));
    let real_array = [0.5f32, -1.25, 100.0, 65504.0, -0.0625].map(|v| dw(v.to_bits()));
    let mix = |id: u16, qty: u16, name: &[u8]| [&[id, qty][..], &text(name, 4)].concat();
    vec![
        st(D, 100, "int", "Word[Signed]", "WORD", json!(-12345), words(&[-12345i16 as u16])),
        st(D, 101, "uint", "Word[Unsigned]", "WORD", json!(54321), words(&[54321])),
        st(D, 102, "byte", "INT holding a BYTE", "WORD", json!(165), words(&[0xA5])),
        st(D, 103, "sint", "INT holding a SINT", "WORD", json!(-100), words(&[-100i16 as u16])),
        st(D, 104, "usint", "INT holding a USINT", "WORD", json!(200), words(&[200])),
        st(D, 106, "dint", "Double Word[Signed]", "DOUBLEWORD", json!(-1_234_567_890),
           words(&dw(-1_234_567_890i32 as u32))),
        st(D, 108, "udint", "Double Word[Unsigned]", "DOUBLEWORD", json!(3_000_000_000u32), words(&dw(3_000_000_000))),
        st(D, 110, "real", "FLOAT[Single]", "DOUBLEWORD", json!(12345.5), words(&dw(12345.5f32.to_bits()))),
        st(D, 112, "lreal", "FLOAT[Double]", "WORD[4]", json!(-98765.4375), words(&qw((-98765.4375f64).to_bits()))),
        st(D, 116, "time", "Time (DINT ms)", "DOUBLEWORD", json!(1234), words(&dw(1234))),
        st(D, 126, "dint_sym", "DINT, both words equal", "DOUBLEWORD", json!(-1_698_915_652), words(&dw(0x9ABC_9ABC))),
        st(D, 128, "udint_sym", "UDINT, both words equal", "DOUBLEWORD", json!(305_402_420), words(&dw(0x1234_1234))),
        st(D, 130, "date", "clock data: year, month, day, hour, minute, second, day of week", "WORD[7]",
           json!([2024, 5, 17, 13, 45, 30, 5]), words(&[2024, 5, 17, 13, 45, 30, 5])),
        st(D, 200, "string", "String(32)", "STRING(16)", json!("SFC-SIM"), Init::Words(text(b"SFC-SIM", 17))),
        st(D, 220, "wstring", "String[Unicode](16)", "", json!("SFC-SIM"), Init::Words(wtext("SFC-SIM", 17))),
        st(D, 240, "int_array", "Word[Signed] [0..9]", "WORD[10]",
           json!([1, -2, 3, -4, 500, -600, 7000, -8000, 32767, -32768]), words(&int_array)),
        st(D, 250, "dint_array", "DINT [0..3]", "DOUBLEWORD[4]", json!([1, -1, 100_000, 305_419_896]),
           Init::Words(dint_array.concat())),
        st(D, 260, "real_array", "REAL [0..4]", "", json!([0.5, -1.25, 100.0, 65504.0, -0.0625]),
           Init::Words(real_array.concat())),
        st(D, 270, "string_sjis", "String(4), Shift-JIS", "STRING(8)", json!("ﾓｰﾀｰ"),
           Init::Words(text(&[0xD3, 0xB0, 0xC0, 0xB0], 3))),
        st(D, 280, "recipe",
           "{id INT, qty INT, name String(8)}; Structures {\"id\":\"WORD\",\"qty\":\"WORD\",\"name\":\"STRING(8)\"}",
           "Recipe", json!({"id": 7, "qty": 250, "name": "PUMP-01"}), concat(&[&[7, 250], &text(b"PUMP-01", 5)])),
        st(D, 300, "recipe_array", "3 x {id INT, qty INT, name String(8)}, 6-word stride", "Recipe[3]",
           json!([{"id": 1, "qty": 100, "name": "MIX-A"}, {"id": 2, "qty": 200, "name": "MIX-B"},
                  {"id": 3, "qty": 300, "name": "MIX-C"}]),
           Init::Words([mix(1, 100, b"MIX-A"), mix(2, 200, b"MIX-B"), mix(3, 300, b"MIX-C")].concat())),
        st(D, 320, "status", "{mode INT, flags Bit[4] in a word}; Structures {\"mode\":\"WORD\",\"flags\":\"BIT[4]\"}",
           "Status", json!({"mode": 2, "flags": [true, false, true, false]}), words(&[2, 0x0005])),
        st(D, 330, "string_array", "String(5) [0..1], word-aligned", "STRING(5)[2]", json!(["ABCDE", "FGHIJ"]),
           concat(&[&text(b"ABCDE", 3), &text(b"FGHIJ", 3)])),
        st(D, tail, "tail", "String(15), the last 8 words of D", "STRING(16)", json!("TAIL-OF-DEVICE!"),
           Init::Words(text(b"TAIL-OF-DEVICE!", 8))),
        st(M, 0, "bits", "BIT[16] = 0x3CA5, M0 (bool_true) on, M1 (bool_false) off", "BIT[16]",
           json!(bits(0x3CA5, 16)), Init::Bits(bits(0x3CA5, 16))),
        st(X, 0, "inputs", "BIT: numbers 0, 2, 3, 16 and 24 on (word X0 = 0x000D)", "BIT",
           json!([0, 2, 3, 16, 24]), Init::Bits((0..25).map(|i| [0, 2, 3, 16, 24].contains(&i)).collect())),
        st(Y, 1, "y1", "BIT", "BIT", json!(true), Init::Bits(vec![true])),
        st(L, 0, "l0", "BIT", "BIT", json!(true), Init::Bits(vec![true])),
        st(B, 0, "b0_b7", "BIT: B0 and B7 on", "BIT", json!([0, 7]), Init::Bits(bits(0x81, 8))),
        st(W, 0, "w", "Word[Unsigned] [0..1]", "WORD[2]", json!([4660, 22136]), words(&[0x1234, 0x5678])),
        st(R, 0, "r", "Word[Signed] [0..1]; ZR0/ZR1 are the same words", "WORD[2]", json!([1000, 2000]),
           words(&[1000, 2000])),
        st(Z, 0, "z", "Word[Signed] [0..1]", "WORD[2]", json!([10, -1]), words(&[10, 0xFFFF])),
        st(Lz, 0, "lz", "Double Word[Signed] [0..1] (iq-r, iq-f)", "DOUBLEWORD", json!([100_000, -2]),
           Init::DWords(vec![100_000, -2i32 as u32])),
    ]
}

/// The dynamic tags, for `--print-map`: (device, number, tag, type, SFC DataType). The signals are the
/// engine's (core::signal); REAL and LREAL tags cannot be decoded by SFC, which has no float type.
const DYNAMIC: &[(Store, u32, &str, &str, &str)] = &[
    (Store::D, 1000, "sine", "REAL", "DOUBLEWORD"),
    (Store::D, 1002, "cosine", "REAL", "DOUBLEWORD"),
    (Store::D, 1004, "tangent", "REAL", "DOUBLEWORD"),
    (Store::D, 1006, "cotangent", "REAL", "DOUBLEWORD"),
    (Store::D, 1008, "exp", "REAL", "DOUBLEWORD"),
    (Store::D, 1010, "quadratic", "REAL", "DOUBLEWORD"),
    (Store::D, 1012, "sawtooth", "REAL", "DOUBLEWORD"),
    (Store::D, 1014, "triangle", "REAL", "DOUBLEWORD"),
    (Store::D, 1016, "square", "REAL", "DOUBLEWORD"),
    (Store::D, 1018, "damped", "REAL", "DOUBLEWORD"),
    (Store::D, 1020, "noise", "REAL", "DOUBLEWORD"),
    (Store::D, 1022, "randomwalk", "REAL", "DOUBLEWORD"),
    (Store::D, 1024, "sine64", "LREAL", "WORD[4]"),
    (Store::D, 1028, "t", "LREAL seconds", "WORD[4]"),
    (Store::D, 1032, "scan", "UDINT scan mod 2^32", "DOUBLEWORD"),
    (Store::D, 1100, "sine_int", "INT round(100·sine), saturated", "WORD"),
    (Store::D, 1101, "cosine_int", "INT ×100", "WORD"),
    (Store::D, 1102, "tangent_int", "INT ×100", "WORD"),
    (Store::D, 1103, "cotangent_int", "INT ×100", "WORD"),
    (Store::D, 1104, "exp_int", "INT ×100", "WORD"),
    (Store::D, 1105, "quadratic_int", "INT ×100", "WORD"),
    (Store::D, 1106, "sawtooth_int", "INT ×100", "WORD"),
    (Store::D, 1107, "triangle_int", "INT ×100", "WORD"),
    (Store::D, 1108, "square_int", "INT ×100", "WORD"),
    (Store::D, 1109, "damped_int", "INT ×100", "WORD"),
    (Store::D, 1110, "noise_int", "INT ×100", "WORD"),
    (Store::D, 1111, "randomwalk_int", "INT ×100", "WORD"),
    (Store::M, 1000, "blink_1hz", "BIT", "BIT"),
    (Store::M, 1001, "blink_5hz", "BIT", "BIT"),
    (Store::Y, 0, "lamp", "BIT = blink_1hz", "BIT"),
];

/// The system devices, timers and counters a profile has, for `--print-map`: (device, number, tag, type,
/// SFC DataType). The device-point registers are listed separately.
fn system(p: &Profile) -> Vec<(Store, u32, &'static str, &'static str, &'static str)> {
    use Store::*;
    let mut out = vec![
        (Sm, 400, "always_on", "ON", "BIT"),
        (Sm, 401, "always_off", "OFF", "BIT"),
        (Sm, 402, "first_scan_on", "ON in scan 0 only", "BIT"),
        (Sm, 403, "first_scan_off", "OFF in scan 0 only", "BIT"),
        (Sm, 410, "clock_100ms", "0.1 s clock", "BIT"),
        (Sm, 411, "clock_200ms", "0.2 s clock", "BIT"),
        (Sm, 412, "clock_1s", "1 s clock (= blink_1hz)", "BIT"),
        (Sm, 413, "clock_2s", "2 s clock", "BIT"),
        (Sd, 203, "cpu_status", "0 = RUN", "WORD"),
        match p.clock {
            Clock::Bcd => (Sd, 210, "clock", "BCD: yy/month, day/hour, minute/second, century/day of week", "WORD[4]"),
            Clock::Binary => (Sd, 210, "clock", "year, month, day, hour, minute, second, day of week", "WORD[7]"),
        },
        (Sd, 412, "second_counter", "floor(t) mod 65536", "WORD"),
        (Sd, 420, "scan_counter", "k mod 65536", "WORD"),
        (Sd, 520, "scan_time", "ms; SD521 µs = 0; SD524/525 minimum and SD526/527 maximum alike", "WORD"),
        (Tc, 0, "t0_coil", "100 ms timer K100: on while t mod 20 s < 15 s", "BIT"),
        (Tn, 0, "t0_value", "min(floor(10·(t mod 20)), 100) while the coil is on, else 0", "WORD"),
        (Ts, 0, "t0_contact", "coil and value = 100", "BIT"),
        (Cc, 0, "c0_coil", "= SM412 (the counted input)", "BIT"),
        (Cn, 0, "c0_value", "floor(t) mod 11", "WORD"),
        (Cs, 0, "c0_contact", "value = 10", "BIT"),
    ];
    if p.fx {
        out.extend([
            (Sm, 8000, "run_on", "ON", "BIT"),
            (Sm, 8001, "run_off", "OFF", "BIT"),
            (Sm, 8002, "initial_pulse_on", "ON in scan 0 only", "BIT"),
            (Sm, 8003, "initial_pulse_off", "OFF in scan 0 only", "BIT"),
            (Sm, 8012, "clock_100ms_fx", "0.1 s clock", "BIT"),
            (Sm, 8013, "clock_1s_fx", "1 s clock", "BIT"),
            (Sm, 8014, "clock_1min_fx", "1 min clock", "BIT"),
            (Sd, 8013, "clock_fx", "second, minute, hour, day, month, year, day of week", "WORD[7]"),
        ]);
    }
    if p.points_of("LT").is_some() {
        out.extend([
            (Ltc, 0, "lt0_coil", "as t0_coil", ""),
            (Ltn, 0, "lt0_value", "µs: min((t mod 20 s)·10^6, 10^7) while the coil is on; unit unverified",
             "DOUBLEWORD"),
            (Lts, 0, "lt0_contact", "coil and t mod 20 s >= 10 s", ""),
        ]);
    }
    if p.points_of("LC").is_some() {
        out.extend([
            (Lcc, 0, "lc0_coil", "= SM412", ""),
            (Lcn, 0, "lc0_value", "floor(t)", "DOUBLEWORD"),
            (Lcs, 0, "lc0_contact", "OFF", ""),
        ]);
    }
    out
}

/// One memory area's contents.
#[derive(Debug, Clone)]
enum Mem {
    Bits(Vec<bool>),
    Words(Vec<u16>),
    DWords(Vec<u32>),
}

/// The device memory of one CPU, one area per store, sized by the profile.
pub struct Image {
    clock: Clock,
    fx: bool,
    mem: Vec<Mem>,
}

impl Image {
    fn new(p: &Profile) -> Image {
        let mut sizes = [0usize; STORES];
        let mut units = [Unit::Word; STORES];
        for d in DEVICES.iter() {
            units[d.store as usize] = d.unit;
            if let Some(n) = p.points_of(d.family) {
                sizes[d.store as usize] = sizes[d.store as usize].max(n as usize);
            }
        }
        let mem = (0..STORES)
            .map(|i| match units[i] {
                Unit::Bit => Mem::Bits(vec![false; sizes[i]]),
                Unit::Word => Mem::Words(vec![0; sizes[i]]),
                Unit::DWord => Mem::DWords(vec![0; sizes[i]]),
            })
            .collect();
        let mut img = Image { clock: p.clock, fx: p.fx, mem };
        for tag in statics(p) {
            img.put(tag.store, tag.no, &tag.init);
        }
        img.set_bit(Store::Sm, 400, true);
        if p.fx {
            img.set_bit(Store::Sm, 8000, true);
        }
        for (sd, family, width) in p.point_registers {
            let n = p.points_of(family).unwrap_or(0);
            if *width == 2 {
                img.set_words(Store::Sd, *sd, &dw(n));
            } else {
                img.set_words(Store::Sd, *sd, &[n as u16]);
            }
        }
        img
    }

    // Reads past an area's end give 0: every request is range-checked before it reads.
    fn bit(&self, s: Store, n: u64) -> bool {
        match &self.mem[s as usize] {
            Mem::Bits(v) => usize::try_from(n).ok().and_then(|i| v.get(i)).copied().unwrap_or(false),
            _ => false,
        }
    }

    fn word(&self, s: Store, n: u64) -> u16 {
        match &self.mem[s as usize] {
            Mem::Words(v) => usize::try_from(n).ok().and_then(|i| v.get(i)).copied().unwrap_or(0),
            _ => 0,
        }
    }

    fn dword(&self, s: Store, n: u64) -> u32 {
        match &self.mem[s as usize] {
            Mem::DWords(v) => usize::try_from(n).ok().and_then(|i| v.get(i)).copied().unwrap_or(0),
            _ => 0,
        }
    }

    /// `count` (16 or 32) bit devices from `n`, device `n` in bit 0.
    fn bits(&self, s: Store, n: u64, count: u32) -> u32 {
        (0..count).fold(0, |acc, i| acc | (self.bit(s, n + i as u64) as u32) << i)
    }

    // Writes into an absent area or past its end are ignored, so one static map serves every profile.
    fn set_bit(&mut self, s: Store, n: u32, b: bool) {
        if let Mem::Bits(v) = &mut self.mem[s as usize] {
            if let Some(slot) = v.get_mut(n as usize) {
                *slot = b;
            }
        }
    }

    fn set_words(&mut self, s: Store, n: u32, words: &[u16]) {
        if let Mem::Words(v) = &mut self.mem[s as usize] {
            for (i, w) in words.iter().enumerate() {
                if let Some(slot) = v.get_mut(n as usize + i) {
                    *slot = *w;
                }
            }
        }
    }

    fn set_dwords(&mut self, s: Store, n: u32, dwords: &[u32]) {
        if let Mem::DWords(v) = &mut self.mem[s as usize] {
            for (i, d) in dwords.iter().enumerate() {
                if let Some(slot) = v.get_mut(n as usize + i) {
                    *slot = *d;
                }
            }
        }
    }

    fn put(&mut self, s: Store, n: u32, init: &Init) {
        match init {
            Init::Words(w) => self.set_words(s, n, w),
            Init::DWords(d) => self.set_dwords(s, n, d),
            Init::Bits(b) => {
                for (i, x) in b.iter().enumerate() {
                    self.set_bit(s, n + i as u32, *x);
                }
            }
        }
    }
}

impl ScanImage for Image {
    fn scan(&mut self, s: &Scan) {
        use Store::*;
        let v = &s.v;
        let k = s.k;
        // The PLC clocks, timers and counters count exact simulated milliseconds, so no float rounding moves
        // an edge.
        let ms = k.wrapping_mul(s.cycle_ms);
        let clock = |period_ms: u64| ms % period_ms < period_ms / 2;

        let reals = [v.sine, v.cosine, v.tangent, v.cotangent, v.exp, v.quadratic, v.sawtooth, v.triangle, v.square,
                     v.damped, v.noise, v.randomwalk];
        for (i, x) in reals.iter().enumerate() {
            self.set_words(D, 1000 + 2 * i as u32, &dw((*x as f32).to_bits()));
        }
        self.set_words(D, 1024, &qw(v.sine.to_bits()));
        self.set_words(D, 1028, &qw(s.t.to_bits()));
        self.set_words(D, 1032, &dw(k as u32));
        // SFC has no float type, so every signal is also an INT ×100.
        let ints: Vec<u16> = reals.iter().map(|x| scaled_i16(*x, 100.0) as u16).collect();
        self.set_words(D, 1100, &ints);
        self.set_bit(M, 1000, v.blink_1hz);
        self.set_bit(M, 1001, v.blink_5hz);
        self.set_bit(Y, 0, v.blink_1hz);

        // Special relays: the first-scan pair and the clocks, each ON for the first half of its period.
        self.set_bit(Sm, 402, k == 0);
        self.set_bit(Sm, 403, k != 0);
        for (no, period) in [(410, 100), (411, 200), (412, 1000), (413, 2000)] {
            self.set_bit(Sm, no, clock(period));
        }
        if self.fx {
            self.set_bit(Sm, 8002, k == 0);
            self.set_bit(Sm, 8003, k != 0);
            for (no, period) in [(8012, 100), (8013, 1000), (8014, 60_000)] {
                self.set_bit(Sm, no, clock(period));
            }
        }

        // Special registers: the clock, the 1 s and scan counters, the scan times (SD521-SD527 µs parts 0).
        let c = civil(s.wall_ms);
        let year = c.year.max(0) as u32;
        let wd = c.weekday as u16;
        match self.clock {
            Clock::Bcd => self.set_words(Sd, 210, &[
                bcd2(year % 100) << 8 | bcd2(c.month), bcd2(c.day) << 8 | bcd2(c.hour),
                bcd2(c.minute) << 8 | bcd2(c.second), bcd2(year / 100) << 8 | wd,
            ]),
            Clock::Binary => self.set_words(Sd, 210, &[
                year as u16, c.month as u16, c.day as u16, c.hour as u16, c.minute as u16, c.second as u16, wd,
            ]),
        }
        if self.fx {
            self.set_words(Sd, 8013, &[
                c.second as u16, c.minute as u16, c.hour as u16, c.day as u16, c.month as u16, year as u16, wd,
            ]);
        }
        self.set_words(Sd, 412, &[(ms / 1000) as u16]);
        self.set_words(Sd, 420, &[k as u16]);
        let scan_ms = s.cycle_ms.min(u16::MAX as u64) as u16;
        self.set_words(Sd, 520, &[scan_ms, 0, 0, 0, scan_ms, 0, scan_ms, 0]);

        // T0: a 100 ms timer, K100, whose coil is on for 15 s of every 20 s.
        let tau = ms % 20_000;
        let coil = tau < 15_000;
        let tn = if coil { (tau / 100).min(100) } else { 0 };
        self.set_bit(Tc, 0, coil);
        self.set_words(Tn, 0, &[tn as u16]);
        self.set_bit(Ts, 0, coil && tn == 100);
        // C0: K10, counting the rising edges of SM412.
        let cn = ms / 1000 % 11;
        self.set_words(Cn, 0, &[cn as u16]);
        self.set_bit(Cc, 0, clock(1000));
        self.set_bit(Cs, 0, cn == 10);
        // LT0 (iQ-R): the T0 cycle in µs; the unit is unverified (spec §4.5). LC0 (iQ-R, iQ-F): seconds.
        self.set_dwords(Ltn, 0, &[if coil { (tau * 1000).min(10_000_000) as u32 } else { 0 }]);
        self.set_bit(Ltc, 0, coil);
        self.set_bit(Lts, 0, coil && tau >= 10_000);
        self.set_dwords(Lcn, 0, &[(ms / 1000) as u32]);
        self.set_bit(Lcc, 0, clock(1000));
    }
}

/// The routing fields of a request, echoed in its reply.
#[derive(Debug, Clone, Copy)]
struct Head {
    /// The 4E serial number; `None` for a 3E frame.
    serial: Option<u16>,
    net: u8,
    pc: u8,
    io: u16,
    sta: u8,
}

impl Head {
    fn reply(&self, end: u16, data: &[u8]) -> Vec<u8> {
        let mut out = Vec::with_capacity(15 + data.len());
        match self.serial {
            None => out.extend_from_slice(&[0xD0, 0x00]),
            Some(serial) => {
                out.extend_from_slice(&[0xD4, 0x00]);
                out.extend_from_slice(&serial.to_le_bytes());
                out.extend_from_slice(&[0x00, 0x00]);
            }
        }
        out.extend_from_slice(&[self.net, self.pc]);
        out.extend_from_slice(&self.io.to_le_bytes());
        out.push(self.sta);
        out.extend_from_slice(&(2 + data.len() as u16).to_le_bytes());
        out.extend_from_slice(&end.to_le_bytes());
        out.extend_from_slice(data);
        out
    }

    /// The error information: routing fields, command and subcommand. Exactly 9 bytes, because SFC's parser
    /// takes fewer than 8 as absent and throws on 8 (SlmpResponseErrorInfo.kt:24,31).
    fn error_info(&self, cmd: u16, sub: u16) -> [u8; 9] {
        let [io_lo, io_hi] = self.io.to_le_bytes();
        let [cmd_lo, cmd_hi] = cmd.to_le_bytes();
        let [sub_lo, sub_hi] = sub.to_le_bytes();
        [self.net, self.pc, io_lo, io_hi, self.sta, cmd_lo, cmd_hi, sub_lo, sub_hi]
    }
}

/// A device field: number (3 bytes) and code (1 byte) in the Q/L format, number (4) and code (2) in the
/// iQ-R format. SFC always sends the Q/L shape (SlmpDeviceRead.kt:18-22, SlmpDevice.kt:235-236).
fn device_field(r: &mut Reader<'_>, iqr: bool) -> Option<(u32, u16)> {
    if iqr {
        Some((r.le_u32()?, r.le_u16()?))
    } else {
        let b = r.bytes(3)?;
        Some((u32::from_le_bytes([b[0], b[1], b[2], 0]), r.u8()? as u16))
    }
}

/// A connection's unparsed input.
#[derive(Debug, Default)]
pub struct Conn {
    pub id: u64,
    /// Frames answered so far.
    pub requests: u64,
    buf: Vec<u8>,
}

impl Conn {
    pub fn new(id: u64) -> Conn {
        Conn { id, requests: 0, buf: Vec::new() }
    }

    /// Bytes of a frame not yet complete.
    pub fn pending(&self) -> usize {
        self.buf.len()
    }
}

/// The outcome of feeding bytes to a connection.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct Output {
    /// Replies, in request order; each one goes out in a single write.
    pub replies: Vec<Vec<u8>>,
    /// The stream cannot be framed any more: close the connection.
    pub close: bool,
}

pub struct Server {
    profile: Profile,
    image: Arc<RwLock<Image>>,
}

impl Server {
    pub fn new(profile_name: &str) -> anyhow::Result<Server> {
        let profile = profile(profile_name)?;
        let image = Arc::new(RwLock::new(Image::new(&profile)));
        Ok(Server { profile, image })
    }

    pub fn profile(&self) -> &str {
        self.profile.name
    }

    pub fn image(&self) -> Arc<dyn ScanTarget> {
        self.image.clone()
    }

    /// Splits `input` (appended to what the connection already holds) into frames and answers each.
    pub fn feed(&self, conn: &mut Conn, input: &[u8], events: &Events) -> Output {
        conn.buf.extend_from_slice(input);
        let mut out = Output::default();
        while conn.buf.len() >= 2 {
            let e4 = match conn.buf[..2] {
                [0x50, 0x00] => false,
                [0x54, 0x00] if self.profile.frame_4e => true,
                _ => {
                    // ASCII code ("5000" is 35 30 30 30), any other subheader, or 4E on a CPU without it. A
                    // binary port does not answer ASCII (it only logs C06F, SlmpError.kt:29), and without a
                    // subheader the framing is lost, so close [policy].
                    let reason = if conn.buf[..2] == [0x54, 0x00] { "4e_off" } else { "subheader" };
                    let detail = json!({"reason": reason, "bytes": hex(&conn.buf[..2])});
                    events.emit(NAME, conn.id, "bad_frame", detail, "closed");
                    out.close = true;
                    conn.buf.clear();
                    break;
                }
            };
            let header = if e4 { 13 } else { 9 };
            if conn.buf.len() < header {
                break;
            }
            let len = u16::from_le_bytes([conn.buf[header - 2], conn.buf[header - 1]]) as usize;
            if len > MAX_LENGTH {
                events.emit(NAME, conn.id, "bad_frame", json!({"reason": "length", "len": len}), "closed");
                out.close = true;
                conn.buf.clear();
                break;
            }
            if conn.buf.len() < header + len {
                break;
            }
            let frame: Vec<u8> = conn.buf.drain(..header + len).collect();
            conn.requests += 1;
            out.replies.push(self.handle(conn.id, &frame, events));
        }
        out
    }

    /// Answers one complete frame: a 3E or 4E header and the declared L bytes.
    pub fn handle(&self, conn: u64, frame: &[u8], events: &Events) -> Vec<u8> {
        let mut r = Reader::new(frame);
        let e4 = r.bytes(2) == Some(&[0x54u8, 0x00][..]);
        let serial = if e4 {
            let serial = r.le_u16().unwrap_or(0);
            let _ = r.skip(2);
            Some(serial)
        } else {
            None
        };
        let head = Head {
            serial,
            net: r.u8().unwrap_or(0),
            pc: r.u8().unwrap_or(0),
            io: r.le_u16().unwrap_or(0),
            sta: r.u8().unwrap_or(0),
        };
        let len = r.le_u16().unwrap_or(0) as usize;
        let rest = r.rest();
        let mut body = Reader::new(&rest[..len.min(rest.len())]);
        // The monitoring timer is ignored: every request is answered at once. The routing fields are echoed and
        // never checked (spec §2.4 step 2 makes that an option, off by default).
        let (timer, cmd, sub) = (body.le_u16(), body.le_u16(), body.le_u16());
        let (op, mut detail, result) = match (timer, cmd, sub) {
            (Some(_), Some(cmd), Some(sub)) => self.execute(cmd, sub, body.rest()),
            // L < 6: the missing command and subcommand bytes are 0 in the error information.
            _ => ("unsupported", json!({}), Err(C061)),
        };
        let (cmd, sub) = (cmd.unwrap_or(0), sub.unwrap_or(0));
        detail["frame"] = json!(if e4 { "4E" } else { "3E" });
        if let Some(serial) = serial {
            detail["serial"] = json!(serial);
        }
        detail["net"] = json!(head.net);
        detail["pc"] = json!(head.pc);
        detail["io"] = json!(head.io);
        detail["sta"] = json!(head.sta);
        detail["len"] = json!(len);
        detail["timer"] = json!(timer.unwrap_or(0));
        detail["cmd"] = json!(format!("{cmd:04X}"));
        detail["sub"] = json!(format!("{sub:04X}"));
        match result {
            Ok(data) => {
                events.emit(NAME, conn, op, detail, "ok");
                head.reply(0x0000, &data)
            }
            Err(code) => {
                events.emit(NAME, conn, op, detail, &format!("{code:04X}"));
                head.reply(code, &head.error_info(cmd, sub))
            }
        }
    }

    /// The check order of spec §2.4: command (C059), subcommand (C059), length (C061), counts (C051, C052,
    /// C054), each device (C05B, C05C), then every range (C056). A failing request returns no data.
    fn execute(&self, cmd: u16, sub: u16, data: &[u8]) -> (&'static str, Value, Result<Vec<u8>, u16>) {
        let mut detail = json!({});
        let (op, result) = match cmd {
            0x0401 => ("read_batch", self.batch_read(sub, data, &mut detail)),
            0x0403 => ("read_random", self.random_read(sub, data, &mut detail)),
            0x0101 => ("read_type_name", self.type_name(sub, data, &mut detail)),
            0x0619 => ("loopback", self.loopback(sub, data, &mut detail)),
            // Writes (1401, 1402), blocks (0406, 1406), monitoring (0801, 0802), remote operations (1001-1006),
            // passwords (1630, 1631), files and buffer memory are not simulated: a CPU without them answers.
            _ => ("unsupported", Err(C059)),
        };
        (op, detail, result)
    }

    /// The device of `code`, if this CPU has its family.
    fn available(&self, code: u16) -> Option<&'static Dev> {
        device(code).filter(|d| self.profile.points_of(d.family).is_some())
    }

    /// `span` points from `no` fit the device; a device with 0 points fits nothing. C056 is the observed code;
    /// a CPU may answer 4031 instead (spec §2.8).
    fn in_range(&self, dev: &Dev, no: u32, span: u64) -> Result<(), u16> {
        let size = self.profile.points_of(dev.family).unwrap_or(0) as u64;
        if no as u64 + span > size {
            Err(C056)
        } else {
            Ok(())
        }
    }

    /// A device in MELSEC notation: hex numbers with a leading 0 before a letter (X0A), octal X and Y on
    /// iQ-F (X12), decimal otherwise. SFC's AccessPoint is always decimal (SlmpAccessPoint.kt:23,29).
    fn notation(&self, dev: &Dev, no: u32) -> String {
        if self.profile.xy_octal && matches!(dev.store, Store::X | Store::Y) {
            format!("{}{no:o}", dev.name)
        } else if dev.hex {
            let digits = format!("{no:X}");
            let zero = if digits.starts_with(|c: char| c.is_ascii_alphabetic()) { "0" } else { "" };
            format!("{}{zero}{digits}", dev.name)
        } else {
            format!("{}{no}", dev.name)
        }
    }

    fn label(&self, code: u16, no: u32) -> String {
        match device(code) {
            Some(dev) => self.notation(dev, no),
            None => format!("{code:#04x}:{no}"),
        }
    }

    /// 0401 Device Read, in the Q/L format (0000 word units, 0001 bit units) or the iQ-R format (0002, 0003).
    fn batch_read(&self, sub: u16, data: &[u8], detail: &mut Value) -> Result<Vec<u8>, u16> {
        let (iqr, bit_units) = match sub {
            0x0000 | 0x0001 => (false, sub == 0x0001),
            0x0002 | 0x0003 if self.profile.iqr_format.is_some() => (true, sub == 0x0003),
            _ => return Err(C059),
        };
        // Number, code and points: L = 12 in the Q/L format, 14 in the iQ-R format. SFC sends 0002 for long
        // devices with the Q/L field (SlmpDevice.kt:252), so L = 12: C061 here. Hardware might answer C058
        // instead [unverified, spec §9.2].
        let want = if iqr { 8 } else { 6 };
        if data.len() != want {
            return Err(C061);
        }
        let mut r = Reader::new(data);
        let (no, code) = device_field(&mut r, iqr).ok_or(C061)?;
        let points = r.le_u16().ok_or(C061)?;
        detail["dev"] = json!(self.label(code, no));
        detail["points"] = json!(points);
        let (max, over) = if bit_units { self.profile.bit_units } else { self.profile.word_units };
        if points == 0 || points > max {
            return Err(over);
        }
        let dev = self.available(code).ok_or(C05B)?;
        let forbidden = if bit_units { NO_BIT_READ } else { NO_WORD_READ };
        if dev.rules & forbidden != 0 {
            return Err(C05B);
        }
        let points = points as u64;
        let span = match (bit_units, dev.unit) {
            (true, Unit::Bit) => points,
            (true, _) => return Err(C05C),
            (false, Unit::Bit) => 16 * points,
            (false, Unit::Word) => points,
            // A long timer is 4 words; another count gets C05C [policy code].
            (false, Unit::DWord) if dev.rules & BLOCK4 != 0 => {
                if !points.is_multiple_of(4) {
                    return Err(C05C);
                }
                points / 4
            }
            (false, Unit::DWord) => return Err(C05B),
        };
        self.in_range(dev, no, span)?;

        let img = self.image.read().unwrap_or_else(|e| e.into_inner());
        let (s, no) = (dev.store, no as u64);
        let mut out = Vec::new();
        match (bit_units, dev.unit) {
            // One nibble per point, the even point in the high nibble.
            (true, _) => {
                for j in (0..points).step_by(2) {
                    let even = img.bit(s, no + j);
                    let odd = j + 1 < points && img.bit(s, no + j + 1);
                    out.push((even as u8) << 4 | odd as u8);
                }
            }
            // 16 bit devices per word, the first in bit 0. SFC never sends this: its bit-device batch reads are
            // always in bit units (SlmpDevice.kt:254-260).
            (false, Unit::Bit) => {
                for i in 0..points {
                    out.extend_from_slice(&(img.bits(s, no + 16 * i, 16) as u16).to_le_bytes());
                }
            }
            (false, Unit::Word) => {
                for i in 0..points {
                    out.extend_from_slice(&img.word(s, no + i).to_le_bytes());
                }
            }
            (false, Unit::DWord) => {
                for i in 0..points / 4 {
                    let n = no + i;
                    let value = img.dword(s, n);
                    let status = status_stores(s)
                        .map(|(coil, contact)| img.bit(coil, n) as u16 | (img.bit(contact, n) as u16) << 1)
                        .unwrap_or(0);
                    for w in [value as u16, (value >> 16) as u16, status, 0] {
                        out.extend_from_slice(&w.to_le_bytes());
                    }
                }
            }
        }
        Ok(out)
    }

    /// 0403 Device Read Random: the word entries, then the double-word entries, each in request order.
    fn random_read(&self, sub: u16, data: &[u8], detail: &mut Value) -> Result<Vec<u8>, u16> {
        let (iqr, max) = match (sub, self.profile.iqr_format) {
            (0x0000, _) => (false, self.profile.random),
            (0x0002, Some(max)) => (true, max),
            _ => return Err(C059),
        };
        let mut r = Reader::new(data);
        let (Some(nw), Some(nd)) = (r.u8(), r.u8()) else {
            return Err(C061);
        };
        let (nw, nd) = (nw as usize, nd as usize);
        detail["word_points"] = json!(nw);
        detail["dword_points"] = json!(nd);
        let entry = if iqr { 6 } else { 4 };
        if r.remaining() != entry * (nw + nd) {
            return Err(C061);
        }
        if nw + nd == 0 || nw + nd > max {
            return Err(C054);
        }
        let mut items = Vec::with_capacity(nw + nd);
        while let Some(item) = device_field(&mut r, iqr) {
            items.push(item);
        }
        let labels: Vec<String> = items.iter().map(|(no, code)| self.label(*code, *no)).collect();
        let (words, dwords) = labels.split_at(nw.min(labels.len()));
        detail["words"] = json!(words);
        detail["dwords"] = json!(dwords);

        let mut devs = Vec::with_capacity(items.len());
        for (i, (no, code)) in items.iter().enumerate() {
            let word = i < nw;
            let dev = self.available(*code).ok_or(C05B)?;
            if dev.rules & NO_RANDOM != 0 || (word && dev.rules & NO_RANDOM_WORD != 0) {
                return Err(C05B);
            }
            devs.push((dev, *no, word));
        }
        for (dev, no, word) in &devs {
            let span = match (word, dev.unit) {
                (true, Unit::Bit) => 16,
                (false, Unit::Bit) => 32,
                (false, Unit::Word) => 2,
                _ => 1,
            };
            self.in_range(dev, *no, span)?;
        }

        let img = self.image.read().unwrap_or_else(|e| e.into_inner());
        let mut out = Vec::with_capacity(2 * nw + 4 * nd);
        for (dev, no, word) in &devs {
            let (s, n) = (dev.store, *no as u64);
            // A double word of words is low word first [observed: plc-comm-slmp client.rs; pymcprotocol].
            let value = match dev.unit {
                Unit::Bit => img.bits(s, n, if *word { 16 } else { 32 }),
                Unit::Word if *word => img.word(s, n) as u32,
                Unit::Word => img.word(s, n) as u32 | (img.word(s, n + 1) as u32) << 16,
                Unit::DWord => img.dword(s, n),
            };
            if *word {
                out.extend_from_slice(&(value as u16).to_le_bytes());
            } else {
                out.extend_from_slice(&value.to_le_bytes());
            }
        }
        Ok(out)
    }

    /// 0101 Read Type Name: the model name, space-padded to 16 bytes, then the model code.
    fn type_name(&self, sub: u16, data: &[u8], detail: &mut Value) -> Result<Vec<u8>, u16> {
        let (model, code) = self.profile.type_name.ok_or(C059)?;
        if sub != 0x0000 {
            return Err(C059);
        }
        if !data.is_empty() {
            return Err(C061);
        }
        detail["model"] = json!(model);
        let mut out = format!("{model:<16}").into_bytes();
        out.truncate(16);
        out.extend_from_slice(&code.to_le_bytes());
        Ok(out)
    }

    /// 0619 Loopback Test: the count and the bytes come back unchanged. Real CPUs may accept only 0-9 and
    /// A-F; every byte is echoed here (spec §9.4).
    fn loopback(&self, sub: u16, data: &[u8], detail: &mut Value) -> Result<Vec<u8>, u16> {
        if sub != 0x0000 {
            return Err(C059);
        }
        let count = Reader::new(data).le_u16().ok_or(C061)? as usize;
        detail["count"] = json!(count);
        // A count outside 1-960 gets the length error too [policy code].
        if !(1..=960).contains(&count) || data.len() != 2 + count {
            return Err(C061);
        }
        Ok(data.to_vec())
    }

    pub fn print_map(&self) -> Value {
        let p = &self.profile;
        let row = |store: Store, no: u32, tag: &str, kind: &str, sfc: &str, value: Value| {
            let dev = owner(store);
            let mut r = json!({"dev": self.notation(dev, no), "tag": tag, "type": kind, "value": value});
            if !sfc.is_empty() {
                r["sfc"] = json!({"AccessPoint": format!("{}{no}", dev.name), "DataType": sfc});
            }
            r
        };
        let mut rows = Vec::new();
        for t in statics(p) {
            rows.push(row(t.store, t.no, t.tag, t.kind, t.sfc, t.value));
        }
        for (store, no, tag, kind, sfc) in DYNAMIC {
            rows.push(row(*store, *no, tag, kind, sfc, json!("dynamic")));
        }
        for (store, no, tag, kind, sfc) in system(p) {
            rows.push(row(store, no, tag, kind, sfc, json!("system")));
        }
        let registers: Vec<Value> = p
            .point_registers
            .iter()
            .map(|(sd, family, width)| {
                json!({"dev": format!("SD{sd}"), "family": family, "words": width,
                       "value": p.points_of(family).unwrap_or(0)})
            })
            .collect();
        let points: serde_json::Map<String, Value> = p.points.iter().map(|(f, n)| (f.to_string(), json!(n))).collect();
        json!({
            "protocol": NAME, "profile": p.name, "device": p.title,
            "type_name": p.type_name.map(|(model, code)| json!({"model": model, "code": format!("{code:04X}")})),
            "frames": if p.frame_4e { vec!["3E", "4E"] } else { vec!["3E"] },
            "device_formats": if p.iqr_format.is_some() { vec!["Q/L", "iQ-R"] } else { vec!["Q/L"] },
            "limits": {
                "batch_word_points": p.word_units.0, "batch_word_error": format!("{:04X}", p.word_units.1),
                "batch_bit_points": p.bit_units.0, "batch_bit_error": format!("{:04X}", p.bit_units.1),
                "random_entries": p.random, "random_entries_iqr_format": p.iqr_format,
            },
            "clock": format!("{:?}", p.clock), "xy_notation": if p.xy_octal { "octal" } else { "hex" },
            "points": points, "point_registers": registers, "tags": rows,
        })
    }

    pub async fn serve(self: Arc<Self>, listener: TcpListener, events: Events) -> anyhow::Result<()> {
        loop {
            let (stream, peer) = super::accept(&listener, NAME).await;
            let server = self.clone();
            let events = events.clone();
            tokio::spawn(async move {
                let mut conn = Conn::new(events.next_conn());
                events.emit(NAME, conn.id, "connect", json!({"peer": peer.to_string()}), "ok");
                let reason = server.connection(stream, &mut conn, &events).await;
                let mut detail = json!({"reason": reason, "requests": conn.requests});
                if conn.pending() > 0 {
                    // EOF inside a frame: the bytes are dropped unanswered.
                    detail["partial"] = json!(conn.pending());
                }
                events.emit(NAME, conn.id, "disconnect", detail, "ok");
            });
        }
    }

    /// Serves one client until it closes or the framing is lost. An idle connection is never closed and
    /// nothing is sent unasked: SLMP has no handshake.
    async fn connection(&self, mut stream: TcpStream, conn: &mut Conn, events: &Events) -> &'static str {
        let _ = stream.set_nodelay(true);
        let mut buf = vec![0u8; 4096];
        loop {
            let n = match stream.read(&mut buf).await {
                Ok(0) => return "eof",
                Ok(n) => n,
                Err(_) => return "read_error",
            };
            let out = self.feed(conn, &buf[..n], events);
            for reply in &out.replies {
                if stream.write_all(reply).await.is_err() {
                    return "write_error";
                }
            }
            if out.close {
                return "bad_frame";
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn melsec_notation_follows_the_profile() {
        let (x, w, d) = (device(0x9C).unwrap(), device(0xB4).unwrap(), device(0xA8).unwrap());
        let iqr = Server::new("iq-r").unwrap();
        let got = (iqr.notation(x, 10), iqr.notation(x, 16), iqr.notation(x, 31));
        assert_eq!(got, ("X0A".into(), "X10".into(), "X1F".into()));
        assert_eq!((iqr.notation(w, 160), iqr.notation(d, 160)), ("W0A0".into(), "D160".into()));
        let iqf = Server::new("iq-f").unwrap();
        let got = (iqf.notation(x, 10), iqf.notation(x, 16), iqf.notation(w, 10));
        assert_eq!(got, ("X12".into(), "X20".into(), "W0A".into()));
        assert_eq!(iqr.label(0x01, 7), "0x01:7");
    }

    #[test]
    fn every_store_has_one_unit_and_an_owner() {
        for d in DEVICES.iter() {
            assert_eq!(owner(d.store).unit, d.unit, "{}", d.name);
        }
        assert_eq!(DEVICES.iter().map(|d| d.code).collect::<std::collections::BTreeSet<_>>().len(), DEVICES.len());
    }

    #[test]
    fn every_profile_builds_and_maps() {
        for name in PROFILES {
            let s = Server::new(name).unwrap();
            assert_eq!(s.profile(), *name);
            assert!(s.print_map()["tags"].as_array().is_some_and(|t| t.len() > 40));
        }
        assert!(Server::new("fx3u").is_err());
    }
}
