// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! Siemens S7 server: S7comm over ISO-on-TCP (RFC 1006 TPKT, ISO 8073 COTP class 0).
//!
//! What SFC's s7 adapter (Apache PLC4X 0.9.1) needs: COTP CR → CC, Setup Communication, the SZL 0x0011
//! identification read and Read Var with S7ANY items. With `ControllerType` unset PLC4X reads SZL 0x0011
//! and completes `connect()` only on a record with index 0x0001. It has no handshake timer, so every
//! handshake frame gets a reply PLC4X can parse, or the connection is closed. On top of that, as a real
//! CPU would: the profile's TSAP rule, PDU and AmQ limits and area sizes, the firmware record and SZL
//! 0x001C component identification, and error replies for writes (not simulated) and every other function.
//!
//! Address map (SFC `Address` strings): see `--print-map s7` and ci/omni-plc-sim/README.md.

use std::collections::BTreeMap;
use std::sync::{Arc, RwLock};

use anyhow::bail;
use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

use crate::core::clock::days_from_civil;
use crate::core::codec::{hex, Reader};
use crate::core::engine::{Image as ScanImage, Scan, ScanTarget};
use crate::core::events::Events;
use crate::core::signal::scaled_i16;

pub const NAME: &str = "s7";
pub const DEFAULT_PROFILE: &str = "s7-1500";
pub const PROFILES: &[&str] = &["s7-300", "s7-400", "s7-1200", "s7-1500"];

/// COTP TPDU size code 0x0A, 1024 bytes: the largest the CC confirms (assumed for every profile).
const TPDU_MAX: u8 = 0x0A;
const DB1_BYTES: usize = 256;
const DB100_BYTES: usize = 128;

// Transport sizes of a request item (S7ANY).
const TS_BIT: u8 = 0x01;
const TS_BYTE: u8 = 0x02;
const TS_CHAR: u8 = 0x03;
const TS_WORD: u8 = 0x04;
const TS_INT: u8 = 0x05;
const TS_DWORD: u8 = 0x06;
const TS_DINT: u8 = 0x07;
const TS_REAL: u8 = 0x08;
const TS_DATE: u8 = 0x09;
const TS_TOD: u8 = 0x0A;
const TS_TIME: u8 = 0x0B;
const TS_S5TIME: u8 = 0x0C;
const TS_DATE_AND_TIME: u8 = 0x0F;
const TS_COUNTER: u8 = 0x1C;
const TS_TIMER: u8 = 0x1D;

// Transport sizes of a reply item. PLC4X reads ceil(length / 8) bytes for 03, 04 and 05 and `length` bytes
// for every other code, 06 included (S7VarPayloadDataItemIO), so DWORD and DINT replies use 04 and 05, as
// snap7 sends them.
const DATA_BIT: u8 = 0x03;
const DATA_BYTE: u8 = 0x04;
const DATA_INT: u8 = 0x05;
const DATA_REAL: u8 = 0x07;
const DATA_OCTETS: u8 = 0x09;

// Item return codes, as PLC4X's DataTransportErrorCode names them.
const RC_OK: u8 = 0xFF;
const RC_INVALID_ADDRESS: u8 = 0x05;
const RC_TYPE_NOT_SUPPORTED: u8 = 0x06;
const RC_NOT_FOUND: u8 = 0x0A;

/// Header error class and code: the function is not available, the answer of a CPU whose PUT/GET access
/// is off. PLC4X turns it into ACCESS_DENIED for every field.
const NOT_AVAILABLE: (u8, u8) = (0x81, 0x04);
/// Header error for a request or reply larger than the negotiated PDU. The code is unverified; the spec
/// assumes 0x85/0x00, and PLC4X's optimizer never produces such a request.
const PDU_TOO_LARGE: (u8, u8) = (0x85, 0x00);
/// UserData error: function not available, for every group and subfunction but the SZL read.
const UD_NOT_AVAILABLE: u16 = 0x8104;
/// UserData error for an SZL-ID this CPU does not have (code assumed by the spec).
const UD_NO_SZL: u16 = 0xD401;

#[derive(Debug, Clone)]
pub struct Profile {
    pub name: &'static str,
    pub title: &'static str,
    /// The order number of SZL 0x0011 records 0x0001 and 0x0006, 20 characters, space-padded. PLC4X takes
    /// its controller type from the character after the first space: 3, 4, 2 or 5 for S7-300, S7-400,
    /// S7-1200 and S7-1500.
    pub mlfb: &'static str,
    /// SZL 0x0011 record 0x0007, V<major>.<minor>.<patch>; illustrative.
    pub firmware: (u8, u8, u8),
    /// SZL 0x001C: station (AS) name, module name, serial number and module type name; illustrative.
    pub station: &'static str,
    pub module_name: &'static str,
    pub serial: &'static str,
    pub module_type: &'static str,
    pub pdu_max: u16,
    /// AmQ calling and called. PLC4X keeps as many requests in flight as AmQ called allows.
    pub amq_max: (u16, u16),
    /// The (rack, slot) pairs a called TSAP may name, Siemens-encoded as rack·32 + slot.
    pub slots: &'static [(u8, u8)],
    pub i_bytes: usize,
    pub q_bytes: usize,
    pub m_bytes: usize,
    pub timers: usize,
    pub counters: usize,
    /// Transport size 0x0F (DATE_AND_TIME). The S7-1200 has no such type and answers 0x06.
    pub date_and_time: bool,
}

