// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! Modbus TCP server (Modbus Application Protocol V1.1b3, Messaging on TCP/IP V1.0b).
//!
//! What SFC's modbus-tcp adapter needs: MBAP framing by the declared length, the transaction id and
//! unit echoed, FC 1-4, and only exception codes 1-4 (it rejects any other code and loses the frame
//! sync). On top of that, as a real device would: FC 0x2B/0x0E device identification, exception 0x01
//! for every other function code (writes are not simulated), and three device profiles.
//!
//! Address map (SFC `Address` = wire + 1): see `--print-map modbus` and ci/omni-plc-sim/README.md.

use std::sync::{Arc, RwLock};

use anyhow::bail;
use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

use crate::core::clock::civil;
use crate::core::engine::{Image as ScanImage, Scan, ScanTarget};
use crate::core::events::Events;
use crate::core::signal::scaled_i16;

pub const NAME: &str = "modbus";
pub const DEFAULT_PROFILE: &str = "generic";
pub const PROFILES: &[&str] = &["generic", "s7-1200", "modicon-m340"];

const MAX_READ_BITS: u16 = 2000;
const MAX_READ_REGISTERS: u16 = 125;

/// The exceptions this server sends. SFC accepts only these four (Modbus.kt:247-252).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Exception {
    IllegalFunction = 1,
    IllegalDataAddress = 2,
    IllegalDataValue = 3,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WordOrder {
    /// Most significant word at the lower address.
    Abcd,
    /// Least significant word first (Modicon %MD/%MF overlaying %MW pairs).
    Cdab,
}