pub fn profile(name: &str) -> anyhow::Result<Profile> {
    Ok(match name {
        "s7-300" => Profile {
            name: "s7-300",
            title: "SIMATIC S7-300 CPU 315-2 PN/DP (6ES7 315-2EH14-0AB0)",
            mlfb: "6ES7 315-2EH14-0AB0 ",
            firmware: (3, 2, 17),
            station: "SIMATIC 300(1)",
            module_name: "CPU 315-2 PN/DP",
            serial: "S C-SIM000000315",
            module_type: "CPU 315-2 PN/DP",
            pdu_max: 240,
            amq_max: (1, 1),
            slots: &[(0, 2)],
            i_bytes: 2048,
            q_bytes: 2048,
            m_bytes: 2048,
            timers: 256,
            counters: 256,
            date_and_time: true,
        },
        // AmQ 8/8 is assumed: the spec could not verify the S7-400 limit.
        "s7-400" => Profile {
            name: "s7-400",
            title: "SIMATIC S7-400 CPU 416-3 (6ES7 416-3XR05-0AB0)",
            mlfb: "6ES7 416-3XR05-0AB0 ",
            firmware: (5, 3, 2),
            station: "SIMATIC 400(1)",
            module_name: "CPU 416-3",
            serial: "S C-SIM000000416",
            module_type: "CPU 416-3",
            pdu_max: 480,
            amq_max: (8, 8),
            slots: &[(0, 2), (0, 3)],
            i_bytes: 16384,
            q_bytes: 16384,
            m_bytes: 16384,
            timers: 2048,
            counters: 2048,
            date_and_time: true,
        },
        "s7-1200" => Profile {
            name: "s7-1200",
            title: "SIMATIC S7-1200 CPU 1214C DC/DC/DC (6ES7 214-1AG40-0XB0)",
            mlfb: "6ES7 214-1AG40-0XB0 ",
            firmware: (4, 5, 2),
            station: "S7-1200 station_1",
            module_name: "PLC_1",
            serial: "S C-SIM000001214",
            module_type: "CPU 1214C DC/DC/DC",
            pdu_max: 240,
            amq_max: (3, 3),
            slots: &[(0, 0), (0, 1)],
            i_bytes: 1024,
            q_bytes: 1024,
            m_bytes: 8192,
            timers: 0,
            counters: 0,
            date_and_time: false,
        },
        // AmQ 3/3 is assumed: the spec could not verify the S7-1500 limit.
        "s7-1500" => Profile {
            name: "s7-1500",
            title: "SIMATIC S7-1500 CPU 1516-3 PN/DP (6ES7 516-3AN01-0AB0)",
            mlfb: "6ES7 516-3AN01-0AB0 ",
            firmware: (2, 8, 3),
            station: "S7-1500 station_1",
            module_name: "PLC_1",
            serial: "S V-SIM000001516",
            module_type: "CPU 1516-3 PN/DP",
            pdu_max: 960,
            amq_max: (3, 3),
            slots: &[(0, 0), (0, 1)],
            i_bytes: 32768,
            q_bytes: 32768,
            m_bytes: 16384,
            timers: 2048,
            counters: 2048,
            date_and_time: true,
        },
        other => bail!("unknown s7 profile {other:?}; known: {}", PROFILES.join(", ")),
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Area {
    Db(u16),
    Inputs,
    Outputs,
    Markers,
    Counters,
    Timers,
}

impl Area {
    /// The area of an S7ANY item; the DB number counts only for 0x84. P (0x80) and the rest are not
    /// readable here.
    fn from_wire(code: u8, db: u16) -> Option<Area> {
        Some(match code {
            0x84 => Area::Db(db),
            0x81 => Area::Inputs,
            0x82 => Area::Outputs,
            0x83 => Area::Markers,
            0x1C => Area::Counters,
            0x1D => Area::Timers,
            _ => return None,
        })
    }

    fn label(self) -> String {
        match self {
            Area::Db(n) => format!("DB{n}"),
            Area::Inputs => "I".into(),
            Area::Outputs => "Q".into(),
            Area::Markers => "M".into(),
            Area::Counters => "C".into(),
            Area::Timers => "T".into(),
        }
    }
}

/// An area code in the events log.
fn area_name(code: u8) -> String {
    match code {
        0x84 => "DB".into(),
        0x81 => "I".into(),
        0x82 => "Q".into(),
        0x83 => "M".into(),
        0x1C => "C".into(),
        0x1D => "T".into(),
        other => format!("0x{other:02X}"),
    }
}

/// How a static tag is laid out.
#[derive(Debug, Clone)]
enum Enc {
    /// One bit, set or cleared without touching the rest of the byte.
    Bit(u8, bool),
    /// Big-endian bytes, as the CPU stores them.
    Bytes(Vec<u8>),
}

struct StaticTag {
    tag: &'static str,
    area: Area,
    byte: usize,
    kind: &'static str,
    /// The SFC channel `Address` that reads the tag.
    address: &'static str,
    value: &'static str,
    enc: Enc,
}

fn st(tag: &'static str, area: Area, byte: usize, kind: &'static str, address: &'static str, value: &'static str,
      bytes: &[u8]) -> StaticTag {
    StaticTag { tag, area, byte, kind, address, value, enc: Enc::Bytes(bytes.to_vec()) }
}

fn flag(tag: &'static str, area: Area, byte: usize, bit: u8, v: bool, address: &'static str) -> StaticTag {
    let value = if v { "TRUE" } else { "FALSE" };
    StaticTag { tag, area, byte, kind: "BOOL", address, value, enc: Enc::Bit(bit, v) }
}

/// Two BCD digits.
fn bcd(v: u32) -> u8 {
    (((v / 10 % 10) << 4) | (v % 10)) as u8
}

/// S7 STRING: maximum length, actual length, then the characters, zero-padded to the maximum.
fn s7_string(max: usize, text: &[u8]) -> Vec<u8> {
    let mut out = vec![max as u8, text.len() as u8];
    out.extend_from_slice(text);
    out.resize(2 + max, 0);
    out
}

/// S7 WSTRING: maximum and actual length as words, then UTF-16BE, zero-padded to the maximum.
fn s7_wstring(max: usize, text: &str) -> Vec<u8> {
    let units: Vec<u16> = text.encode_utf16().collect();
    let mut out = Vec::with_capacity(4 + 2 * max);
    out.extend_from_slice(&(max as u16).to_be_bytes());
    out.extend_from_slice(&(units.len() as u16).to_be_bytes());
    for u in units {
        out.extend_from_slice(&u.to_be_bytes());
    }
    out.resize(4 + 2 * max, 0);
    out
}

/// One exact value per type in DB1, plus static M, I and Q bytes. Every value is exactly representable,
/// so a case can compare it for equality.
fn statics() -> Vec<StaticTag> {
    use Area::*;
    let db = Db(1);
    let ints: Vec<u8> = [1i16, -2, 300, -32768].iter().flat_map(|v| v.to_be_bytes()).collect();
    let reals: Vec<u8> = [0.5f32, -1.25, 1024.0, -0.0078125].iter().flat_map(|v| v.to_be_bytes()).collect();
    // DATE counts days since 1990-01-01; TIME_OF_DAY milliseconds since midnight.
    let date = (days_from_civil(2024, 2, 29) - days_from_civil(1990, 1, 1)) as u16;
    let tod: u32 = (8 * 3600 + 30 * 60 + 15) * 1000 + 250;
    // DATE_AND_TIME is BCD: year, month, day, hour, minute, second, two millisecond digits, then the third
    // digit and the weekday (1 = Sunday; 2024-02-29 is a Thursday).
    let dt = [bcd(24), bcd(2), bcd(29), bcd(13), bcd(45), bcd(30), bcd(12), (bcd(3) << 4) | 5];
    // DTL: year, month, day, weekday, hour, minute, second, nanoseconds.
    let dtl = [&2024u16.to_be_bytes()[..], &[2u8, 29, 5, 13, 45, 30][..], &123_456_789u32.to_be_bytes()[..]].concat();
    vec![
        flag("bool_true", db, 0, 0, true, "%DB1.DBX0.0:BOOL"),
        flag("bool_false", db, 0, 1, false, "%DB1.DBX0.1:BOOL"),
        st("byte", db, 1, "BYTE", "%DB1.DBB1:BYTE", "16#A5", &[0xA5]),
        st("sint", db, 2, "SINT", "%DB1.DBB2:SINT", "-100", &(-100i8).to_be_bytes()),
        st("usint", db, 3, "USINT", "%DB1.DBB3:USINT", "200", &[200]),
        st("int", db, 4, "INT", "%DB1.DBW4:INT", "-12345", &(-12345i16).to_be_bytes()),
        st("uint", db, 6, "UINT", "%DB1.DBW6:UINT", "54321", &54321u16.to_be_bytes()),
        st("word", db, 8, "WORD", "%DB1.DBW8:WORD", "16#D431", &0xD431u16.to_be_bytes()),
        st("dint", db, 10, "DINT", "%DB1.DBD10:DINT", "-1234567890", &(-1_234_567_890i32).to_be_bytes()),
        st("udint", db, 14, "UDINT", "%DB1.DBD14:UDINT", "3000000000", &3_000_000_000u32.to_be_bytes()),
        st("dword", db, 18, "DWORD", "%DB1.DBD18:DWORD", "16#B2D05E00", &0xB2D0_5E00u32.to_be_bytes()),
        st("real", db, 22, "REAL", "%DB1.DBD22:REAL", "12345.5", &12345.5f32.to_be_bytes()),
        st("lreal", db, 26, "LREAL", "%DB1:26:LREAL", "-98765.4375", &(-98765.4375f64).to_be_bytes()),
        st("lint", db, 34, "LINT", "%DB1:34:LINT", "-1234567890123", &(-1_234_567_890_123i64).to_be_bytes()),
        st("ulint", db, 42, "ULINT", "%DB1:42:ULINT", "12345678901234", &12_345_678_901_234u64.to_be_bytes()),
        st("time", db, 50, "TIME", "%DB1:50:TIME", "T#1S234MS", &1234i32.to_be_bytes()),
        st("date", db, 54, "DATE", "%DB1:54:DATE", "D#2024-02-29", &date.to_be_bytes()),
        st("tod", db, 56, "TIME_OF_DAY", "%DB1:56:TIME_OF_DAY", "TOD#08:30:15.250", &tod.to_be_bytes()),
        st("dt", db, 60, "DATE_AND_TIME", "%DB1:60:DATE_AND_TIME", "DT#2024-02-29-13:45:30.123", &dt),
        st("dtl", db, 68, "DTL", "%DB1:68:SINT[12]", "DTL#2024-02-29-13:45:30.123456789", &dtl),
        st("char", db, 80, "CHAR", "%DB1.DBB80:CHAR", "'S'", b"S"),
        st("char_latin1", db, 81, "CHAR", "%DB1.DBB81:CHAR", "'Ä' (Latin-1 16#C4)", &[0xC4]),
        st("wchar", db, 82, "WCHAR", "%DB1:82:WCHAR", "WCHAR#'W'", &0x0057u16.to_be_bytes()),
        st("string", db, 84, "STRING[16]", "%DB1:84:STRING(16)", "'SFC-SIM'", &s7_string(16, b"SFC-SIM")),
        st("wstring", db, 102, "WSTRING[16]", "%DB1:102:WSTRING(16)", "WSTRING#'SFC-SIM'", &s7_wstring(16, "SFC-SIM")),
        st("int_array", db, 138, "ARRAY[0..3] OF INT", "%DB1.DBW138:INT[4]", "[1, -2, 300, -32768]", &ints),
        st("real_array", db, 146, "ARRAY[0..3] OF REAL", "%DB1.DBD146:REAL[4]", "[0.5, -1.25, 1024.0, -0.0078125]",
           &reals),
        st("ltime", db, 162, "LTIME", "%DB1:162:LTIME", "LT#1S500MS", &1_500_000_000i64.to_be_bytes()),
        st("lword", db, 170, "LWORD", "%DB1:170:LWORD", "16#0123456789ABCDEF", &0x0123_4567_89AB_CDEFu64.to_be_bytes()),
        // Edge values that expose adapter defects (spec section 8): D5, D6 and D9; lreal (D1) and char_latin1
        // (D9) above do as well. The pilot leaves all of them out.
        st("ulint_max", db, 180, "ULINT", "%DB1:180:ULINT", "18446744073709551615", &u64::MAX.to_be_bytes()),
        st("time_neg", db, 188, "TIME", "%DB1:188:TIME", "T#-1S234MS", &(-1234i32).to_be_bytes()),
        st("string_latin1", db, 192, "STRING[16]", "%DB1:192:STRING(16)", "'Grüße' (Latin-1)",
           &s7_string(16, &[0x47, 0x72, 0xFC, 0xDF, 0x65])),
        // Outside DBs SFC can read only simple types: its raw and chunked forms fail there (defect D2).
        st("m_byte", Markers, 0, "BYTE", "%MB0:BYTE", "16#A5", &[0xA5]),
        flag("m_bit", Markers, 0, 0, true, "%M0.0:BOOL"),
        flag("m_bit1", Markers, 0, 1, false, "%M0.1:BOOL"),
        st("m_int", Markers, 2, "INT", "%MW2:INT", "-12345", &(-12345i16).to_be_bytes()),
        st("m_real", Markers, 4, "REAL", "%MD4:REAL", "12345.5", &12345.5f32.to_be_bytes()),
        st("m_lreal", Markers, 20, "LREAL", "%M20:LREAL", "1.5", &1.5f64.to_be_bytes()),
        st("i_byte", Inputs, 0, "BYTE", "%IB0:BYTE", "16#81", &[0x81]),
        flag("i_bit0", Inputs, 0, 0, true, "%I0.0:BOOL"),
        flag("i_bit1", Inputs, 0, 1, false, "%I0.1:BOOL"),
        flag("i_bit7", Inputs, 0, 7, true, "%I0.7:BOOL"),
        st("i_int", Inputs, 2, "INT", "%IW2:INT", "12345", &12345i16.to_be_bytes()),
        st("i_real", Inputs, 4, "REAL", "%ID4:REAL", "1.5", &1.5f32.to_be_bytes()),
        st("q_byte", Outputs, 0, "BYTE", "%QB0:BYTE", "16#3C", &[0x3C]),
        flag("q_bit0", Outputs, 0, 0, false, "%Q0.0:BOOL"),
        flag("q_bit", Outputs, 0, 2, true, "%Q0.2:BOOL"),
        st("q_int", Outputs, 2, "INT", "%QW2:INT", "-2", &(-2i16).to_be_bytes()),
        st("q_real", Outputs, 4, "REAL", "%QD4:REAL", "-0.25", &(-0.25f32).to_be_bytes()),
    ]
}

/// A dynamic tag, for `--print-map`: (area, byte, bit, tag, type, SFC address, signal).
type DynamicTag = (Area, usize, Option<u8>, &'static str, &'static str, &'static str, &'static str);

const DYNAMIC: &[DynamicTag] = &[
    (Area::Db(100), 0, None, "scan", "DINT", "%DB100.DBD0:DINT", "scan number k"),
    (Area::Db(100), 4, None, "t", "LREAL", "%DB100:4:LREAL", "seconds, k·cycle_ms/1000"),
    (Area::Db(100), 12, None, "sine", "REAL", "%DB100.DBD12:REAL", "sine"),
    (Area::Db(100), 16, None, "cosine", "REAL", "%DB100.DBD16:REAL", "cosine"),
    (Area::Db(100), 20, None, "tangent", "REAL", "%DB100.DBD20:REAL", "tangent"),
    (Area::Db(100), 24, None, "cotangent", "REAL", "%DB100.DBD24:REAL", "cotangent"),
    (Area::Db(100), 28, None, "exp", "REAL", "%DB100.DBD28:REAL", "exp"),
    (Area::Db(100), 32, None, "quadratic", "REAL", "%DB100.DBD32:REAL", "quadratic"),
    (Area::Db(100), 36, None, "sawtooth", "REAL", "%DB100.DBD36:REAL", "sawtooth"),
    (Area::Db(100), 40, None, "triangle", "REAL", "%DB100.DBD40:REAL", "triangle"),
    (Area::Db(100), 44, None, "square", "REAL", "%DB100.DBD44:REAL", "square"),
    (Area::Db(100), 48, None, "damped", "REAL", "%DB100.DBD48:REAL", "damped"),
    (Area::Db(100), 52, None, "noise", "REAL", "%DB100.DBD52:REAL", "noise"),
    (Area::Db(100), 56, None, "randomwalk", "REAL", "%DB100.DBD56:REAL", "randomwalk"),
    (Area::Db(100), 60, None, "sine64", "LREAL", "%DB100:60:LREAL", "sine (negative half: defect D1)"),
    (Area::Db(100), 68, None, "sine_int", "INT", "%DB100.DBW68:INT", "round(100·sine)"),
    (Area::Db(100), 70, Some(0), "blink_1hz", "BOOL", "%DB100.DBX70.0:BOOL", "blink_1hz"),
    (Area::Db(100), 70, Some(1), "blink_5hz", "BOOL", "%DB100.DBX70.1:BOOL", "blink_5hz"),
    (Area::Markers, 8, None, "m_scan", "DINT", "%MD8:DINT", "scan number k"),
    (Area::Markers, 12, None, "m_sine", "REAL", "%MD12:REAL", "sine"),
    (Area::Markers, 16, Some(0), "m_blink_1hz", "BOOL", "%M16.0:BOOL", "blink_1hz"),
    (Area::Markers, 16, Some(1), "m_blink_5hz", "BOOL", "%M16.1:BOOL", "blink_5hz"),
    (Area::Inputs, 8, Some(0), "i_blink_1hz", "BOOL", "%I8.0:BOOL", "blink_1hz"),
];

fn write(mem: &mut [u8], at: usize, bytes: &[u8]) {
    if let Some(dst) = mem.get_mut(at..at + bytes.len()) {
        dst.copy_from_slice(bytes);
    }
}

fn set_bit(mem: &mut [u8], byte: usize, bit: u8, v: bool) {
    if let Some(b) = mem.get_mut(byte) {
        if v {
            *b |= 1 << bit;
        } else {
            *b &= !(1 << bit);
        }
    }
}

/// The CPU's memory: DB1 (static) and DB100 (dynamic), the I, Q and M areas, timers and counters.
pub struct Image {
    pub dbs: BTreeMap<u16, Vec<u8>>,
    pub inputs: Vec<u8>,
    pub outputs: Vec<u8>,
    pub markers: Vec<u8>,
    /// Two bytes per timer and per counter, all zero.
    pub timers: Vec<u8>,
    pub counters: Vec<u8>,
    /// The scan the dynamic tags come from.
    pub scan: u64,
}

impl Image {
    fn new(p: &Profile) -> Image {
        let mut img = Image {
            dbs: BTreeMap::from([(1, vec![0; DB1_BYTES]), (100, vec![0; DB100_BYTES])]),
            inputs: vec![0; p.i_bytes],
            outputs: vec![0; p.q_bytes],
            markers: vec![0; p.m_bytes],
            timers: vec![0; 2 * p.timers],
            counters: vec![0; 2 * p.counters],
            scan: 0,
        };
        for tag in statics() {
            img.put(tag.area, tag.byte, &tag.enc);
        }
        img
    }

    fn area(&self, area: Area) -> Option<&[u8]> {
        Some(match area {
            Area::Db(n) => self.dbs.get(&n)?.as_slice(),
            Area::Inputs => self.inputs.as_slice(),
            Area::Outputs => self.outputs.as_slice(),
            Area::Markers => self.markers.as_slice(),
            Area::Counters => self.counters.as_slice(),
            Area::Timers => self.timers.as_slice(),
        })
    }

    fn area_mut(&mut self, area: Area) -> Option<&mut [u8]> {
        Some(match area {
            Area::Db(n) => self.dbs.get_mut(&n)?.as_mut_slice(),
            Area::Inputs => self.inputs.as_mut_slice(),
            Area::Outputs => self.outputs.as_mut_slice(),
            Area::Markers => self.markers.as_mut_slice(),
            Area::Counters => self.counters.as_mut_slice(),
            Area::Timers => self.timers.as_mut_slice(),
        })
    }

    fn put(&mut self, area: Area, byte: usize, enc: &Enc) {
        let Some(mem) = self.area_mut(area) else { return };
        match enc {
            Enc::Bit(bit, v) => set_bit(mem, byte, *bit, *v),
            Enc::Bytes(bytes) => write(mem, byte, bytes),
        }
    }
}

impl ScanImage for Image {
    fn scan(&mut self, s: &Scan) {
        let v = &s.v;
        let real = |x: f64| (x as f32).to_be_bytes();
        // A DINT counter, as a PLC program keeps one: it wraps after 2³¹ scans (248 days at 10 ms).
        let scan = (s.k as i32).to_be_bytes();
        if let Some(db) = self.dbs.get_mut(&100) {
            write(db, 0, &scan);
            write(db, 4, &s.t.to_be_bytes());
            let reals = [v.sine, v.cosine, v.tangent, v.cotangent, v.exp, v.quadratic, v.sawtooth, v.triangle,
                         v.square, v.damped, v.noise, v.randomwalk];
            for (i, x) in reals.iter().enumerate() {
                write(db, 12 + 4 * i, &real(*x));
            }
            write(db, 60, &v.sine.to_be_bytes());
            write(db, 68, &scaled_i16(v.sine, 100.0).to_be_bytes());
            set_bit(db, 70, 0, v.blink_1hz);
            set_bit(db, 70, 1, v.blink_5hz);
        }
        write(&mut self.markers, 8, &scan);
        write(&mut self.markers, 12, &real(v.sine));
        set_bit(&mut self.markers, 16, 0, v.blink_1hz);
        set_bit(&mut self.markers, 16, 1, v.blink_5hz);
        set_bit(&mut self.inputs, 8, 0, v.blink_1hz);
        self.scan = s.k;
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
enum State {
    /// Only a COTP CR is accepted.
    #[default]
    AwaitCr,
    /// Only Setup Communication (or a disconnect request) is accepted.
    AwaitSetup,
    Ready,
}

/// A connection's unparsed input and its COTP and S7 session.
#[derive(Debug, Default)]
pub struct Conn {
    pub id: u64,
    buf: Vec<u8>,
    state: State,
    /// The client's COTP reference, the destination reference of the CC and the DC.
    client_ref: u16,
    /// The negotiated PDU size.
    pdu: u16,
}

impl Conn {
    pub fn new(id: u64) -> Conn {
        Conn { id, ..Conn::default() }
    }

    /// The server's COTP reference: the connection number, never 0.
    fn server_ref(&self) -> u16 {
        match (self.id % 0xFFFF) as u16 {
            0 => 0xFFFF,
            r => r,
        }
    }
}

/// The outcome of feeding bytes to a connection.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct Output {
    /// Replies, in request order; each one goes out in a single write.
    pub replies: Vec<Vec<u8>>,
    /// The connection ends, for this reason: input that cannot be served, or a disconnect request.
    pub close: Option<&'static str>,
}

/// What one TPKT frame leads to.
#[derive(Debug, PartialEq, Eq)]
pub enum Action {
    Reply(Vec<u8>),
    /// Reply, then close: the answer to a disconnect request.
    ReplyAndClose(Vec<u8>, &'static str),
    /// Close without a reply.
    Close(&'static str),
}

/// An S7ANY item: the ten bytes after `12 0A`.
#[derive(Debug, Clone, Copy)]
struct Item {
    syntax: u8,
    ts: u8,
    count: u16,
    db: u16,
    area: u8,
    /// Byte·8 + bit; PLC4X sends 5 zero bits, 16 bits of byte and 3 of bit, the same for bytes below 65536.
    address: u32,
}

impl Item {
    fn parse(b: &[u8; 10]) -> Item {
        Item {
            syntax: b[0],
            ts: b[1],
            count: u16::from_be_bytes([b[2], b[3]]),
            db: u16::from_be_bytes([b[4], b[5]]),
            area: b[6],
            address: u32::from_be_bytes([0, b[7], b[8], b[9]]),
        }
    }

    /// The item in wire units, for the events log. Timers and counters are numbered, so their `byte` is
    /// the number.
    fn detail(&self, rc: u8) -> Value {
        let (byte, bit) = match self.area {
            0x1C | 0x1D => (self.address, 0),
            _ => (self.address >> 3, self.address & 7),
        };
        json!({"area": area_name(self.area), "db": self.db, "byte": byte, "bit": bit, "ts": self.ts,
               "count": self.count, "rc": rc})
    }
}

/// A read item's reply: transport size, length field (in the unit the transport size counts) and data.
struct Data {
    ts: u8,
    len: usize,
    bytes: Vec<u8>,
}

/// Bytes per element, the reply transport size and whether the reply length counts bits. The reply sizes
/// follow snap7; PLC4X only needs the length unit to match the code.
fn element(ts: u8, date_and_time: bool) -> Option<(usize, u8, bool)> {
    Some(match ts {
        TS_BIT => (1, DATA_BIT, true),
        TS_BYTE => (1, DATA_BYTE, true),
        TS_CHAR => (1, DATA_OCTETS, false),
        TS_WORD | TS_DATE | TS_S5TIME => (2, DATA_BYTE, true),
        TS_INT => (2, DATA_INT, true),
        TS_DWORD | TS_TOD | TS_TIME => (4, DATA_BYTE, true),
        TS_DINT => (4, DATA_INT, true),
        TS_REAL => (4, DATA_REAL, false),
        // The 8-byte DATE_AND_TIME of a real CPU; PLC4X's DT alias expects 12 bytes (defect D7).
        TS_DATE_AND_TIME if date_and_time => (8, DATA_BYTE, true),
        TS_COUNTER | TS_TIMER => (2, DATA_OCTETS, false),
        _ => return None,
    })
}

/// SZL 0x0011 (module identification). Records 0x0001 and 0x0006 carry the order number, 0x0007 the
/// firmware as 'V' major, minor, patch, where snap7's GetOrderCode reads it.
fn identity_records(p: &Profile) -> Vec<u8> {
    let mlfb = padded(p.mlfb, 20, b' ');
    let blank = [b' '; 20];
    let (major, minor, patch) = p.firmware;
    let mut out = Vec::with_capacity(3 * 28);
    for (index, order, ausbg, ausbe) in [
        (0x0001u16, &mlfb[..], 0x0001u16, 0x0001u16),
        (0x0006, &mlfb[..], 0x0001, 0x0001),
        (0x0007, &blank[..], u16::from_be_bytes([b'V', major]), u16::from_be_bytes([minor, patch])),
    ] {
        out.extend_from_slice(&index.to_be_bytes());
        out.extend_from_slice(order);
        out.extend_from_slice(&[0x00, 0x00]); // BGTyp
        out.extend_from_slice(&ausbg.to_be_bytes());
        out.extend_from_slice(&ausbe.to_be_bytes());
    }
    out
}

/// SZL 0x001C (component identification), 34-byte records in the order snap7's GetCpuInfo indexes them:
/// station name, module name, plant designation, copyright, serial number, module type name. Six records
/// still fit the S7-300's 240-byte PDU.
fn component_records(p: &Profile) -> Vec<u8> {
    let texts = [(1u16, p.station), (2, p.module_name), (3, ""), (4, "Original Siemens Equipment"), (5, p.serial),
                 (7, p.module_type)];
    let mut out = Vec::with_capacity(texts.len() * 34);
    for (index, text) in texts {
        out.extend_from_slice(&index.to_be_bytes());
        out.extend_from_slice(&padded(text, 32, 0x00));
    }
    out
}

/// The records of an SZL-ID: (record length, records), or `None` for an ID this CPU does not have.
fn szl_records(p: &Profile, id: u16) -> Option<(usize, Vec<u8>)> {
    match id {
        0x0011 => Some((28, identity_records(p))),
        0x001C => Some((34, component_records(p))),
        _ => None,
    }
}

/// `text` cut or filled to `n` bytes.
fn padded(text: &str, n: usize, fill: u8) -> Vec<u8> {
    let mut out: Vec<u8> = text.bytes().take(n).collect();
    out.resize(n, fill);
    out
}

/// A COTP TPDU in a TPKT.
fn tpkt(cotp: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(4 + cotp.len());
    out.extend_from_slice(&[0x03, 0x00]);
    out.extend_from_slice(&((4 + cotp.len()) as u16).to_be_bytes());
    out.extend_from_slice(cotp);
    out
}

/// An S7 PDU in one COTP DT with EOT set and NR 0: PLC4X does not reassemble segments.
fn dt(pdu: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(7 + pdu.len());
    out.extend_from_slice(&[0x03, 0x00]);
    out.extend_from_slice(&((7 + pdu.len()) as u16).to_be_bytes());
    out.extend_from_slice(&[0x02, 0xF0, 0x80]);
    out.extend_from_slice(pdu);
    out
}

/// Ack (ROSCTR 2): the 12-byte header alone.
fn s7_ack(pdu_ref: u16, error: (u8, u8)) -> Vec<u8> {
    let mut out = vec![0x32, 0x02, 0x00, 0x00];
    out.extend_from_slice(&pdu_ref.to_be_bytes());
    out.extend_from_slice(&[0x00, 0x00, 0x00, 0x00, error.0, error.1]);
    out
}

/// Ack_Data (ROSCTR 3): the 12-byte header with error class and code, parameter, data.
fn s7_ack_data(pdu_ref: u16, error: (u8, u8), param: &[u8], data: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(12 + param.len() + data.len());
    out.extend_from_slice(&[0x32, 0x03, 0x00, 0x00]);
    out.extend_from_slice(&pdu_ref.to_be_bytes());
    out.extend_from_slice(&(param.len() as u16).to_be_bytes());
    out.extend_from_slice(&(data.len() as u16).to_be_bytes());
    out.extend_from_slice(&[error.0, error.1]);
    out.extend_from_slice(param);
    out.extend_from_slice(data);
    out
}

/// UserData (ROSCTR 7): the 10-byte header, parameter, data.
fn s7_user_data(pdu_ref: u16, param: &[u8], data: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(10 + param.len() + data.len());
    out.extend_from_slice(&[0x32, 0x07, 0x00, 0x00]);
    out.extend_from_slice(&pdu_ref.to_be_bytes());
    out.extend_from_slice(&(param.len() as u16).to_be_bytes());
    out.extend_from_slice(&(data.len() as u16).to_be_bytes());
    out.extend_from_slice(param);
    out.extend_from_slice(data);
    out
}

/// A UserData error: a response (type 8) to `group` with the error code in the parameter and an empty data
/// item with return code 0x0A.
fn s7_user_data_error(pdu_ref: u16, group: u8, subfunction: u8, sequence: u8, code: u16) -> Vec<u8> {
    let [hi, lo] = code.to_be_bytes();
    let param = [0x00, 0x01, 0x12, 0x08, 0x12, 0x80 | group, subfunction, sequence, 0x00, 0x00, hi, lo];
    s7_user_data(pdu_ref, &param, &[RC_NOT_FOUND, 0x00, 0x00, 0x00])
}

/// The S7 header of a Job or UserData: protocol ID, ROSCTR, PDU reference, parameter and data length.
fn s7_header(pdu: &[u8]) -> Option<(u8, u8, u16, usize, usize)> {
    let mut r = Reader::new(pdu);
    let (protocol, rosctr) = (r.u8()?, r.u8()?);
    r.skip(2)?; // reserved
    Some((protocol, rosctr, r.be_u16()?, r.be_u16()? as usize, r.be_u16()? as usize))
}

fn error_status(error: (u8, u8)) -> String {
    format!("0x{:02X}{:02X}", error.0, error.1)
}

fn hex16(v: u16) -> String {
    format!("0x{v:04X}")
}

fn tsap(t: Option<&[u8]>) -> Value {
    t.map_or(Value::Null, |t| json!(format!("0x{}", t.iter().map(|b| format!("{b:02X}")).collect::<String>())))
}

/// Logs why the connection ends without a reply.
fn close(conn: &Conn, events: &Events, reason: &'static str, mut detail: Value) -> Action {
    detail["reason"] = json!(reason);
    events.emit(NAME, conn.id, "drop", detail, "dropped");
    Action::Close(reason)
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

    /// Splits `input` (appended to what the connection already holds) into TPKT frames by their declared
    /// length and answers each.
    pub fn feed(&self, conn: &mut Conn, input: &[u8], events: &Events) -> Output {
        conn.buf.extend_from_slice(input);
        let mut out = Output::default();
        while conn.buf.len() >= 4 {
            let version = conn.buf[0];
            let len = u16::from_be_bytes([conn.buf[2], conn.buf[3]]) as usize;
            // Seven bytes are the TPKT header and the shortest COTP DT header.
            if version != 0x03 || len < 7 {
                let reason = if version != 0x03 { "tpkt_version" } else { "tpkt_length" };
                events.emit(NAME, conn.id, "drop", json!({"reason": reason, "version": version, "length": len}),
                            "dropped");
                out.close = Some(reason);
                break;
            }
            if conn.buf.len() < len {
                break;
            }
            let frame: Vec<u8> = conn.buf.drain(..len).collect();
            match self.handle(conn, &frame, events) {
                Action::Reply(reply) => out.replies.push(reply),
                Action::ReplyAndClose(reply, reason) => {
                    out.replies.push(reply);
                    out.close = Some(reason);
                    break;
                }
                Action::Close(reason) => {
                    out.close = Some(reason);
                    break;
                }
            }
        }
        if out.close.is_some() {
            conn.buf.clear();
        }
        out
    }

    /// Answers one complete TPKT frame, following the connection's COTP and S7 state.
    pub fn handle(&self, conn: &mut Conn, frame: &[u8], events: &Events) -> Action {
        let (Some(&li), Some(&code)) = (frame.get(4), frame.get(5)) else {
            return close(conn, events, "short_frame", json!({"length": frame.len()}));
        };
        let end = 5 + li as usize;
        if li == 0 || end > frame.len() {
            return close(conn, events, "cotp_length", json!({"li": li, "length": frame.len()}));
        }
        let (header, payload) = (&frame[4..end], &frame[end..]);
        match (code, conn.state) {
            (0xF0, State::AwaitCr) => close(conn, events, "dt_before_cc", json!({})),
            (0xF0, _) if li != 2 => close(conn, events, "dt_length", json!({"li": li})),
            // EOT clear: one segment of a longer PDU. PLC4X never segments and reassembly is optional, so
            // the connection ends instead.
            (0xF0, _) if header[2] & 0x80 == 0 => close(conn, events, "segmented_dt", json!({})),
            (0xF0, _) => self.on_s7(conn, payload, events),
            (c, State::AwaitCr) if c & 0xF0 == 0xE0 => self.on_cr(conn, header, events),
            (c, State::AwaitSetup | State::Ready) if c & 0xF0 == 0x80 => self.on_dr(conn, events),
            // A second CR, a DR before the CC, CC, DC, ER and unknown TPDUs.
            (c, state) => close(conn, events, "unexpected_tpdu", json!({"code": c, "state": format!("{state:?}")})),
        }
    }

    /// COTP CR → CC. A called TSAP outside the profile's connection types and slots closes the
    /// connection: a DR would leave PLC4X waiting for a CC forever, a close fails its connect().
    fn on_cr(&self, conn: &mut Conn, header: &[u8], events: &Events) -> Action {
        // LI, E0, destination reference, source reference, class, then TLV parameters up to the end of
        // the LI. Bytes after the LI (user data) are ignored.
        if header.len() < 7 {
            return close(conn, events, "cr_length", json!({"li": header.len() - 1}));
        }
        let src_ref = u16::from_be_bytes([header[4], header[5]]);
        let (mut tpdu, mut calling, mut called) = (None, None, None);
        let mut tlv = Reader::new(&header[7..]);
        while tlv.remaining() > 0 {
            let parameter = tlv.u8().and_then(|code| {
                let n = tlv.u8()? as usize;
                Some((code, tlv.bytes(n)?))
            });
            match parameter {
                Some((0xC0, value)) => tpdu = value.first().copied(),
                Some((0xC1, value)) => calling = Some(value),
                Some((0xC2, value)) => called = Some(value),
                Some(_) => {}
                None => return close(conn, events, "cr_parameter", json!({"src_ref": src_ref})),
            }
        }
        let detail = json!({"src_ref": src_ref, "calling": tsap(calling), "called": tsap(called), "tpdu": tpdu});
        // High byte: connection type (PG, OP, basic). Low byte: rack·32 + slot. PLC4X encodes rack·16 +
        // slot (defect D13), which agrees for rack 0.
        let accepted = called.is_some_and(|t| {
            t.len() == 2 && (1..=3).contains(&t[0]) && self.profile.slots.contains(&(t[1] >> 5, t[1] & 0x1F))
        });
        let Some(called) = called.filter(|_| accepted) else {
            return close(conn, events, "tsap", detail);
        };
        // PLC4X reads C0, C1 and C2 by type with fixed value sizes, logs a different calling TSAP as
        // "Switching calling TSAP id" and every other parameter as "Got unknown parameter type".
        let mut params = vec![0xC0, 0x01, tpdu.map_or(TPDU_MAX, |t| t.min(TPDU_MAX))];
        for (code, value) in [(0xC1, calling), (0xC2, Some(called))] {
            if let Some(value) = value {
                params.extend_from_slice(&[code, value.len() as u8]);
                params.extend_from_slice(value);
            }
        }
        let mut cotp = vec![(6 + params.len()) as u8, 0xD0];
        cotp.extend_from_slice(&src_ref.to_be_bytes());
        cotp.extend_from_slice(&conn.server_ref().to_be_bytes());
        cotp.push(0x00); // class 0
        cotp.extend_from_slice(&params);
        conn.client_ref = src_ref;
        conn.state = State::AwaitSetup;
        events.emit(NAME, conn.id, "cr", detail, "ok");
        Action::Reply(tpkt(&cotp))
    }

    /// COTP DR → DC, then close. SFC never sends a DR; it is what ends an ISO transport connection.
    fn on_dr(&self, conn: &Conn, events: &Events) -> Action {
        events.emit(NAME, conn.id, "dr", json!({"client_ref": conn.client_ref}), "ok");
        let mut dc = vec![0x05, 0xC0];
        dc.extend_from_slice(&conn.client_ref.to_be_bytes());
        dc.extend_from_slice(&conn.server_ref().to_be_bytes());
        Action::ReplyAndClose(tpkt(&dc), "dr")
    }

    fn on_s7(&self, conn: &mut Conn, pdu: &[u8], events: &Events) -> Action {
        let Some((protocol, rosctr, pdu_ref, plen, dlen)) = s7_header(pdu) else {
            return close(conn, events, "s7_header", json!({"length": pdu.len()}));
        };
        if protocol != 0x32 {
            return close(conn, events, "protocol_id", json!({"protocol": protocol}));
        }
        if 10 + plen + dlen != pdu.len() {
            return close(conn, events, "s7_length",
                         json!({"ref": pdu_ref, "parameter": plen, "data": dlen, "pdu": pdu.len()}));
        }
        let (param, data) = pdu[10..].split_at(plen);
        match (rosctr, conn.state) {
            (0x01, _) => self.on_job(conn, pdu_ref, param, data, events),
            (0x07, State::Ready) => self.on_user_data(conn, pdu_ref, param, data, events),
            (0x07, _) => close(conn, events, "user_data_before_setup", json!({"ref": pdu_ref})),
            (rosctr, _) => close(conn, events, "rosctr", json!({"ref": pdu_ref, "rosctr": rosctr})),
        }
    }

    fn on_job(&self, conn: &mut Conn, pdu_ref: u16, param: &[u8], data: &[u8], events: &Events) -> Action {
        let Some(&function) = param.first() else {
            return close(conn, events, "job_parameter", json!({"ref": pdu_ref}));
        };
        if function == 0xF0 {
            return self.on_setup(conn, pdu_ref, param, data, events);
        }
        if conn.state != State::Ready {
            return close(conn, events, "job_before_setup", json!({"ref": pdu_ref, "function": function}));
        }
        match function {
            0x04 => self.on_read(conn, pdu_ref, param, data, events),
            // Writes are not simulated: the answer of a CPU whose PUT/GET access is off.
            0x05 => {
                events.emit(NAME, conn.id, "write", json!({"ref": pdu_ref, "n": param.get(1)}),
                            &error_status(NOT_AVAILABLE));
                Action::Reply(dt(&s7_ack_data(pdu_ref, NOT_AVAILABLE, &[0x05, 0x00], &[])))
            }
            // Block transfer, PLC control, stop: not available.
            _ => {
                events.emit(NAME, conn.id, "unsupported_function", json!({"ref": pdu_ref, "function": function}),
                            &error_status(NOT_AVAILABLE));
                Action::Reply(dt(&s7_ack(pdu_ref, NOT_AVAILABLE)))
            }
        }
    }

    /// Setup Communication: each value is the smaller of request and profile. Allowed again on a set-up
    /// connection, as a renegotiation.
    fn on_setup(&self, conn: &mut Conn, pdu_ref: u16, param: &[u8], data: &[u8], events: &Events) -> Action {
        // F0, reserved, AmQ calling, AmQ called, PDU length.
        if param.len() != 8 || !data.is_empty() {
            return close(conn, events, "setup_length",
                         json!({"ref": pdu_ref, "parameter": param.len(), "data": data.len()}));
        }
        let word = |i: usize| u16::from_be_bytes([param[i], param[i + 1]]);
        let (calling, called, pdu) = (word(2), word(4), word(6));
        if pdu < 16 {
            return close(conn, events, "setup_pdu", json!({"ref": pdu_ref, "pdu": pdu}));
        }
        let p = &self.profile;
        // PLC4X keeps AmQ called requests in flight, so 0 would stall every read.
        let amq = (calling.min(p.amq_max.0).max(1), called.min(p.amq_max.1).max(1));
        // SFC packs PDU − 18 bytes of data into one request (S7Controller.kt:159-161).
        let size = pdu.min(p.pdu_max);
        conn.pdu = size;
        conn.state = State::Ready;
        events.emit(NAME, conn.id, "setup", json!({
            "ref": pdu_ref, "amq_calling": amq.0, "amq_called": amq.1, "pdu": size,
            "requested": {"amq_calling": calling, "amq_called": called, "pdu": pdu},
        }), "ok");
        let mut reply = vec![0xF0, 0x00];
        for w in [amq.0, amq.1, size] {
            reply.extend_from_slice(&w.to_be_bytes());
        }
        Action::Reply(dt(&s7_ack_data(pdu_ref, (0x00, 0x00), &reply, &[])))
    }

    /// Read Var: every item from one snapshot of the image, in request order.
    fn on_read(&self, conn: &Conn, pdu_ref: u16, param: &[u8], data: &[u8], events: &Events) -> Action {
        let n = param.get(1).copied().unwrap_or(0) as usize;
        if n == 0 || param.len() != 2 + 12 * n || !data.is_empty() {
            return close(conn, events, "read_var_length",
                         json!({"ref": pdu_ref, "n": n, "parameter": param.len(), "data": data.len()}));
        }
        let mut items = Vec::with_capacity(n);
        for spec in param[2..].as_chunks::<12>().0 {
            // Variable specification 0x12 and address length 10 introduce every S7ANY item.
            let [0x12, 0x0A, address @ ..] = spec else {
                return close(conn, events, "read_var_item", json!({"ref": pdu_ref, "spec": hex(&spec[..2])}));
            };
            items.push(Item::parse(address));
        }
        if 10 + param.len() > conn.pdu as usize {
            return self.too_large(conn, pdu_ref, n, events);
        }
        let (results, scan) = {
            let img = self.image.read().unwrap_or_else(|e| e.into_inner());
            let results: Vec<Result<Data, u8>> = items.iter().map(|it| self.read_item(&img, it)).collect();
            (results, img.scan)
        };
        // An odd data length is padded to a word, except after the last item (S7VarPayloadDataItemIO).
        let pad = |i: usize, d: &Data| (d.bytes.len() % 2 == 1 && i + 1 < n) as usize;
        let size: usize = results.iter().enumerate()
            .map(|(i, r)| r.as_ref().map_or(4, |d| 4 + d.bytes.len() + pad(i, d)))
            .sum();
        if 14 + size > conn.pdu as usize {
            return self.too_large(conn, pdu_ref, n, events);
        }
        let mut payload = Vec::with_capacity(size);
        for (i, result) in results.iter().enumerate() {
            match result {
                Ok(d) => {
                    payload.extend_from_slice(&[RC_OK, d.ts]);
                    // The reply fits one PDU of at most 960 bytes, so even a length in bits fits 16 bits.
                    payload.extend_from_slice(&(d.len as u16).to_be_bytes());
                    payload.extend_from_slice(&d.bytes);
                    payload.resize(payload.len() + pad(i, d), 0x00);
                }
                // An error item carries no data and no padding.
                Err(rc) => payload.extend_from_slice(&[*rc, 0x00, 0x00, 0x00]),
            }
        }
        let rcs: Vec<u8> = results.iter().map(|r| r.as_ref().map_or_else(|rc| *rc, |_| RC_OK)).collect();
        let status = rcs.iter().find(|rc| **rc != RC_OK).map_or_else(|| "ok".to_string(), |rc| format!("0x{rc:02X}"));
        let detail: Vec<Value> = items.iter().zip(&rcs).map(|(it, rc)| it.detail(*rc)).collect();
        events.emit(NAME, conn.id, "read", json!({"ref": pdu_ref, "scan": scan, "n": n, "items": detail}), &status);
        Action::Reply(dt(&s7_ack_data(pdu_ref, (0x00, 0x00), &[0x04, n as u8], &payload)))
    }

    fn too_large(&self, conn: &Conn, pdu_ref: u16, n: usize, events: &Events) -> Action {
        events.emit(NAME, conn.id, "read", json!({"ref": pdu_ref, "n": n, "pdu": conn.pdu}),
                    &error_status(PDU_TOO_LARGE));
        Action::Reply(dt(&s7_ack_data(pdu_ref, PDU_TOO_LARGE, &[0x04, 0x00], &[])))
    }

    /// One item, checked in a CPU's order: syntax ID, transport size, count, bit address, area, range.
    fn read_item(&self, img: &Image, it: &Item) -> Result<Data, u8> {
        if it.syntax != 0x10 {
            return Err(RC_INVALID_ADDRESS);
        }
        let (size, ts, bits) = element(it.ts, self.profile.date_and_time).ok_or(RC_TYPE_NOT_SUPPORTED)?;
        // A BIT item names one bit. What a CPU does with a larger count is unverified; the spec
        // recommends 0x05.
        if it.count == 0 || (it.ts == TS_BIT && it.count != 1) {
            return Err(RC_INVALID_ADDRESS);
        }
        let numbered = matches!(it.ts, TS_COUNTER | TS_TIMER);
        // Timers and counters are addressed by number (snap7's convention), every other non-BIT item
        // starts on a byte.
        if it.ts != TS_BIT && !numbered && it.address & 7 != 0 {
            return Err(RC_INVALID_ADDRESS);
        }
        let area = Area::from_wire(it.area, it.db).ok_or(RC_INVALID_ADDRESS)?;
        let mem = img.area(area).ok_or(RC_NOT_FOUND)?;
        let own = match area {
            Area::Counters => Some(TS_COUNTER),
            Area::Timers => Some(TS_TIMER),
            _ => None,
        };
        if own.is_some() && mem.is_empty() {
            return Err(RC_NOT_FOUND);
        }
        // Timers and counters are read only with their own transport size and nothing else is; 0x06 for
        // the other combinations is the spec's unverified choice.
        if own.map_or(numbered, |own| own != it.ts) {
            return Err(RC_TYPE_NOT_SUPPORTED);
        }
        let start = if own.is_some() { 2 * it.address as usize } else { (it.address >> 3) as usize };
        if it.ts == TS_BIT {
            let byte = *mem.get(start).ok_or(RC_INVALID_ADDRESS)?;
            // The value goes in bit 0: PLC4X reads seven reserved bits, then the value.
            return Ok(Data { ts, len: 1, bytes: vec![(byte >> (it.address & 7)) & 1] });
        }
        let n = it.count as usize * size;
        let bytes = mem.get(start..start + n).ok_or(RC_INVALID_ADDRESS)?.to_vec();
        Ok(Data { ts, len: if bits { 8 * n } else { n }, bytes })
    }

    /// UserData: the SZL read (CPU functions, group 4, subfunction 1); 0x8104 for everything else (cyclic
    /// data, alarms, clock, block functions).
    fn on_user_data(&self, conn: &Conn, pdu_ref: u16, param: &[u8], data: &[u8], events: &Events) -> Action {
        // 00, one item, 12, item length 4 (8 with data-unit reference, last-unit flag and error code),
        // method, type and group, subfunction, sequence number.
        let item_len = param.get(3).copied().unwrap_or(0) as usize;
        if !matches!(item_len, 4 | 8) || param.len() != 4 + item_len || param[..3] != [0x00, 0x01, 0x12] {
            return close(conn, events, "user_data_parameter", json!({"ref": pdu_ref, "parameter": hex(param)}));
        }
        let (group, subfunction, sequence) = (param[5] & 0x0F, param[6], param[7]);
        if group == 4 && subfunction == 1 {
            return self.on_szl(conn, pdu_ref, sequence, data, events);
        }
        events.emit(NAME, conn.id, "user_data", json!({"ref": pdu_ref, "group": group, "subfunction": subfunction}),
                    &hex16(UD_NOT_AVAILABLE));
        Action::Reply(dt(&s7_user_data_error(pdu_ref, group, subfunction, sequence, UD_NOT_AVAILABLE)))
    }

    /// Read SZL. PLC4X requires a response of type 8 and subfunction 1, record length 28 and, for its
    /// connect() to complete, one record with index 0x0001.
    fn on_szl(&self, conn: &Conn, pdu_ref: u16, sequence: u8, data: &[u8], events: &Events) -> Action {
        // FF, 09, length 4, SZL-ID, index.
        if data.len() != 8 || data[2..4] != [0x00, 0x04] {
            return close(conn, events, "szl_data", json!({"ref": pdu_ref, "data": hex(data)}));
        }
        let id = u16::from_be_bytes([data[4], data[5]]);
        let index = u16::from_be_bytes([data[6], data[7]]);
        let mut detail = json!({"ref": pdu_ref, "szl_id": hex16(id), "index": hex16(index)});
        let Some((record_len, records)) = szl_records(&self.profile, id) else {
            events.emit(NAME, conn.id, "szl", detail, &hex16(UD_NO_SZL));
            return Action::Reply(dt(&s7_user_data_error(pdu_ref, 4, 1, sequence, UD_NO_SZL)));
        };
        let count = records.len() / record_len;
        detail["records"] = json!(count);
        events.emit(NAME, conn.id, "szl", detail, "ok");
        // Every index returns the whole list; the IDs that select one record (0x0111, 0x011C) are not
        // simulated.
        let mut payload = vec![RC_OK, DATA_OCTETS];
        for w in [8 + records.len(), id as usize, index as usize, record_len, count] {
            payload.extend_from_slice(&(w as u16).to_be_bytes());
        }
        payload.extend_from_slice(&records);
        // Response (type 8) to CPU functions (group 4), subfunction 1; sequence number and data-unit fields
        // are not checked by PLC4X.
        let param = [0x00, 0x01, 0x12, 0x08, 0x12, 0x84, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00];
        Action::Reply(dt(&s7_user_data(pdu_ref, &param, &payload)))
    }

    pub fn print_map(&self) -> Value {
        let p = &self.profile;
        let mut rows = Vec::new();
        for tag in statics() {
            let bit = match tag.enc {
                Enc::Bit(bit, _) => Some(bit),
                Enc::Bytes(_) => None,
            };
            rows.push(json!({
                "area": tag.area.label(), "byte": tag.byte, "bit": bit, "sfc": {"Address": tag.address},
                "tag": tag.tag, "type": tag.kind, "value": tag.value,
            }));
        }
        for (area, byte, bit, tag, kind, address, signal) in DYNAMIC {
            rows.push(json!({
                "area": area.label(), "byte": byte, "bit": bit, "sfc": {"Address": address},
                "tag": tag, "type": kind, "value": "dynamic", "signal": signal,
            }));
        }
        let slots: Vec<Value> = p.slots.iter().map(|(rack, slot)| json!({"rack": rack, "slot": slot})).collect();
        let (major, minor, patch) = p.firmware;
        json!({
            "protocol": NAME, "profile": p.name, "device": p.title,
            "identity": {"mlfb": p.mlfb, "firmware": format!("V{major}.{minor}.{patch}"), "module_type": p.module_type},
            "pdu_max": p.pdu_max, "amq_max": {"calling": p.amq_max.0, "called": p.amq_max.1},
            "tsap": {
                "accepted": slots,
                "note": "the called TSAP must be connection type 01..03 and one of these (rack, slot); PLC4X sends \
                         0x0100 | RemoteRack << 4 | RemoteSlot, so SFC's defaults (0, 0) reach only s7-1200 and \
                         s7-1500, and s7-300/400 cases set RemoteSlot 2 or 3",
            },
            "areas": {"DB1": DB1_BYTES, "DB100": DB100_BYTES, "I": p.i_bytes, "Q": p.q_bytes, "M": p.m_bytes,
                      "T": p.timers, "C": p.counters},
            "date_and_time": p.date_and_time,
            "tags": rows,
        })
    }

    pub async fn serve(self: Arc<Self>, listener: TcpListener, events: Events) -> anyhow::Result<()> {
        loop {
            let (stream, peer) = super::accept(&listener, NAME).await;
            let server = self.clone();
            let events = events.clone();
            tokio::spawn(async move {
                let id = events.next_conn();
                events.emit(NAME, id, "connect", json!({"peer": peer.to_string()}), "ok");
                let reason = server.connection(stream, id, &events).await;
                events.emit(NAME, id, "disconnect", json!({"reason": reason}), "ok");
            });
        }
    }

    async fn connection(&self, mut stream: TcpStream, id: u64, events: &Events) -> &'static str {
        let _ = stream.set_nodelay(true);
        let mut conn = Conn::new(id);
        let mut buf = vec![0u8; 4096];
        loop {
            let n = match stream.read(&mut buf).await {
                Ok(0) => return "eof",
                Ok(n) => n,
                Err(_) => return "read_error",
            };
            let out = self.feed(&mut conn, &buf[..n], events);
            for reply in &out.replies {
                if stream.write_all(reply).await.is_err() {
                    return "write_error";
                }
            }
            if let Some(reason) = out.close {
                return reason;
            }
        }
    }
}