#[derive(Debug, Clone)]
pub struct Profile {
    pub name: &'static str,
    pub title: &'static str,
    pub coils: usize,
    pub discrete_inputs: usize,
    pub input_registers: usize,
    pub holding_registers: usize,
    /// FC 2 reads the coils and FC 4 the holding registers (Modicon %M and %MW).
    pub alias: bool,
    pub word_order: WordOrder,
    /// First character in the low byte of a register.
    pub string_low_first: bool,
    /// FC 0x2B/0x0E: conformity level and objects; `None` answers 0x01.
    pub identity: Option<(u8, Vec<(u8, &'static str)>)>,
}

pub fn profile(name: &str) -> anyhow::Result<Profile> {
    Ok(match name {
        "generic" => Profile {
            name: "generic",
            title: "Modbus TCP reference server at the protocol maxima",
            coils: 65536,
            discrete_inputs: 65536,
            input_registers: 65536,
            holding_registers: 65536,
            alias: false,
            word_order: WordOrder::Abcd,
            string_low_first: false,
            identity: Some((0x83, vec![
                (0x00, "Amazon Web Services"),
                (0x01, "OPS-MB-GENERIC"),
                (0x02, "V1.0"),
                (0x03, "https://aws.amazon.com"),
                (0x04, "omni-plc-sim"),
                (0x05, "generic"),
                (0x06, "SFC e2e"),
                (0x80, "SIM-0001"),
            ])),
        },
        "s7-1200" => Profile {
            name: "s7-1200",
            title: "SIMATIC S7-1200 CPU 1214C (6ES7 214-1AG40-0XB0) with MB_SERVER",
            coils: 8192,
            discrete_inputs: 8192,
            input_registers: 512,
            holding_registers: 1000,
            alias: false,
            word_order: WordOrder::Abcd,
            string_low_first: false,
            identity: None,
        },
        "modicon-m340" => Profile {
            name: "modicon-m340",
            title: "Modicon M340 BMX P34 2020, embedded Ethernet",
            coils: 8192,
            discrete_inputs: 8192,
            input_registers: 10000,
            holding_registers: 10000,
            alias: true,
            word_order: WordOrder::Cdab,
            string_low_first: true,
            identity: Some((0x82, vec![
                (0x00, "Schneider Electric"),
                (0x01, "BMX P34 2020"),
                (0x02, "V3.20"),
                (0x03, "www.schneider-electric.com"),
                (0x04, "Modicon M340"),
                (0x05, "BMX P34 2020"),
                (0x06, "SFC_E2E"),
            ])),
        },
        other => bail!("unknown modbus profile {other:?}; known: {}", PROFILES.join(", ")),
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Table {
    Coils,
    DiscreteInputs,
    InputRegisters,
    HoldingRegisters,
}

impl Table {
    fn name(self) -> &'static str {
        match self {
            Table::Coils => "coils",
            Table::DiscreteInputs => "discrete_inputs",
            Table::InputRegisters => "input_registers",
            Table::HoldingRegisters => "holding_registers",
        }
    }

    fn sfc_type(self) -> &'static str {
        match self {
            Table::Coils => "Coil",
            Table::DiscreteInputs => "DiscreteInput",
            Table::InputRegisters => "InputRegister",
            Table::HoldingRegisters => "HoldingRegister",
        }
    }
}

/// How a static tag is laid out in registers.
#[derive(Debug, Clone)]
enum Enc {
    Bit(bool),
    /// One register.
    W(u16),
    /// A fixed layout that ignores the profile's word and byte order (`*_cdab`, S7 DT/DTL, BCD…).
    Ws(Vec<u16>),
    /// 32 bits in the profile's word order.
    D(u32),
    /// 64 bits in the profile's word order.
    Q(u64),
    /// ASCII, two characters per register in the profile's byte order, NUL-padded to `words`.
    Str(&'static str, usize),
}

struct StaticTag {
    name: &'static str,
    table: Table,
    wire: u16,
    enc: Enc,
    kind: &'static str,
}

fn st(name: &'static str, table: Table, wire: u16, kind: &'static str, enc: Enc) -> StaticTag {
    StaticTag { name, table, wire, enc, kind }
}

fn statics() -> Vec<StaticTag> {
    use Table::*;
    let f = |v: f32| v.to_bits();
    let mut out = vec![
        st("bool_true", Coils, 0, "BOOL", Enc::Bit(true)),
        st("bool_false", Coils, 1, "BOOL", Enc::Bit(false)),
        st("di_false", DiscreteInputs, 0, "BOOL", Enc::Bit(false)),
        st("di_true", DiscreteInputs, 1, "BOOL", Enc::Bit(true)),
        st("run", DiscreteInputs, 19, "BOOL", Enc::Bit(true)),
        st("ai_static", InputRegisters, 8, "INT[8] (Siemens analog counts)",
           Enc::Ws(vec![0, 6912, 13824, 20736, 27648, 32511, 32767, 0x9400])),
        st("bool_true", HoldingRegisters, 0, "BOOL", Enc::W(1)),
        st("bool_false", HoldingRegisters, 1, "BOOL", Enc::W(0)),
        st("byte", HoldingRegisters, 2, "BYTE", Enc::W(0xA5)),
        st("sint", HoldingRegisters, 3, "SINT", Enc::W(-100i16 as u16)),
        st("usint", HoldingRegisters, 4, "USINT", Enc::W(200)),
        st("int", HoldingRegisters, 5, "INT", Enc::W(-12345i16 as u16)),
        st("uint", HoldingRegisters, 6, "UINT", Enc::W(54321)),
        st("word", HoldingRegisters, 7, "WORD", Enc::W(54321)),
        st("dint", HoldingRegisters, 8, "DINT", Enc::D(-1_234_567_890i32 as u32)),
        st("udint", HoldingRegisters, 10, "UDINT", Enc::D(3_000_000_000)),
        st("dword", HoldingRegisters, 12, "DWORD", Enc::D(3_000_000_000)),
        st("lint", HoldingRegisters, 14, "LINT", Enc::Q(-1_234_567_890_123i64 as u64)),
        st("ulint", HoldingRegisters, 18, "ULINT", Enc::Q(12_345_678_901_234)),
        st("real", HoldingRegisters, 22, "REAL", Enc::D(f(12345.5))),
        st("lreal", HoldingRegisters, 24, "LREAL", Enc::Q((-98765.4375f64).to_bits())),
        st("time", HoldingRegisters, 28, "TIME (DINT ms)", Enc::D(1234)),
        st("string", HoldingRegisters, 30, "CHAR[16]", Enc::Str("SFC-SIM", 8)),
        st("string_bs", HoldingRegisters, 38, "CHAR[16], byte-swapped",
           Enc::Ws(vec![0x4653, 0x2D43, 0x4953, 0x004D, 0, 0, 0, 0])),
        st("bcd", HoldingRegisters, 46, "BCD16", Enc::W(0x1234)),
        st("status_word", HoldingRegisters, 47, "WORD (bits 0,1,6,7,8,10,13,15)", Enc::W(0xA5C3)),
        st("date", HoldingRegisters, 48, "S7 DATE (days since 1990-01-01)", Enc::W(12584)),
        st("tod", HoldingRegisters, 49, "S7 TOD (ms)", Enc::D(45_296_789)),
        st("dt", HoldingRegisters, 51, "S7 DATE_AND_TIME (BCD)", Enc::Ws(vec![0x2406, 0x1512, 0x3456, 0x7897])),
        st("dtl", HoldingRegisters, 55, "S7 DTL", Enc::Ws(vec![0x07E8, 0x060F, 0x070C, 0x2238, 0x2F07, 0x2F40])),
        st("clock7", HoldingRegisters, 61, "year, month, day, hour, min, sec, ms",
           Enc::Ws(vec![2024, 6, 15, 12, 34, 56, 789])),
        st("epoch", HoldingRegisters, 68, "UDINT Unix seconds", Enc::D(1_718_454_896)),
        st("m10k", HoldingRegisters, 70, "INT32-M10K (hi·10000 + lo)", Enc::Ws(vec![12345, 6789])),
        st("real_cdab", HoldingRegisters, 72, "REAL, word-swapped", Enc::Ws(vec![0xE600, 0x4640])),
        st("real_badc", HoldingRegisters, 74, "REAL, byte-swapped", Enc::Ws(vec![0x4046, 0x00E6])),
        st("real_dcba", HoldingRegisters, 76, "REAL, reversed", Enc::Ws(vec![0x00E6, 0x4046])),
        st("dint_cdab", HoldingRegisters, 78, "DINT, word-swapped", Enc::Ws(vec![0xFD2E, 0xB669])),
        st("pattern", HoldingRegisters, 80, "WAGO-style test words",
           Enc::Ws(vec![0x0000, 0xFFFF, 0x1234, 0xAAAA, 0x5555, 0x7FFF, 0x8000, 0x3FFF, 0x4000])),
        st("int_array", HoldingRegisters, 89, "ARRAY[0..7] OF INT",
           Enc::Ws([0i16, 1, -1, 1000, -1000, 32767, -32768, 12345].iter().map(|v| *v as u16).collect())),
        st("real_array[0]", HoldingRegisters, 97, "REAL", Enc::D(f(0.0))),
        st("real_array[1]", HoldingRegisters, 99, "REAL", Enc::D(f(1.0))),
        st("real_array[2]", HoldingRegisters, 101, "REAL", Enc::D(f(-1.0))),
        st("real_array[3]", HoldingRegisters, 103, "REAL", Enc::D(f(std::f32::consts::PI))),
        st("motor.id", HoldingRegisters, 105, "INT", Enc::W(7)),
        st("motor.speed", HoldingRegisters, 106, "REAL", Enc::D(f(1500.25))),
        st("motor.running", HoldingRegisters, 108, "BOOL", Enc::W(1)),
        st("motor.faults", HoldingRegisters, 109, "WORD", Enc::W(5)),
        st("run_state", HoldingRegisters, 317, "UINT (1 = RUN)", Enc::W(1)),
        st("ton_pt", HoldingRegisters, 318, "DINT ms", Enc::D(5000)),
        st("ctu_pv", HoldingRegisters, 324, "UINT", Enc::W(10)),
        st("dev_vendor", HoldingRegisters, 330, "CHAR[16]", Enc::Str("AWS", 8)),
        st("dev_product", HoldingRegisters, 338, "CHAR[16]", Enc::Str("omni-plc-sim", 8)),
        st("fw_major", HoldingRegisters, 346, "UINT", Enc::W(1)),
        st("fw_minor", HoldingRegisters, 347, "UINT", Enc::W(0)),
        st("serial", HoldingRegisters, 348, "UDINT", Enc::D(20_240_615)),
    ];
    // Coils 2..9 hold 0xA5 and discrete inputs 2..9 hold 0x5A, least significant bit first.
    for i in 0..8u16 {
        out.push(st("byte_bits", Coils, 2 + i, "BOOL", Enc::Bit(0xA5 >> i & 1 == 1)));
        out.push(st("byte_bits_5a", DiscreteInputs, 2 + i, "BOOL", Enc::Bit(0x5A >> i & 1 == 1)));
    }
    out
}

/// The dynamic tags, for `--print-map`: (table, wire, registers or bits, tag, encoding).
const DYNAMIC: &[(Table, u16, u16, &str, &str)] = &[
    (Table::Coils, 16, 1, "blink_1hz", "BOOL"),
    (Table::Coils, 17, 1, "blink_5hz", "BOOL"),
    (Table::Coils, 18, 1, "ton_q", "BOOL"),
    (Table::Coils, 19, 1, "ctu_q", "BOOL"),
    (Table::Coils, 32, 16, "scan_bits", "BOOL[16], bit i of scan mod 2^16"),
    (Table::DiscreteInputs, 16, 1, "blink_5hz", "BOOL"),
    (Table::DiscreteInputs, 17, 1, "blink_1hz", "BOOL"),
    (Table::DiscreteInputs, 18, 1, "ton_in", "BOOL"),
    (Table::InputRegisters, 0, 1, "ai_sine", "INT counts 13824 + 138.24·sine"),
    (Table::InputRegisters, 1, 1, "ai_cosine", "INT counts"),
    (Table::InputRegisters, 2, 1, "ai_triangle", "INT counts"),
    (Table::InputRegisters, 3, 1, "ai_sawtooth", "INT counts"),
    (Table::InputRegisters, 4, 1, "ai_square", "INT counts"),
    (Table::InputRegisters, 5, 1, "ai_noise", "INT counts"),
    (Table::InputRegisters, 6, 1, "ai_randomwalk", "INT counts"),
    (Table::InputRegisters, 7, 1, "ai_damped", "INT counts"),
    (Table::InputRegisters, 16, 1, "ir_scan16", "UINT scan mod 2^16"),
    (Table::InputRegisters, 17, 2, "ir_scan32", "UDINT scan"),
    (Table::HoldingRegisters, 200, 1, "scan16", "UINT scan mod 2^16"),
    (Table::HoldingRegisters, 201, 2, "scan32", "UDINT scan"),
    (Table::HoldingRegisters, 203, 4, "scan", "ULINT scan"),
    (Table::HoldingRegisters, 207, 4, "t", "LREAL seconds"),
    (Table::HoldingRegisters, 211, 2, "sine", "REAL"),
    (Table::HoldingRegisters, 213, 2, "cosine", "REAL"),
    (Table::HoldingRegisters, 215, 2, "tangent", "REAL"),
    (Table::HoldingRegisters, 217, 2, "cotangent", "REAL"),
    (Table::HoldingRegisters, 219, 2, "exp", "REAL"),
    (Table::HoldingRegisters, 221, 2, "quadratic", "REAL"),
    (Table::HoldingRegisters, 223, 2, "sawtooth", "REAL"),
    (Table::HoldingRegisters, 225, 2, "triangle", "REAL"),
    (Table::HoldingRegisters, 227, 2, "square", "REAL"),
    (Table::HoldingRegisters, 229, 2, "damped", "REAL"),
    (Table::HoldingRegisters, 231, 2, "noise", "REAL"),
    (Table::HoldingRegisters, 233, 2, "randomwalk", "REAL"),
    (Table::HoldingRegisters, 235, 4, "sine64", "LREAL"),
    (Table::HoldingRegisters, 239, 1, "sine_int", "INT round(100·sine)"),
    (Table::HoldingRegisters, 240, 1, "blink_1hz", "BOOL in a register"),
    (Table::HoldingRegisters, 241, 1, "blink_5hz", "BOOL in a register"),
    (Table::HoldingRegisters, 300, 7, "rtc7", "year, month, day, hour, min, sec, ms (PLC clock)"),
    (Table::HoldingRegisters, 307, 4, "rtc_bcd", "BCD YYYY, MMDD, hhmm, ss00"),
    (Table::HoldingRegisters, 311, 1, "rtc_weekday", "ISO 1 = Monday … 7 = Sunday"),
    (Table::HoldingRegisters, 312, 2, "rtc_epoch", "UDINT Unix seconds"),
    (Table::HoldingRegisters, 314, 2, "uptime_s", "UDINT seconds"),
    (Table::HoldingRegisters, 316, 1, "cycle_ms", "UINT"),
    (Table::HoldingRegisters, 320, 2, "ton_et", "DINT ms, TON with IN = (t mod 7) < 6, PT 5 s"),
    (Table::HoldingRegisters, 322, 1, "ton_in", "BOOL"),
    (Table::HoldingRegisters, 323, 1, "ton_q", "BOOL"),
    (Table::HoldingRegisters, 325, 1, "ctu_cv", "UINT, floor(t) mod 16"),
    (Table::HoldingRegisters, 326, 1, "ctu_q", "BOOL, CV >= PV"),
];

/// The four tables.
pub struct Image {
    word_order: WordOrder,
    string_low_first: bool,
    pub coils: Vec<bool>,
    pub discrete_inputs: Vec<bool>,
    pub input_registers: Vec<u16>,
    pub holding_registers: Vec<u16>,
}

impl Image {
    fn new(p: &Profile) -> Image {
        let mut img = Image {
            word_order: p.word_order,
            string_low_first: p.string_low_first,
            coils: vec![false; p.coils],
            discrete_inputs: vec![false; p.discrete_inputs],
            input_registers: vec![0; p.input_registers],
            holding_registers: vec![0; p.holding_registers],
        };
        for tag in statics() {
            img.put(tag.table, tag.wire, &tag.enc);
        }
        img
    }

    fn words32(&self, v: u32) -> [u16; 2] {
        let (hi, lo) = ((v >> 16) as u16, v as u16);
        match self.word_order {
            WordOrder::Abcd => [hi, lo],
            WordOrder::Cdab => [lo, hi],
        }
    }

    fn words64(&self, v: u64) -> [u16; 4] {
        let w = [(v >> 48) as u16, (v >> 32) as u16, (v >> 16) as u16, v as u16];
        match self.word_order {
            WordOrder::Abcd => w,
            WordOrder::Cdab => [w[3], w[2], w[1], w[0]],
        }
    }

    fn set_bit(&mut self, table: Table, wire: u16, v: bool) {
        let t = match table {
            Table::Coils => &mut self.coils,
            Table::DiscreteInputs => &mut self.discrete_inputs,
            _ => return,
        };
        if let Some(slot) = t.get_mut(wire as usize) {
            *slot = v;
        }
    }

    fn set_words(&mut self, table: Table, wire: u16, words: &[u16]) {
        let t = match table {
            Table::InputRegisters => &mut self.input_registers,
            Table::HoldingRegisters => &mut self.holding_registers,
            _ => return,
        };
        for (i, w) in words.iter().enumerate() {
            if let Some(slot) = t.get_mut(wire as usize + i) {
                *slot = *w;
            }
        }
    }

    fn put(&mut self, table: Table, wire: u16, enc: &Enc) {
        match enc {
            Enc::Bit(b) => self.set_bit(table, wire, *b),
            Enc::W(w) => self.set_words(table, wire, &[*w]),
            Enc::Ws(ws) => self.set_words(table, wire, ws),
            Enc::D(v) => {
                let w = self.words32(*v);
                self.set_words(table, wire, &w)
            }
            Enc::Q(v) => {
                let w = self.words64(*v);
                self.set_words(table, wire, &w)
            }
            Enc::Str(s, words) => {
                let mut bytes: Vec<u8> = s.bytes().collect();
                bytes.resize(words * 2, 0);
                let ws: Vec<u16> = bytes
                    .chunks(2)
                    .map(|p| if self.string_low_first { u16::from_le_bytes([p[0], p[1]]) } else { u16::from_be_bytes([p[0], p[1]]) })
                    .collect();
                self.set_words(table, wire, &ws)
            }
        }
    }

    fn hr(&mut self, wire: u16, words: &[u16]) {
        self.set_words(Table::HoldingRegisters, wire, words);
    }
}

fn bcd(v: u32) -> u16 {
    ((v / 1000 % 10) << 12 | (v / 100 % 10) << 8 | (v / 10 % 10) << 4 | v % 10) as u16
}

fn analog(v: f64) -> u16 {
    (13824.0 + 138.24 * v).round().clamp(-32768.0, 32767.0) as i16 as u16
}

impl ScanImage for Image {
    fn scan(&mut self, s: &Scan) {
        let v = &s.v;
        let k = s.k;
        let real = |x: f64| (x as f32).to_bits();

        for (wire, b) in [(16, v.blink_1hz), (17, v.blink_5hz)] {
            self.set_bit(Table::Coils, wire, b);
        }
        self.set_bit(Table::DiscreteInputs, 16, v.blink_5hz);
        self.set_bit(Table::DiscreteInputs, 17, v.blink_1hz);
        for i in 0..16u16 {
            self.set_bit(Table::Coils, 32 + i, (k >> i) & 1 == 1);
        }

        let ai = [v.sine, v.cosine, v.triangle, v.sawtooth, v.square, v.noise, v.randomwalk, v.damped];
        let ai: Vec<u16> = ai.iter().map(|x| analog(*x)).collect();
        self.set_words(Table::InputRegisters, 0, &ai);
        self.set_words(Table::InputRegisters, 16, &[k as u16]);
        let w = self.words32(k as u32);
        self.set_words(Table::InputRegisters, 17, &w);

        self.hr(200, &[k as u16]);
        let w = self.words32(k as u32);
        self.hr(201, &w);
        let w = self.words64(k);
        self.hr(203, &w);
        let w = self.words64(s.t.to_bits());
        self.hr(207, &w);
        let reals = [v.sine, v.cosine, v.tangent, v.cotangent, v.exp, v.quadratic, v.sawtooth, v.triangle, v.square,
                     v.damped, v.noise, v.randomwalk];
        for (i, x) in reals.iter().enumerate() {
            let w = self.words32(real(*x));
            self.hr(211 + 2 * i as u16, &w);
        }
        let w = self.words64(v.sine.to_bits());
        self.hr(235, &w);
        self.hr(239, &[scaled_i16(v.sine, 100.0) as u16, v.blink_1hz as u16, v.blink_5hz as u16]);

        // PLC system block: the PLC clock, uptime, a TON and a CTU.
        let c = civil(s.wall_ms);
        self.hr(300, &[c.year as u16, c.month as u16, c.day as u16, c.hour as u16, c.minute as u16, c.second as u16,
                       c.millis as u16]);
        self.hr(307, &[bcd(c.year as u32), bcd(c.month) << 8 | bcd(c.day), bcd(c.hour) << 8 | bcd(c.minute),
                       bcd(c.second) << 8]);
        self.hr(311, &[if c.weekday == 0 { 7 } else { c.weekday as u16 }]);
        let w = self.words32(s.wall_ms.div_euclid(1000) as u32);
        self.hr(312, &w);
        let w = self.words32(s.t.floor() as u32);
        self.hr(314, &w);
        self.hr(316, &[s.cycle_ms.min(u16::MAX as u64) as u16]);
        let tm = s.t.rem_euclid(7.0);
        let ton_in = tm < 6.0;
        let ton_q = ton_in && tm >= 5.0;
        let ton_et = if ton_in { ((tm * 1000.0).floor() as u32).min(5000) } else { 0 };
        let w = self.words32(ton_et);
        self.hr(320, &w);
        self.hr(322, &[ton_in as u16, ton_q as u16]);
        let ctu_cv = (s.t.floor() as u64 % 16) as u16;
        let ctu_q = ctu_cv >= 10;
        self.hr(325, &[ctu_cv, ctu_q as u16]);
        self.set_bit(Table::Coils, 18, ton_q);
        self.set_bit(Table::Coils, 19, ctu_q);
        self.set_bit(Table::DiscreteInputs, 18, ton_in);
    }
}

/// A connection's unparsed input.
#[derive(Debug, Default)]
pub struct Conn {
    pub id: u64,
    buf: Vec<u8>,
}

impl Conn {
    pub fn new(id: u64) -> Conn {
        Conn { id, buf: Vec::new() }
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
        loop {
            if conn.buf.len() < 7 {
                break;
            }
            let tid = u16::from_be_bytes([conn.buf[0], conn.buf[1]]);
            let pid = u16::from_be_bytes([conn.buf[2], conn.buf[3]]);
            let len = u16::from_be_bytes([conn.buf[4], conn.buf[5]]) as usize;
            if !(2..=254).contains(&len) {
                events.emit(NAME, conn.id, "drop", json!({"tid": tid, "reason": "bad_length", "length": len}), "dropped");
                out.close = true;
                conn.buf.clear();
                break;
            }
            if conn.buf.len() < 6 + len {
                break;
            }
            let frame: Vec<u8> = conn.buf.drain(..6 + len).collect();
            if pid != 0 {
                events.emit(NAME, conn.id, "drop", json!({"tid": tid, "reason": "protocol_id", "pid": pid}), "dropped");
                continue;
            }
            out.replies.push(self.handle(conn.id, &frame, events));
        }
        out
    }

    /// Answers one complete ADU (MBAP header plus PDU).
    pub fn handle(&self, conn: u64, frame: &[u8], events: &Events) -> Vec<u8> {
        let tid = u16::from_be_bytes([frame[0], frame[1]]);
        let unit = frame[6];
        let pdu = &frame[7..];
        let fc = pdu[0];
        let (op, detail, result) = self.execute(pdu);
        let mut detail = detail;
        detail["tid"] = json!(tid);
        detail["unit"] = json!(unit);
        detail["fc"] = json!(fc);
        let reply_pdu = match result {
            Ok(data) => {
                events.emit(NAME, conn, op, detail, "ok");
                data
            }
            Err(e) => {
                let code = e as u8;
                detail["exception"] = json!(code);
                events.emit(NAME, conn, op, detail, &format!("0x{code:02X}"));
                vec![fc | 0x80, code]
            }
        };
        let mut adu = Vec::with_capacity(7 + reply_pdu.len());
        adu.extend_from_slice(&tid.to_be_bytes());
        adu.extend_from_slice(&[0, 0]);
        adu.extend_from_slice(&(1 + reply_pdu.len() as u16).to_be_bytes());
        adu.push(unit);
        adu.extend_from_slice(&reply_pdu);
        adu
    }

    /// The check order of the protocol's state diagrams: function code (0x01), then length and
    /// quantity (0x03), then range (0x02).
    fn execute(&self, pdu: &[u8]) -> (&'static str, Value, Result<Vec<u8>, Exception>) {
        let fc = pdu[0];
        match fc {
            0x01 | 0x02 => {
                let op = if fc == 1 { "read_coils" } else { "read_discrete_inputs" };
                let Some((addr, qty)) = addr_qty(pdu) else {
                    return (op, json!({}), Err(Exception::IllegalDataValue));
                };
                let detail = json!({"addr": addr, "qty": qty});
                if qty == 0 || qty > MAX_READ_BITS {
                    return (op, detail, Err(Exception::IllegalDataValue));
                }
                let img = self.image.read().unwrap_or_else(|e| e.into_inner());
                let table = if fc == 1 || self.profile.alias { &img.coils } else { &img.discrete_inputs };
                let (start, end) = (addr as usize, addr as usize + qty as usize);
                if end > table.len() {
                    return (op, detail, Err(Exception::IllegalDataAddress));
                }
                let n = (qty as usize).div_ceil(8);
                let mut data = vec![0u8; n];
                for (i, bit) in table[start..end].iter().enumerate() {
                    if *bit {
                        data[i / 8] |= 1 << (i % 8);
                    }
                }
                let mut reply = vec![fc, n as u8];
                reply.extend_from_slice(&data);
                (op, detail, Ok(reply))
            }
            0x03 | 0x04 => {
                let op = if fc == 3 { "read_holding_registers" } else { "read_input_registers" };
                let Some((addr, qty)) = addr_qty(pdu) else {
                    return (op, json!({}), Err(Exception::IllegalDataValue));
                };
                let detail = json!({"addr": addr, "qty": qty});
                if qty == 0 || qty > MAX_READ_REGISTERS {
                    return (op, detail, Err(Exception::IllegalDataValue));
                }
                let img = self.image.read().unwrap_or_else(|e| e.into_inner());
                let table = if fc == 3 || self.profile.alias { &img.holding_registers } else { &img.input_registers };
                let (start, end) = (addr as usize, addr as usize + qty as usize);
                if end > table.len() {
                    return (op, detail, Err(Exception::IllegalDataAddress));
                }
                let mut reply = vec![fc, (2 * qty) as u8];
                for w in &table[start..end] {
                    reply.extend_from_slice(&w.to_be_bytes());
                }
                (op, detail, Ok(reply))
            }
            0x2B => self.device_identification(pdu),
            _ => ("unsupported_fc", json!({}), Err(Exception::IllegalFunction)),
        }
    }

    /// FC 0x2B / MEI 0x0E, Read Device Identification (basic, regular, extended stream; individual).
    fn device_identification(&self, pdu: &[u8]) -> (&'static str, Value, Result<Vec<u8>, Exception>) {
        let op = "read_device_identification";
        let Some((conformity, objects)) = &self.profile.identity else {
            return (op, json!({}), Err(Exception::IllegalFunction));
        };
        if pdu.len() < 2 {
            return (op, json!({}), Err(Exception::IllegalDataValue));
        }
        if pdu[1] != 0x0E {
            return (op, json!({"mei": pdu[1]}), Err(Exception::IllegalFunction));
        }
        if pdu.len() != 4 {
            return (op, json!({}), Err(Exception::IllegalDataValue));
        }
        let (code, object) = (pdu[2], pdu[3]);
        let detail = json!({"code": code, "object": object});
        if !(1..=4).contains(&code) {
            return (op, detail, Err(Exception::IllegalDataValue));
        }
        // A stream above the device's conformity level is answered at that level.
        let level = conformity & 0x7F;
        let effective = if code == 4 { 4 } else { code.min(level) };
        let selected: Vec<&(u8, &str)> = if effective == 4 {
            match objects.iter().find(|(id, _)| *id == object) {
                Some(o) => vec![o],
                None => return (op, detail, Err(Exception::IllegalDataAddress)),
            }
        } else {
            let in_stream = |id: u8| match effective {
                1 => id <= 0x02,
                2 => id <= 0x06,
                _ => true,
            };
            let start = if objects.iter().any(|(id, _)| *id == object && in_stream(*id)) { object } else { 0 };
            objects.iter().filter(|(id, _)| in_stream(*id) && *id >= start).collect()
        };
        let mut reply = vec![0x2B, 0x0E, effective, *conformity, 0x00, 0x00, selected.len() as u8];
        for (id, text) in selected {
            reply.push(*id);
            reply.push(text.len() as u8);
            reply.extend_from_slice(text.as_bytes());
        }
        (op, detail, Ok(reply))
    }

    pub fn print_map(&self) -> Value {
        let mut rows = Vec::new();
        for tag in statics() {
            let size = match &tag.enc {
                Enc::Bit(_) | Enc::W(_) => 1,
                Enc::Ws(ws) => ws.len(),
                Enc::D(_) => 2,
                Enc::Q(_) => 4,
                Enc::Str(_, words) => *words,
            };
            rows.push(json!({
                "table": tag.table.name(), "wire": tag.wire, "sfc": {"Type": tag.table.sfc_type(), "Address": tag.wire as u32 + 1, "Size": size},
                "tag": tag.name, "type": tag.kind, "value": format!("{:?}", tag.enc),
            }));
        }
        for (table, wire, size, tag, kind) in DYNAMIC {
            rows.push(json!({
                "table": table.name(), "wire": wire, "sfc": {"Type": table.sfc_type(), "Address": *wire as u32 + 1, "Size": size},
                "tag": tag, "type": kind, "value": "dynamic",
            }));
        }
        json!({
            "protocol": NAME, "profile": self.profile.name, "device": self.profile.title,
            "tables": {"coils": self.profile.coils, "discrete_inputs": self.profile.discrete_inputs,
                       "input_registers": self.profile.input_registers, "holding_registers": self.profile.holding_registers},
            "aliases": self.profile.alias, "word_order": format!("{:?}", self.profile.word_order),
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
            if out.close {
                return "bad_length";
            }
        }
    }
}

/// Start address and quantity of a read request; the PDU must be exactly 5 bytes.
fn addr_qty(pdu: &[u8]) -> Option<(u16, u16)> {
    if pdu.len() != 5 {
        return None;
    }
    Some((u16::from_be_bytes([pdu[1], pdu[2]]), u16::from_be_bytes([pdu[3], pdu[4]])))
}
