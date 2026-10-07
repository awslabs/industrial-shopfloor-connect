// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! Beckhoff ADS server (TwinCAT 2 and 3), ADS over AMS/TCP.
//!
//! What SFC's ads adapter needs: framing by the declared AMS/TCP length (the client reads exactly
//! 6 + N bytes, byte by byte, and never resynchronises), command and invoke id echoed with state flags
//! 0x0005, and three requests: Read 0xF00F (upload info), Read 0xF00B (the symbol upload, whose entries
//! it walks by entryLength) and ReadWrite 0xF080 (one sum read of every channel per cycle). On top of
//! that, as a TwinCAT runtime would: the router errors 6, 7 and 0xE, ReadDeviceInfo, ReadState and the
//! device data group 0xF100, a second PLC runtime on AMS port 852, the system service on port 10000, and
//! three profiles. Writes, WriteControl, symbol handles and notifications are not simulated; they get
//! the answers of a read-only device (`Server::plc_command`).
//!
//! Symbol table and address map: see `--print-map ads` and ci/omni-plc-sim/README.md.

use std::f64::consts::TAU;
use std::fmt;
use std::sync::{Arc, RwLock};

use anyhow::bail;
use serde_json::{json, Map, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

use crate::core::clock::unix_ms;
use crate::core::codec::{hex, Reader};
use crate::core::engine::{Image as ScanImage, Scan, ScanTarget};
use crate::core::events::Events;
use crate::core::signal::{scaled_i16, Values};

pub const NAME: &str = "ads";
pub const DEFAULT_PROFILE: &str = "tc3-ipc";
pub const PROFILES: &[&str] = &["tc3-ipc", "tc3-cx8190", "tc2-pc"];

/// The most ADS data one frame may carry; the AMS/TCP length adds the 32-byte AMS header.
pub const MAX_DATA: usize = 1 << 20;
/// Unverified: TwinCAT documents no item limit for sum commands; 500 is where clients split them.
const MAX_SUM_ITEMS: u32 = 500;
/// The TwinCAT system service, which answers identity and state only.
const SYSTEM_PORT: u16 = 10000;
/// Response and ADS command: the only state flags SFC accepts (GetSymbolsResponse.kt:103).
const RESPONSE_FLAGS: u16 = 0x0005;
const ADS_STATE_RUN: u16 = 5;
const SYMBOL_VERSION: u8 = 1;
/// TwinCAT's distributed clock counts nanoseconds from 2000-01-01; this is that instant in Unix ms.
const DC_EPOCH_MS: i64 = 946_684_800_000;

const CMD_READ_DEVICE_INFO: u16 = 1;
const CMD_READ: u16 = 2;
const CMD_WRITE: u16 = 3;
const CMD_READ_STATE: u16 = 4;
const CMD_WRITE_CONTROL: u16 = 5;
const CMD_ADD_NOTIFICATION: u16 = 6;
const CMD_DELETE_NOTIFICATION: u16 = 7;
const CMD_DEVICE_NOTIFICATION: u16 = 8;
const CMD_READ_WRITE: u16 = 9;

// Router errors, in the AMS header of a reply without data. SFC checks the header error before
// anything else (RequestResponse.kt:91) and prints it by number (AdsException.kt:10-116).
const ERR_TARGET_PORT: u32 = 0x0006;
const ERR_TARGET_MACHINE: u32 = 0x0007;
const ERR_AMS_LENGTH: u32 = 0x000E;

/// The ADS errors this server sends in a reply's result field, or in a sum read's item results.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AdsErr {
    ServiceNotSupported = 0x701,
    InvalidGroup = 0x702,
    InvalidOffset = 0x703,
    InvalidAccess = 0x704,
    InvalidSize = 0x705,
    InvalidParam = 0x70B,
    InvalidNotifyHandle = 0x714,
}

const IG_DATA: u32 = 0x4040;
const IG_M: u32 = 0x4020;
const IG_M_BITS: u32 = 0x4021;
const IG_I: u32 = 0xF020;
const IG_I_BITS: u32 = 0xF021;
const IG_Q: u32 = 0xF030;
const IG_Q_BITS: u32 = 0xF031;
const IG_SYM_VERSION: u32 = 0xF008;
const IG_SYM_UPLOAD: u32 = 0xF00B;
const IG_SYM_UPLOADINFO: u32 = 0xF00C;
const IG_SYM_DT_UPLOAD: u32 = 0xF00E;
const IG_SYM_UPLOADINFO2: u32 = 0xF00F;
const IG_SUMUP_READ: u32 = 0xF080;
const IG_SUMUP_WRITE: u32 = 0xF081;
const IG_SUMUP_READWRITE: u32 = 0xF082;
const IG_DEVICE_DATA: u32 = 0xF100;

/// A byte area of a PLC runtime: the PLC data (0x4040), %M (0x4020), %I (0xF020) and %Q (0xF030).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Area {
    Data,
    M,
    I,
    Q,
}

impl Area {
    const ALL: [Area; 4] = [Area::Data, Area::M, Area::I, Area::Q];

    fn size(self) -> usize {
        match self {
            Area::Data => 65536,
            Area::M => 4096,
            Area::I | Area::Q => 256,
        }
    }

    fn group(self) -> u32 {
        match self {
            Area::Data => IG_DATA,
            Area::M => IG_M,
            Area::I => IG_I,
            Area::Q => IG_Q,
        }
    }
}

/// The area an index group addresses, and whether it addresses bits: the groups 0x4021, 0xF021 and
/// 0xF031 reach the bytes of %M, %I and %Q bit by bit, bit b being bit b % 8 of byte b / 8.
fn area(ig: u32) -> Option<(Area, bool)> {
    Some(match ig {
        IG_DATA => (Area::Data, false),
        IG_M => (Area::M, false),
        IG_M_BITS => (Area::M, true),
        IG_I => (Area::I, false),
        IG_I_BITS => (Area::I, true),
        IG_Q => (Area::Q, false),
        IG_Q_BITS => (Area::Q, true),
        _ => return None,
    })
}

/// The groups a PLC runtime serves for reading. A write to any of them is refused with 0x704.
fn serves(ig: u32) -> bool {
    area(ig).is_some()
        || matches!(ig, IG_SYM_VERSION | IG_SYM_UPLOAD | IG_SYM_UPLOADINFO | IG_SYM_DT_UPLOAD | IG_SYM_UPLOADINFO2
            | IG_DEVICE_DATA)
}

#[derive(Debug, Clone)]
pub struct Profile {
    pub name: &'static str,
    pub title: &'static str,
    pub netid: [u8; 6],
    /// TwinCAT 3: 48-byte upload info, entries with a type GUID, function blocks with a method table.
    pub tc3: bool,
    /// The AMS ports of the PLC runtimes; the system service on 10000 is always there too.
    pub runtimes: &'static [u16],
    pub pack: usize,
    pub pointer: usize,
    /// ReadDeviceInfo of a PLC runtime and of the system service: major, minor, build, name.
    pub plc_device: (u8, u8, u16, &'static str),
    pub system_device: (u8, u8, u16, &'static str),
    /// `Constants.bMulticoreSupport` and `Constants.nRegisterSize` (TwinCAT 3 only).
    pub multicore: bool,
    pub register_size: u16,
}

pub fn profile(name: &str) -> anyhow::Result<Profile> {
    Ok(match name {
        "tc3-ipc" => Profile {
            name: "tc3-ipc",
            title: "TwinCAT 3.1.4024.56 XAR (TC1000 ADS, TC1200 PLC) on an x64 IPC such as a C6015",
            netid: [192, 168, 100, 10, 1, 1],
            tc3: true,
            runtimes: &[851, 852],
            pack: 8,
            pointer: 8,
            plc_device: (3, 1, 4024, "Plc30 App"),
            // Unverified: the system service's device name.
            system_device: (3, 1, 4024, "TwinCAT System"),
            multicore: true,
            register_size: 64,
        },
        "tc3-cx8190" => Profile {
            name: "tc3-cx8190",
            title: "TwinCAT 3.1.4024 on a CX8190 (ARM Cortex-A9, one core), as in examples/in-process-ads-s3",
            netid: [5, 80, 201, 232, 1, 1],
            tc3: true,
            runtimes: &[851],
            pack: 8,
            pointer: 4,
            plc_device: (3, 1, 4024, "Plc30 App"),
            system_device: (3, 1, 4024, "TwinCAT System"),
            multicore: false,
            register_size: 32,
        },
        "tc2-pc" => Profile {
            name: "tc2-pc",
            title: "TwinCAT 2.11 R3 (TS1200 PLC) on an x86 PC",
            netid: [192, 168, 100, 20, 1, 1],
            tc3: false,
            runtimes: &[801],
            pack: 1,
            pointer: 4,
            // Unverified: both device names.
            plc_device: (2, 11, 2300, "TCatPlcCtrl"),
            system_device: (2, 11, 2300, "TwinCAT System"),
            multicore: false,
            register_size: 32,
        },
        other => bail!("unknown ads profile {other:?}; known: {}", PROFILES.join(", ")),
    })
}

/// An elementary type. `Dt` and `Tod` are DATE_AND_TIME and TIME_OF_DAY declared with the IEC short
/// names, which changes only the type name a symbol entry reports.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Elem {
    Bool,
    Byte,
    Word,
    Dword,
    Sint,
    Usint,
    Int,
    Uint,
    Dint,
    Udint,
    Lint,
    Ulint,
    Lword,
    Real,
    Lreal,
    Time,
    Ltime,
    Date,
    DateAndTime,
    Dt,
    TimeOfDay,
    Tod,
    Otcid,
}

impl Elem {
    /// Type name, size, ADS data type (ADST_*) and the id in its type GUID. TwinCAT 3 reports variables
    /// declared DT and TOD with the long names: SFC decodes only those (DataType.kt:39-69), and the
    /// CX8190 example documents its DT channel decoded as a date (in-process-ads-s3.json:49-52).
    fn info(self) -> (&'static str, usize, u32, u64) {
        use Elem::*;
        match self {
            Bool => ("BOOL", 1, 33, 0x30),
            Byte => ("BYTE", 1, 17, 0x01),
            Word => ("WORD", 2, 18, 0x02),
            Dword => ("DWORD", 4, 19, 0x03),
            Sint => ("SINT", 1, 16, 0x04),
            Usint => ("USINT", 1, 17, 0x05),
            Int => ("INT", 2, 2, 0x06),
            Uint => ("UINT", 2, 18, 0x07),
            Dint => ("DINT", 4, 3, 0x08),
            Udint => ("UDINT", 4, 19, 0x09),
            Lint => ("LINT", 8, 20, 0x0A),
            Ulint => ("ULINT", 8, 21, 0x0B),
            Lword => ("LWORD", 8, 21, 0x0C),
            Real => ("REAL", 4, 4, 0x0D),
            Lreal => ("LREAL", 8, 5, 0x0E),
            Time => ("TIME", 4, 19, 0x11),
            Ltime => ("LTIME", 8, 21, 0x12),
            Date => ("DATE", 4, 19, 0x13),
            DateAndTime | Dt => ("DATE_AND_TIME", 4, 19, 0x14),
            TimeOfDay | Tod => ("TIME_OF_DAY", 4, 19, 0x16),
            Otcid => ("OTCID", 4, 19, 0x18),
        }
    }

    /// With `alias`, the short names DT and TOD, which SFC cannot decode (it reports raw bytes).
    fn name(self, alias: bool) -> &'static str {
        match self {
            Elem::Dt if alias => "DT",
            Elem::Tod if alias => "TOD",
            _ => self.info().0,
        }
    }

    fn guid(self, alias: bool) -> u64 {
        match self {
            Elem::Dt if alias => 0x15,
            Elem::Tod if alias => 0x17,
            _ => self.info().3,
        }
    }

    fn size(self) -> usize {
        self.info().1
    }

    fn adst(self) -> u32 {
        self.info().2
    }

    fn signed(self) -> bool {
        matches!(self, Elem::Sint | Elem::Int | Elem::Dint | Elem::Lint)
    }

    /// TwinCAT 2 has no 64-bit integers and no LTIME.
    fn on_tc2(self) -> bool {
        !matches!(self, Elem::Lint | Elem::Ulint | Elem::Lword | Elem::Ltime)
    }
}

#[derive(Debug, Clone)]
enum Ty {
    E(Elem),
    /// STRING(n): n characters and a NUL.
    Str(usize),
    /// WSTRING(n): n UTF-16 code units and a NUL unit.
    WStr(usize),
    /// Bounds per dimension; elements are stored row-major.
    Array(Vec<(i32, i32)>, Box<Ty>),
    Struct(&'static str, Vec<(&'static str, Ty)>),
    Enum(&'static str, Elem),
    Pointer(Box<Ty>),
}

/// How a profile lays out memory and names types.
#[derive(Debug, Clone, Copy)]
struct Layout {
    pack: usize,
    pointer: usize,
    /// Report DT and TOD declarations with the short type names.
    alias: bool,
}

impl Ty {
    fn size(&self, l: &Layout) -> usize {
        match self {
            Ty::E(e) | Ty::Enum(_, e) => e.size(),
            Ty::Str(n) => n + 1,
            Ty::WStr(n) => 2 * (n + 1),
            Ty::Array(dims, el) => elements(dims) * el.size(l),
            Ty::Struct(_, members) => struct_layout(members, l).1,
            Ty::Pointer(_) => l.pointer,
        }
    }

    /// Strings and BOOL align to 1, WSTRING to 2, everything else to min(size, pack), structs to their
    /// most aligned member.
    fn align(&self, l: &Layout) -> usize {
        match self {
            Ty::E(e) | Ty::Enum(_, e) => e.size().min(l.pack),
            Ty::Str(_) => 1,
            Ty::WStr(_) => 2.min(l.pack),
            Ty::Array(_, el) => el.align(l),
            Ty::Struct(_, members) => struct_layout(members, l).2,
            Ty::Pointer(_) => l.pointer.min(l.pack),
        }
    }

    /// The TwinCAT spelling: `ARRAY [0..1,0..2] OF BYTE` (no space after the comma), `STRING(80)`.
    fn name(&self, l: &Layout) -> String {
        match self {
            Ty::E(e) => e.name(l.alias).to_string(),
            Ty::Str(n) => format!("STRING({n})"),
            Ty::WStr(n) => format!("WSTRING({n})"),
            Ty::Array(dims, el) => {
                let dims: Vec<String> = dims.iter().map(|(lo, hi)| format!("{lo}..{hi}")).collect();
                format!("ARRAY [{}] OF {}", dims.join(","), el.name(l))
            }
            Ty::Struct(name, _) | Ty::Enum(name, _) => name.to_string(),
            Ty::Pointer(to) => format!("POINTER TO {}", to.name(l)),
        }
    }

    /// An enum reports its base type and an array its element type.
    fn adst(&self, l: &Layout) -> u32 {
        match self {
            Ty::E(e) | Ty::Enum(_, e) => e.adst(),
            Ty::Str(_) => 30,
            Ty::WStr(_) => 31,
            Ty::Array(_, el) => el.adst(l),
            Ty::Struct(..) => 65,
            // A pointer reports the unsigned integer of its size.
            Ty::Pointer(_) => {
                if l.pointer == 8 {
                    21
                } else {
                    19
                }
            }
        }
    }

    fn on_tc2(&self) -> bool {
        match self {
            Ty::E(e) => e.on_tc2(),
            Ty::WStr(_) => false,
            Ty::Array(_, el) => el.on_tc2(),
            _ => true,
        }
    }
}

fn elements(dims: &[(i32, i32)]) -> usize {
    dims.iter().map(|(lo, hi)| (hi - lo + 1).max(0) as usize).product()
}

/// Member offsets, size and alignment of a struct: declaration order, each member at its alignment,
/// the size rounded up to the struct's alignment. Pack 1 (TwinCAT 2) therefore packs every byte.
fn struct_layout(members: &[(&'static str, Ty)], l: &Layout) -> (Vec<usize>, usize, usize) {
    let mut offsets = Vec::with_capacity(members.len());
    let (mut end, mut align) = (0usize, 1usize);
    for (_, ty) in members {
        let a = ty.align(l);
        end = end.next_multiple_of(a);
        offsets.push(end);
        end += ty.size(l);
        align = align.max(a);
    }
    (offsets, end.next_multiple_of(align), align)
}

/// A value in PLC memory, encoded by the type it is stored as.
#[derive(Debug, Clone)]
enum Val {
    Bool(bool),
    /// Any integer, enum or pointer, two's complement, cut to the type's size.
    Int(i64),
    /// REAL is stored as f32, LREAL as f64.
    Real(f64),
    /// STRING in CP1252, WSTRING in UTF-16LE, cut to the declared length.
    Text(String),
    /// Exact bytes, so a NaN keeps its bit pattern.
    Raw(Vec<u8>),
    /// Array elements, row-major.
    List(Vec<Val>),
    /// Struct members by name; a member without a value stays zero.
    Fields(Vec<(&'static str, Val)>),
}

fn copy_cut(out: &mut [u8], bytes: &[u8]) {
    let n = out.len().min(bytes.len());
    out[..n].copy_from_slice(&bytes[..n]);
}

/// Writes `v` into `out`, which is zeroed and exactly the size of `ty`.
fn encode(ty: &Ty, v: &Val, l: &Layout, out: &mut [u8]) {
    match (ty, v) {
        (_, Val::Raw(bytes)) => copy_cut(out, bytes),
        (Ty::E(Elem::Real), Val::Real(x)) => copy_cut(out, &(*x as f32).to_le_bytes()),
        (Ty::E(Elem::Lreal), Val::Real(x)) => copy_cut(out, &x.to_le_bytes()),
        (Ty::E(_), Val::Bool(b)) => copy_cut(out, &[u8::from(*b)]),
        (Ty::E(_) | Ty::Enum(..) | Ty::Pointer(_), Val::Int(i)) => copy_cut(out, &i.to_le_bytes()),
        (Ty::Str(_), Val::Text(s)) => {
            // CP1252 agrees with Latin-1 on every character the map uses; others become '?'.
            let bytes: Vec<u8> = s.chars().map(|c| u8::try_from(u32::from(c)).unwrap_or(b'?')).collect();
            let n = out.len().saturating_sub(1);
            copy_cut(&mut out[..n], &bytes);
        }
        (Ty::WStr(_), Val::Text(s)) => {
            let bytes: Vec<u8> = s.encode_utf16().flat_map(u16::to_le_bytes).collect();
            let n = out.len().saturating_sub(2);
            copy_cut(&mut out[..n], &bytes);
        }
        (Ty::Array(_, el), Val::List(items)) => {
            for (item, slot) in items.iter().zip(out.chunks_mut(el.size(l).max(1))) {
                encode(el, item, l, slot);
            }
        }
        (Ty::Struct(_, members), Val::Fields(fields)) => {
            let (offsets, ..) = struct_layout(members, l);
            for ((name, mty), at) in members.iter().zip(offsets) {
                let Some((_, fv)) = fields.iter().find(|(n, _)| n == name) else { continue };
                if let Some(slot) = out.get_mut(at..at + mty.size(l)) {
                    encode(mty, fv, l, slot);
                }
            }
        }
        _ => debug_assert!(false, "{v:?} cannot be stored as {ty:?}"),
    }
}

/// The REAL signals of core::signal.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Sig {
    Sine,
    Cosine,
    Tangent,
    Cotangent,
    Exp,
    Quadratic,
    Sawtooth,
    Triangle,
    Square,
    Damped,
    Noise,
    RandomWalk,
}

impl Sig {
    fn of(self, v: &Values) -> f64 {
        match self {
            Sig::Sine => v.sine,
            Sig::Cosine => v.cosine,
            Sig::Tangent => v.tangent,
            Sig::Cotangent => v.cotangent,
            Sig::Exp => v.exp,
            Sig::Quadratic => v.quadratic,
            Sig::Sawtooth => v.sawtooth,
            Sig::Triangle => v.triangle,
            Sig::Square => v.square,
            Sig::Damped => v.damped,
            Sig::Noise => v.noise,
            Sig::RandomWalk => v.randomwalk,
        }
    }

    fn name(self) -> &'static str {
        match self {
            Sig::Sine => "sine",
            Sig::Cosine => "cosine",
            Sig::Tangent => "tangent",
            Sig::Cotangent => "cotangent",
            Sig::Exp => "exp",
            Sig::Quadratic => "quadratic",
            Sig::Sawtooth => "sawtooth",
            Sig::Triangle => "triangle",
            Sig::Square => "square",
            Sig::Damped => "damped",
            Sig::Noise => "noise",
            Sig::RandomWalk => "randomwalk",
        }
    }
}

/// The fixed part of a PLC task's `_TaskInfo`.
#[derive(Debug)]
struct Task {
    obj_id: u32,
    priority: u16,
    ads_port: u16,
    name: &'static str,
}

static TASK_851: Task = Task { obj_id: 0x0201_0010, priority: 20, ads_port: 350, name: "PlcTask" };
static TASK_852: Task = Task { obj_id: 0x0201_0020, priority: 21, ads_port: 351, name: "PlcTask2" };

/// What the scan writes into a dynamic symbol.
#[derive(Debug, Clone, Copy)]
enum Live {
    /// The scan counter k: ULINT on TwinCAT 3, UDINT (k mod 2^32) on TwinCAT 2.
    Scan,
    /// Simulated seconds, LREAL.
    T,
    /// REAL or LREAL, by the symbol's type.
    Signal(Sig),
    /// round(100·sine), saturated to INT.
    SineInt,
    Blink1Hz,
    Blink5Hz,
    /// An incremental encoder: 4·k mod 2^32.
    Encoder,
    Ton,
    Ctu,
    TonQ,
    TonEt,
    CtuCv,
    CtuQ,
    /// `ARRAY [1..1] OF PLC.PlcTaskSystemInfo`.
    TaskInfo(&'static Task),
    /// TwinCAT 2 `SystemTaskInfoArr`: task 1 runs, tasks 2-4 are empty.
    Tc2Tasks,
    /// floor(2t), the parts of line 2.
    PartCount,
    /// 20 + 5·sin(2π·0.05·t), line 2's temperature.
    Temperature,
}

impl Live {
    fn describe(self) -> String {
        match self {
            Live::Scan => "scan counter k".into(),
            Live::T => "t = k·cycle_ms/1000 s".into(),
            Live::Signal(s) => s.name().into(),
            Live::SineInt => "sine_int = round(100·sine)".into(),
            Live::Blink1Hz => "blink_1hz".into(),
            Live::Blink5Hz => "blink_5hz".into(),
            Live::Encoder => "4·k mod 2^32".into(),
            Live::Ton => "TON(IN := frac(t/10) < 0.7, PT := T#5S)".into(),
            Live::Ctu => "CTU(CU := blink_1hz, RESET := Q of the previous scan, PV := 10)".into(),
            Live::TonQ => "fbTon.Q".into(),
            Live::TonEt => "fbTon.ET".into(),
            Live::CtuCv => "fbCtu.CV".into(),
            Live::CtuQ => "fbCtu.Q".into(),
            Live::TaskInfo(task) => format!("task {}: CycleCount = k, DcTaskTime = PLC clock", task.name),
            Live::Tc2Tasks => "task PlcTask: cycleCount = k".into(),
            Live::PartCount => "floor(2t)".into(),
            Live::Temperature => "20 + 5·sin(2π·0.05·t)".into(),
        }
    }
}

#[derive(Debug, Clone)]
enum Init {
    /// Written when the image is built.
    Static(Val),
    /// Rewritten by every scan.
    Live(Live),
}

#[derive(Debug, Clone)]
struct Symbol {
    name: String,
    ig: u32,
    io: u32,
    size: usize,
    ty: Ty,
    flags: u32,
    comment: &'static str,
    init: Init,
}

/// One PLC runtime: its AMS port, its symbols and the replies to the symbol upload.
struct Runtime {
    port: u16,
    symbols: Vec<Symbol>,
    /// The 0xF00B data: every entry, concatenated.
    upload: Vec<u8>,
    /// The 0xF00F data.
    info: Vec<u8>,
}

/// A variable of a GVL or program, before `block` lays it out.
struct Var {
    name: &'static str,
    ty: Ty,
    init: Init,
    comment: &'static str,
}

fn var(name: &'static str, ty: Ty, init: Init, comment: &'static str) -> Var {
    Var { name, ty, init, comment }
}

fn int(v: i64) -> Init {
    Init::Static(Val::Int(v))
}

fn real(v: f64) -> Init {
    Init::Static(Val::Real(v))
}

fn boolean(v: bool) -> Init {
    Init::Static(Val::Bool(v))
}

fn text(v: &str) -> Init {
    Init::Static(Val::Text(v.to_string()))
}

fn list<T: Copy>(items: &[T], f: impl Fn(T) -> Val) -> Init {
    Init::Static(Val::List(items.iter().map(|x| f(*x)).collect()))
}

fn live(l: Live) -> Init {
    Init::Live(l)
}

fn array(dims: &[(i32, i32)], el: Ty) -> Ty {
    Ty::Array(dims.to_vec(), Box::new(el))
}

/// Seconds since 1970-01-01 UTC, the encoding of DATE and DATE_AND_TIME.
fn secs(year: i32, month: u32, day: u32, hour: u32, minute: u32, second: u32) -> i64 {
    unix_ms(year, month, day, hour, minute, second, 0) / 1000
}

fn st_motor() -> Ty {
    use Elem::*;
    Ty::Struct("ST_Motor", vec![("bEnabled", Ty::E(Bool)), ("nSpeedRpm", Ty::E(Int)), ("fCurrent", Ty::E(Real)),
                                ("sName", Ty::Str(15))])
}

fn version() -> Ty {
    let u = || Ty::E(Elem::Uint);
    Ty::Struct("VERSION", vec![("uiMajor", u()), ("uiMinor", u()), ("uiServicePack", u()), ("uiPatch", u())])
}

fn version_of(v: [i64; 4]) -> Init {
    Init::Static(Val::Fields(vec![("uiMajor", Val::Int(v[0])), ("uiMinor", Val::Int(v[1])),
                                  ("uiServicePack", Val::Int(v[2])), ("uiPatch", Val::Int(v[3]))]))
}

fn lib_version() -> Ty {
    let u = || Ty::E(Elem::Uint);
    Ty::Struct("ST_LibVersion", vec![("iMajor", u()), ("iMinor", u()), ("iBuild", u()), ("iRevision", u()),
                                     ("nFlags", Ty::E(Elem::Dword)), ("sVersion", Ty::Str(23))])
}

fn lib_version_of(v: [i64; 4]) -> Init {
    let text = format!("{}.{}.{}.{}", v[0], v[1], v[2], v[3]);
    Init::Static(Val::Fields(vec![("iMajor", Val::Int(v[0])), ("iMinor", Val::Int(v[1])), ("iBuild", Val::Int(v[2])),
                                  ("iRevision", Val::Int(v[3])), ("sVersion", Val::Text(text))]))
}

/// PLC.PlcAppSystemInfo, 192 bytes, with the offsets SFC reads (PlcAppSystemInfo.kt:152-171).
fn app_info() -> Ty {
    use Elem::*;
    Ty::Struct("PLC.PlcAppSystemInfo", vec![
        ("ObjId", Ty::E(Otcid)), ("TaskCnt", Ty::E(Udint)), ("OnlineChangeCnt", Ty::E(Udint)), ("Flags", Ty::E(Dword)),
        ("AdsPort", Ty::E(Uint)), ("BootDataLoaded", Ty::E(Bool)), ("OldBootData", Ty::E(Bool)),
        ("AppTimestamp", Ty::E(DateAndTime)), ("KeepOutputsOnBP", Ty::E(Bool)), ("ShutdownInProgress", Ty::E(Bool)),
        ("LicensesPending", Ty::E(Bool)), ("BSODOccured", Ty::E(Bool)), ("LoggedIn", Ty::E(Bool)),
        ("reserved", array(&[(29, 63)], Ty::E(Byte))), ("AppName", Ty::Str(63)), ("ProjectName", Ty::Str(63)),
    ])
}

/// PLC.PlcTaskSystemInfo, 128 bytes, with the offsets SFC reads (PlcTaskSystemInfo.kt:110-124).
fn task_info() -> Ty {
    use Elem::*;
    Ty::Struct("PLC.PlcTaskSystemInfo", vec![
        ("ObjId", Ty::E(Otcid)), ("CycleTime", Ty::E(Udint)), ("Priority", Ty::E(Uint)), ("AdsPort", Ty::E(Uint)),
        ("CycleCount", Ty::E(Udint)), ("DcTaskTime", Ty::E(Lint)), ("LastExecTime", Ty::E(Udint)),
        ("FirstCycle", Ty::E(Bool)), ("CycleTimeExceeded", Ty::E(Bool)), ("InCallAfterOutputUpdate", Ty::E(Bool)),
        ("RTViolation", Ty::E(Bool)), ("reserved", array(&[(32, 63)], Ty::E(Byte))), ("TaskName", Ty::Str(63)),
    ])
}

/// A TwinCAT 3 function block starts with a pointer to its method table; a TwinCAT 2 one does not.
fn function_block(p: &Profile, name: &'static str, members: Vec<(&'static str, Ty)>) -> Ty {
    let mut all = if p.tc3 { vec![("__VFTABLE", Ty::Pointer(Box::new(Ty::E(Elem::Byte))))] } else { vec![] };
    all.extend(members);
    Ty::Struct(name, all)
}

fn ton(p: &Profile) -> Ty {
    use Elem::*;
    function_block(p, "TON", vec![("IN", Ty::E(Bool)), ("PT", Ty::E(Time)), ("Q", Ty::E(Bool)), ("ET", Ty::E(Time)),
                                  ("M", Ty::E(Bool)), ("StartTime", Ty::E(Time))])
}

fn ctu(p: &Profile) -> Ty {
    use Elem::*;
    function_block(p, "CTU", vec![("CU", Ty::E(Bool)), ("RESET", Ty::E(Bool)), ("PV", Ty::E(Word)), ("Q", Ty::E(Bool)),
                                  ("CV", Ty::E(Word)), ("M", Ty::E(Bool))])
}

/// Unverified: TwinCAT 2 SYSTEMINFOTYPE as TcSystem.lib declares it (40 bytes at pack 1).
fn tc2_system_info() -> Ty {
    use Elem::*;
    Ty::Struct("SYSTEMINFOTYPE", vec![
        ("runTimeNo", Ty::E(Byte)), ("projectName", Ty::Str(32)), ("numberOfTasks", Ty::E(Byte)),
        ("onlineChangeCount", Ty::E(Uint)), ("bootDataFlags", Ty::E(Byte)), ("systemStateFlags", Ty::E(Word)),
    ])
}

/// Unverified: TwinCAT 2 SYSTEMTASKINFOTYPE as TcSystem.lib declares it (33 bytes at pack 1).
fn tc2_task_info() -> Ty {
    use Elem::*;
    Ty::Struct("SYSTEMTASKINFOTYPE", vec![
        ("active", Ty::E(Bool)), ("taskName", Ty::Str(16)), ("firstCycle", Ty::E(Bool)),
        ("cycleTimeExceeded", Ty::E(Bool)), ("cycleTime", Ty::E(Udint)), ("lastExecTime", Ty::E(Udint)),
        ("priority", Ty::E(Byte)), ("cycleCount", Ty::E(Udint)),
    ])
}

/// One exact value per data type; the comment is the tag's logical id.
fn gvl_static() -> Vec<Var> {
    use Elem::*;
    let dt = secs(2024, 3, 15, 12, 34, 56);
    let tod = 45_296_789; // TOD#12:34:56.789, ms since midnight
    let motor = Val::Fields(vec![("bEnabled", Val::Bool(true)), ("nSpeedRpm", Val::Int(1450)),
                                 ("fCurrent", Val::Real(3.75)), ("sName", Val::Text("M1".into()))]);
    vec![
        var("bBoolTrue", Ty::E(Bool), boolean(true), "bool_true"),
        var("bBoolFalse", Ty::E(Bool), boolean(false), "bool_false"),
        var("nByte", Ty::E(Byte), int(0xA5), "byte"),
        var("nSint", Ty::E(Sint), int(-100), "sint"),
        var("nUsint", Ty::E(Usint), int(200), "usint"),
        var("nInt", Ty::E(Int), int(-12345), "int"),
        var("nUint", Ty::E(Uint), int(54321), "uint"),
        var("nWord", Ty::E(Word), int(0xD431), "word"),
        var("nDint", Ty::E(Dint), int(-1_234_567_890), "dint"),
        var("nUdint", Ty::E(Udint), int(3_000_000_000), "udint"),
        var("nDword", Ty::E(Dword), int(0xB2D0_5E00), "dword"),
        var("nLint", Ty::E(Lint), int(-1_234_567_890_123), "lint"),
        var("nUlint", Ty::E(Ulint), int(12_345_678_901_234), "ulint"),
        var("nLword", Ty::E(Lword), int(0x0123_4567_89AB_CDEF), "lword"),
        var("fReal", Ty::E(Real), real(12345.5), "real"),
        var("fLreal", Ty::E(Lreal), real(-98765.4375), "lreal"),
        var("sString", Ty::Str(80), text("SFC-SIM"), "string"),
        var("tTime", Ty::E(Time), int(1234), "time"),
        var("tLtime", Ty::E(Ltime), int(1_234_567_890), "ltime"),
        var("dDate", Ty::E(Date), int(secs(2024, 3, 15, 0, 0, 0)), "date"),
        var("dtDateAndTime", Ty::E(DateAndTime), int(dt), "date_and_time"),
        var("dtDt", Ty::E(Dt), int(dt), "dt"),
        var("todTimeOfDay", Ty::E(TimeOfDay), int(tod), "time_of_day"),
        var("todTod", Ty::E(Tod), int(tod), "tod"),
        var("wsWString", Ty::WStr(80), text("SFC-SIM-W"), "wstring"),
        var("aInt", array(&[(0, 4)], Ty::E(Int)), list(&[-200, -100, 0, 100, 200], Val::Int), "array_int"),
        var("aReal", array(&[(1, 3)], Ty::E(Real)), list(&[1.5, -2.25, 3.125], Val::Real), "array_real"),
        var("aByte2D", array(&[(0, 1), (0, 2)], Ty::E(Byte)), list(&[1, 2, 3, 4, 5, 6], Val::Int), "array_byte_2d"),
        var("aString", array(&[(0, 2)], Ty::Str(10)), list(&["RED", "GREEN", "BLUE"], |s| Val::Text(s.into())),
            "array_string"),
        var("aBool", array(&[(0, 3)], Ty::E(Bool)), list(&[true, false, true, true], Val::Bool), "array_bool"),
        var("stMotor", st_motor(), Init::Static(motor), "struct"),
        // E_MachineState: Idle 0, Starting 1, Running 2, Stopping 3, Fault 4.
        var("eState", Ty::Enum("E_MachineState", Int), int(2), "enum"),
    ]
}

/// The signals; the comment is the signal id.
fn gvl_dynamic(p: &Profile) -> Vec<Var> {
    use Elem::*;
    let real = |name, sig: Sig| var(name, Ty::E(Real), live(Live::Signal(sig)), sig.name());
    vec![
        var("nScan", Ty::E(if p.tc3 { Ulint } else { Udint }), live(Live::Scan), "scan"),
        var("fT", Ty::E(Lreal), live(Live::T), "t"),
        real("fSine", Sig::Sine),
        real("fCosine", Sig::Cosine),
        real("fTangent", Sig::Tangent),
        real("fCotangent", Sig::Cotangent),
        real("fExp", Sig::Exp),
        real("fQuadratic", Sig::Quadratic),
        real("fSawtooth", Sig::Sawtooth),
        real("fTriangle", Sig::Triangle),
        real("fSquare", Sig::Square),
        real("fDamped", Sig::Damped),
        real("fNoise", Sig::Noise),
        real("fRandomWalk", Sig::RandomWalk),
        var("fSine64", Ty::E(Lreal), live(Live::Signal(Sig::Sine)), "sine64"),
        var("nSineInt", Ty::E(Int), live(Live::SineInt), "sine_int"),
        var("bBlink1Hz", Ty::E(Bool), live(Live::Blink1Hz), "blink_1hz"),
        var("bBlink5Hz", Ty::E(Bool), live(Live::Blink5Hz), "blink_5hz"),
    ]
}

/// Real-PLC values that SFC decodes wrongly today, for defect cases.
fn gvl_edge(p: &Profile) -> Vec<Var> {
    use Elem::*;
    let y2040 = secs(2040, 1, 1, 0, 0, 0);
    let pointer = if p.pointer == 8 { 0x0000_7FF6_1234_5678 } else { 0x1234_5678 };
    vec![
        var("aIntNeg", array(&[(-2, 2)], Ty::E(Int)), list(&[10, 20, 30, 40, 50], Val::Int), ""),
        var("sCp1252", Ty::Str(20), text("Grüße"), ""),
        var("wsCjk", Ty::WStr(20), text("AB一CD"), ""),
        var("dtY2040", Ty::E(DateAndTime), int(y2040), ""),
        var("dY2040", Ty::E(Date), int(y2040), ""),
        var("tLong", Ty::E(Time), int(30 * 86_400_000), ""), // T#30D
        var("nUlintMax", Ty::E(Ulint), int(-1), ""),       // 2^64 - 1
        var("fNaN", Ty::E(Real), Init::Static(Val::Raw(vec![0x00, 0x00, 0xC0, 0x7F])), ""),
        var("pInt", Ty::Pointer(Box::new(Ty::E(Int))), int(pointer), ""),
    ]
}

/// examples/in-process-ads-s3/main.tmc, plus a TON and a CTU that run.
fn main_program(p: &Profile) -> Vec<Var> {
    use Elem::*;
    let bytes = |v: &[i64]| list(v, Val::Int);
    vec![
        var("varBOOL", Ty::E(Bool), boolean(true), ""),
        var("varBYTE", Ty::E(Byte), int(1), ""),
        var("varDATE", Ty::E(Date), int(secs(2023, 12, 8, 0, 0, 0)), ""),
        var("varDATE_AND_TIME", Ty::E(DateAndTime), int(secs(2023, 12, 8, 18, 14, 0)), ""),
        var("varDINT", Ty::E(Dint), int(2), ""),
        var("varDT", Ty::E(Dt), int(secs(2023, 12, 8, 18, 17, 0)), ""),
        var("varDWORD", Ty::E(Dword), int(3), ""),
        var("varINT", Ty::E(Int), int(4), ""),
        var("varLINT", Ty::E(Lint), int(5), ""),
        var("varLREAL", Ty::E(Lreal), real(6.0), ""),
        var("varLTIME", Ty::E(Ltime), int(100), ""),
        var("varREAL", Ty::E(Real), real(7.0), ""),
        var("varSINT", Ty::E(Sint), int(8), ""),
        var("varSTRING", Ty::Str(80), text("Hello"), ""),
        var("varTIME", Ty::E(Time), int(20), ""),
        var("varTIME_OF_DAY", Ty::E(TimeOfDay), int(66_600_000), ""),
        var("varTOD", Ty::E(Tod), int(66_660_000), ""),
        var("varUDINT", Ty::E(Udint), int(9), ""),
        var("varUINT", Ty::E(Uint), int(10), ""),
        var("varULINT", Ty::E(Ulint), int(11), ""),
        var("varUSINT", Ty::E(Usint), int(12), ""),
        var("varWORD", Ty::E(Word), int(13), ""),
        var("varWSTRING", Ty::WStr(80), text("Hello world WS"), ""),
        var("varBYTEARRAY1", array(&[(0, 4)], Ty::E(Byte)), bytes(&[0, 1, 2, 3, 4]), ""),
        var("varBYTEARRAY2", array(&[(0, 4), (0, 2)], Ty::E(Byte)),
            bytes(&[0, 1, 2, 10, 11, 12, 20, 21, 22, 30, 31, 32, 40, 41, 42]), ""),
        var("varBYTEARRAY3", array(&[(0, 1), (0, 2), (0, 3)], Ty::E(Byte)),
            bytes(&[0, 1, 2, 3, 10, 11, 12, 13, 20, 21, 22, 23, 100, 101, 102, 103, 110, 111, 112, 113, 120, 121, 122,
                    123]), ""),
        var("fbTon", ton(p), live(Live::Ton), ""),
        var("fbCtu", ctu(p), live(Live::Ctu), ""),
        var("bTonQ", Ty::E(Bool), live(Live::TonQ), ""),
        var("tTonEt", Ty::E(Time), live(Live::TonEt), ""),
        var("nCtuCv", Ty::E(Word), live(Live::CtuCv), ""),
        var("bCtuQ", Ty::E(Bool), live(Live::CtuQ), ""),
    ]
}

fn constants(p: &Profile) -> Vec<Var> {
    use Elem::*;
    vec![
        var("bFPUSupport", Ty::E(Bool), boolean(true), ""),
        var("bLittleEndian", Ty::E(Bool), boolean(true), ""),
        var("bMulticoreSupport", Ty::E(Bool), boolean(p.multicore), ""),
        var("bSimulationMode", Ty::E(Bool), boolean(false), ""),
        var("CompilerVersion", version(), version_of([3, 5, 13, 30]), ""),
        var("nPackMode", Ty::E(Uint), int(p.pack as i64), ""),
        var("nRegisterSize", Ty::E(Word), int(p.register_size.into()), ""),
        var("RuntimeVersion", version(), version_of([3, 1, 4024, 56]), ""),
        var("RuntimeVersionNumeric", Ty::E(Dword), int(0x0301_0FB8), ""), // 3.1.4024
    ]
}

fn global_version() -> Vec<Var> {
    vec![
        var("stLibVersion_Tc2_Standard", lib_version(), lib_version_of([3, 3, 3, 0]), ""),
        var("stLibVersion_Tc2_System", lib_version(), lib_version_of([3, 4, 26, 0]), ""),
        var("stLibVersion_Tc3_Module", lib_version(), lib_version_of([3, 3, 21, 0]), ""),
    ]
}

/// TwinCAT_SystemInfoVarList of the runtime on `port` (851 or 852).
fn system_info(port: u16) -> Vec<Var> {
    let (app, task, oid) = if port == 852 {
        (0x0850_2020, &TASK_852, "_TaskOid_PlcTask2")
    } else {
        (0x0850_2000, &TASK_851, "_TaskOid_PlcTask")
    };
    let app_value = Val::Fields(vec![
        ("ObjId", Val::Int(app)),
        ("TaskCnt", Val::Int(1)),
        ("AdsPort", Val::Int(port.into())),
        ("BootDataLoaded", Val::Bool(true)),
        ("AppTimestamp", Val::Int(secs(2024, 3, 15, 8, 0, 0))),
        ("LoggedIn", Val::Bool(true)),
        ("AppName", Val::Text(format!("Port_{port}"))),
        ("ProjectName", Val::Text("OmniPlcSim".into())),
    ]);
    let mut vars = vec![
        var("_AppInfo", app_info(), Init::Static(app_value), ""),
        var("_TaskInfo", array(&[(1, 1)], task_info()), live(Live::TaskInfo(task)), ""),
        var(oid, Ty::E(Elem::Otcid), int(task.obj_id.into()), ""),
    ];
    if port == 851 {
        vars.push(var("_TaskPouOid_PlcTask", Ty::E(Elem::Otcid), int(0x0850_2010), ""));
    }
    vars
}

/// The second PLC runtime (port 852): a production line.
fn line2() -> Vec<Var> {
    use Elem::*;
    vec![
        var("nPartCount", Ty::E(Udint), live(Live::PartCount), ""),
        var("fTemperature", Ty::E(Real), live(Live::Temperature), ""),
        var("sRecipe", Ty::Str(20), text("RECIPE-2"), ""),
        var("bRunning", Ty::E(Bool), boolean(true), ""),
    ]
}

/// Unverified: the TwinCAT 2 system variables, whose layouts the repository does not show.
fn tc2_system() -> Vec<Var> {
    let info = Val::Fields(vec![("runTimeNo", Val::Int(1)), ("projectName", Val::Text("OmniPlcSim".into())),
                                ("numberOfTasks", Val::Int(1))]);
    vec![
        var("SystemInfo", tc2_system_info(), Init::Static(info), ""),
        var("SystemTaskInfoArr", array(&[(1, 4)], tc2_task_info()), live(Live::Tc2Tasks), ""),
    ]
}

/// TwinCAT 3 entries carry ADSSYMBOLFLAG_TYPEGUID, bit-located ones also ADSSYMBOLFLAG_BITVALUE.
fn entry_flags(p: &Profile, bit: bool) -> u32 {
    (if p.tc3 { 0x0008 } else { 0 }) | (if bit { 0x0002 } else { 0 })
}

/// Lays `vars` out in index group 0x4040 from `base`, in declaration order, and appends them as
/// `<prefix><name>`. TwinCAT 2 lacks the 64-bit integers, LTIME and WSTRING, so those variables do not
/// exist there.
fn block(out: &mut Vec<Symbol>, p: &Profile, l: &Layout, prefix: &str, base: u32, vars: Vec<Var>) {
    let mut at = base as usize;
    for v in vars.into_iter().filter(|v| p.tc3 || v.ty.on_tc2()) {
        at = at.next_multiple_of(v.ty.align(l));
        let size = v.ty.size(l);
        out.push(Symbol {
            name: format!("{prefix}{}", v.name),
            ig: IG_DATA,
            io: at as u32,
            size,
            ty: v.ty,
            flags: entry_flags(p, false),
            comment: v.comment,
            init: v.init,
        });
        at += size;
    }
}

/// GVL_IO: variables at fixed %I, %Q and %M addresses; the comment is the address. Unverified: the
/// addresses count bytes; under CODESYS addressing %IW2 would be bytes 4-5. SFC uses only the group
/// and offset of the entry, so it reads the same either way.
fn located(out: &mut Vec<Symbol>, p: &Profile, prefix: &str) {
    use Elem::*;
    let vars = [
        ("bSensor", IG_I_BITS, 0, Bool, live(Live::Blink1Hz), "%IX0.0"),
        ("nAnalogIn", IG_I, 2, Int, live(Live::SineInt), "%IW2"),
        ("nEncoder", IG_I, 4, Udint, live(Live::Encoder), "%ID4"),
        ("bMotorOn", IG_Q_BITS, 0, Bool, live(Live::Blink1Hz), "%QX0.0"),
        ("nSetpoint", IG_Q, 2, Int, int(1500), "%QW2"),
        ("nStatusWord", IG_M, 0, Word, int(0x00C3), "%MW0"),
    ];
    for (name, ig, io, e, init, comment) in vars {
        let bit = area(ig).is_some_and(|(_, bits)| bits);
        out.push(Symbol { name: format!("{prefix}{name}"), ig, io, size: e.size(), ty: Ty::E(e),
                          flags: entry_flags(p, bit), comment, init });
    }
}

/// The symbols of the runtime on `port`, in upload order.
fn symbols(p: &Profile, l: &Layout, port: u16) -> Vec<Symbol> {
    let mut out = Vec::new();
    // TwinCAT 2 names a global variable `.x`, TwinCAT 3 `<GVL>.x`.
    let gvl = |name: &str| if p.tc3 { format!("{name}.") } else { ".".to_string() };
    if port == 852 {
        block(&mut out, p, l, &gvl("GVL_Line2"), 0x1000, line2());
        block(&mut out, p, l, "TwinCAT_SystemInfoVarList.", 0x4200, system_info(port));
        return out;
    }
    block(&mut out, p, l, &gvl("GVL_Static"), 0x1000, gvl_static());
    block(&mut out, p, l, &gvl("GVL_Dynamic"), 0x2000, gvl_dynamic(p));
    block(&mut out, p, l, &gvl("GVL_Edge"), 0x2800, gvl_edge(p));
    located(&mut out, p, &gvl("GVL_IO"));
    block(&mut out, p, l, "MAIN.", 0x3000, main_program(p));
    if p.tc3 {
        block(&mut out, p, l, "Constants.", 0x4000, constants(p));
        block(&mut out, p, l, "Global_Version.", 0x4100, global_version());
        block(&mut out, p, l, "TwinCAT_SystemInfoVarList.", 0x4200, system_info(port));
    } else {
        block(&mut out, p, l, ".", 0x4000, tc2_system());
    }
    out
}

/// The first 10 bytes of every type GUID; the last 6 hold the type's id, big-endian. The values are
/// synthetic: SFC does not read the GUID, it only skips it by entryLength (GetSymbolsResponse.kt:32).
const GUID_PREFIX: [u8; 10] = [0x95, 0x19, 0x07, 0x18, 0, 0, 0, 0, 0, 0];

/// The 0xF00B table: one AdsSymbolEntry per symbol, each padded to a multiple of 4 bytes, nothing
/// after the last (GetSymbolsResponse.kt:24-27). On TwinCAT 3 every entry ends with its type GUID:
/// elementary types have fixed ids, every other type string is numbered from 0x100 in order of first
/// appearance.
fn upload(symbols: &[Symbol], p: &Profile, l: &Layout) -> Vec<u8> {
    let mut derived: Vec<String> = Vec::new();
    let mut out = Vec::new();
    for s in symbols {
        let ty = s.ty.name(l);
        let start = out.len();
        out.extend_from_slice(&[0; 4]);
        for v in [s.ig, s.io, s.size as u32, s.ty.adst(l), s.flags] {
            out.extend_from_slice(&v.to_le_bytes());
        }
        for len in [s.name.len(), ty.len(), s.comment.len()] {
            out.extend_from_slice(&(len as u16).to_le_bytes());
        }
        for t in [s.name.as_bytes(), ty.as_bytes(), s.comment.as_bytes()] {
            out.extend_from_slice(t);
            out.push(0);
        }
        if p.tc3 {
            let id = match &s.ty {
                Ty::E(e) => e.guid(l.alias),
                _ => {
                    let i = derived.iter().position(|d| *d == ty).unwrap_or_else(|| {
                        derived.push(ty.clone());
                        derived.len() - 1
                    });
                    0x100 + i as u64
                }
            };
            out.extend_from_slice(&GUID_PREFIX);
            out.extend_from_slice(&id.to_be_bytes()[2..]);
        }
        out.resize(start + (out.len() - start).next_multiple_of(4), 0);
        let len = (out.len() - start) as u32;
        out[start..start + 4].copy_from_slice(&len.to_le_bytes());
    }
    out
}

/// The 0xF00F data: AdsSymbolUploadInfo2, 48 bytes on TwinCAT 3 and its first 24 on TwinCAT 2. SFC
/// reads nSymSize at offset 4 (GetSymbolsLengthResponse.kt:21).
fn upload_info(count: usize, size: usize, p: &Profile) -> Vec<u8> {
    let mut out = Vec::with_capacity(48);
    // nSymbols, nSymSize, nDatatypes, nDatatypeSize, nMaxDynSymbols, nUsedDynSymbols
    for v in [count as u32, size as u32, 0, 0, 0, 0] {
        out.extend_from_slice(&v.to_le_bytes());
    }
    if p.tc3 {
        // nInvalidDynSymbols, nEncodingCodePage, nFlags, reserved[3]. Unverified: the code page and the
        // flags; 1252 is the Windows code page TwinCAT strings use.
        for v in [0u32, 1252, 0, 0, 0, 0] {
            out.extend_from_slice(&v.to_le_bytes());
        }
    }
    out
}

/// The TON and CTU of MAIN, in whole milliseconds of scan time so the timer never drifts:
/// `fbTon(IN := frac(t/10) < 0.7, PT := T#5S)` and `fbCtu(CU := blink_1hz, RESET := fbCtu.Q, PV := 10)`.
#[derive(Debug, Default)]
struct Timers {
    ton_in: bool,
    ton_rise_ms: u64,
    ton_start: u32,
    ton_et: u32,
    ton_q: bool,
    ctu_cu: bool,
    ctu_reset: bool,
    ctu_cv: u16,
    ctu_q: bool,
}

const TON_PT_MS: u32 = 5000;
const CTU_PV: u16 = 10;

impl Timers {
    fn step(&mut self, s: &Scan) {
        let ms = s.k.saturating_mul(s.cycle_ms);
        let input = ms % 10_000 < 7_000;
        if input && !self.ton_in {
            self.ton_rise_ms = ms;
            self.ton_start = ms as u32; // TIME() wraps at 2^32 ms
        }
        self.ton_in = input;
        self.ton_et = if input { ms.saturating_sub(self.ton_rise_ms).min(TON_PT_MS.into()) as u32 } else { 0 };
        self.ton_q = input && self.ton_et >= TON_PT_MS;
        // RESET is the previous scan's Q, so CV falls back to 0 one scan after it reaches PV.
        self.ctu_reset = self.ctu_q;
        let cu = s.v.blink_1hz;
        if self.ctu_reset {
            self.ctu_cv = 0;
        } else if cu && !self.ctu_cu {
            self.ctu_cv = self.ctu_cv.saturating_add(1);
        }
        self.ctu_cu = cu;
        self.ctu_q = self.ctu_cv >= CTU_PV;
    }
}

fn live_value(live: Live, s: &Scan, fb: &Timers) -> Val {
    let v = &s.v;
    let ms = s.k.saturating_mul(s.cycle_ms);
    let u = |x: u64| Val::Int(x as i64);
    match live {
        Live::Scan => u(s.k),
        Live::T => Val::Real(s.t),
        Live::Signal(sig) => Val::Real(sig.of(v)),
        Live::SineInt => Val::Int(scaled_i16(v.sine, 100.0).into()),
        Live::Blink1Hz => Val::Bool(v.blink_1hz),
        Live::Blink5Hz => Val::Bool(v.blink_5hz),
        Live::Encoder => u(s.k.wrapping_mul(4)),
        Live::Ton => Val::Fields(vec![("IN", Val::Bool(fb.ton_in)), ("PT", u(TON_PT_MS.into())),
                                      ("Q", Val::Bool(fb.ton_q)), ("ET", u(fb.ton_et.into())),
                                      ("M", Val::Bool(fb.ton_in)), ("StartTime", u(fb.ton_start.into()))]),
        Live::Ctu => Val::Fields(vec![("CU", Val::Bool(fb.ctu_cu)), ("RESET", Val::Bool(fb.ctu_reset)),
                                      ("PV", u(CTU_PV.into())), ("Q", Val::Bool(fb.ctu_q)),
                                      ("CV", u(fb.ctu_cv.into())), ("M", Val::Bool(fb.ctu_cu))]),
        Live::TonQ => Val::Bool(fb.ton_q),
        Live::TonEt => u(fb.ton_et.into()),
        Live::CtuCv => u(fb.ctu_cv.into()),
        Live::CtuQ => Val::Bool(fb.ctu_q),
        Live::TaskInfo(task) => Val::List(vec![Val::Fields(vec![
            ("ObjId", u(task.obj_id.into())),
            // 100 ns units.
            ("CycleTime", u(s.cycle_ms.saturating_mul(10_000))),
            ("Priority", u(task.priority.into())),
            ("AdsPort", u(task.ads_port.into())),
            ("CycleCount", u(s.k)),
            ("DcTaskTime", Val::Int(s.wall_ms.saturating_sub(DC_EPOCH_MS).saturating_mul(1_000_000))),
            ("LastExecTime", u(20 + s.k % 7)),
            ("FirstCycle", Val::Bool(s.k == 0)),
            ("TaskName", Val::Text(task.name.into())),
        ])]),
        Live::Tc2Tasks => Val::List(vec![Val::Fields(vec![
            ("active", Val::Bool(true)),
            ("taskName", Val::Text("PlcTask".into())),
            ("firstCycle", Val::Bool(s.k == 0)),
            ("cycleTime", u(s.cycle_ms.saturating_mul(10_000))),
            ("lastExecTime", u(20 + s.k % 7)),
            ("priority", u(1)),
            ("cycleCount", u(s.k)),
        ])]),
        Live::PartCount => u(ms / 500),
        Live::Temperature => Val::Real(20.0 + 5.0 * (TAU * 0.05 * s.t).sin()),
    }
}

/// A symbol the scan rewrites.
struct LiveTag {
    area: Area,
    bit: bool,
    io: u32,
    ty: Ty,
    live: Live,
}

/// The memory of one PLC runtime.
struct Memory {
    /// Indexed by `Area as usize`.
    areas: [Vec<u8>; 4],
    live: Vec<LiveTag>,
    timers: Timers,
}

/// Stores `v` as `ty` at `io`. In a bit group `io` is a bit number and only that bit changes.
fn store(mem: &mut [u8], bit: bool, io: u32, ty: &Ty, v: &Val, l: &Layout) {
    if bit {
        let mask = 1u8 << (io % 8);
        if let Some(b) = mem.get_mut(io as usize / 8) {
            if matches!(v, Val::Bool(true)) {
                *b |= mask;
            } else {
                *b &= !mask;
            }
        }
        return;
    }
    let at = io as usize;
    if let Some(slot) = mem.get_mut(at..at + ty.size(l)) {
        slot.fill(0);
        encode(ty, v, l, slot);
    }
}

/// The memory of every PLC runtime of a profile.
pub struct Image {
    layout: Layout,
    /// One per PLC runtime, in the order of `Profile::runtimes`.
    plcs: Vec<Memory>,
}

impl Image {
    fn new(runtimes: &[Runtime], layout: Layout) -> Image {
        let mut plcs = Vec::with_capacity(runtimes.len());
        for rt in runtimes {
            let areas = Area::ALL.map(|a| vec![0; a.size()]);
            let mut m = Memory { areas, live: Vec::new(), timers: Timers::default() };
            for s in &rt.symbols {
                let Some((area, bit)) = area(s.ig) else { continue };
                match &s.init {
                    Init::Static(v) => store(&mut m.areas[area as usize], bit, s.io, &s.ty, v, &layout),
                    Init::Live(live) => m.live.push(LiveTag { area, bit, io: s.io, ty: s.ty.clone(), live: *live }),
                }
            }
            plcs.push(m);
        }
        Image { layout, plcs }
    }
}

impl ScanImage for Image {
    fn scan(&mut self, s: &Scan) {
        let l = self.layout;
        for m in &mut self.plcs {
            m.timers.step(s);
            for tag in &m.live {
                let v = live_value(tag.live, s, &m.timers);
                store(&mut m.areas[tag.area as usize], tag.bit, tag.io, &tag.ty, &v, &l);
            }
        }
    }
}

/// An AMS address: NetId and port.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct AmsAddr {
    net: [u8; 6],
    port: u16,
}

impl fmt::Display for AmsAddr {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}:{}", netid(&self.net), self.port)
    }
}

fn netid(net: &[u8; 6]) -> String {
    net.iter().map(u8::to_string).collect::<Vec<_>>().join(".")
}

fn ams_addr(r: &mut Reader) -> Option<AmsAddr> {
    let net = r.bytes(6)?.try_into().ok()?;
    Some(AmsAddr { net, port: r.le_u16()? })
}

/// The 32-byte AMS header of a request. Its error code is ignored.
#[derive(Debug, Clone, Copy)]
struct Header {
    target: AmsAddr,
    source: AmsAddr,
    cmd: u16,
    flags: u16,
    len: u32,
    invoke: u32,
}

impl Header {
    fn parse(bytes: &[u8]) -> Option<Header> {
        let mut r = Reader::new(bytes);
        let (target, source) = (ams_addr(&mut r)?, ams_addr(&mut r)?);
        let (cmd, flags, len) = (r.le_u16()?, r.le_u16()?, r.le_u32()?);
        r.skip(4)?;
        Some(Header { target, source, cmd, flags, len, invoke: r.le_u32()? })
    }
}

/// A reply to `h` in one buffer: addresses swapped, command and invoke id echoed, flags 0x0005.
fn response(h: &Header, err: u32, data: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(38 + data.len());
    out.extend_from_slice(&[0, 0]);
    out.extend_from_slice(&(32 + data.len() as u32).to_le_bytes());
    for a in [h.source, h.target] {
        out.extend_from_slice(&a.net);
        out.extend_from_slice(&a.port.to_le_bytes());
    }
    out.extend_from_slice(&h.cmd.to_le_bytes());
    out.extend_from_slice(&RESPONSE_FLAGS.to_le_bytes());
    out.extend_from_slice(&(data.len() as u32).to_le_bytes());
    out.extend_from_slice(&err.to_le_bytes());
    out.extend_from_slice(&h.invoke.to_le_bytes());
    out.extend_from_slice(data);
    out
}

fn op_name(cmd: u16) -> &'static str {
    match cmd {
        CMD_READ_DEVICE_INFO => "ReadDeviceInfo",
        CMD_READ => "Read",
        CMD_WRITE => "Write",
        CMD_READ_STATE => "ReadState",
        CMD_WRITE_CONTROL => "WriteControl",
        CMD_ADD_NOTIFICATION => "AddDeviceNotification",
        CMD_DELETE_NOTIFICATION => "DeleteDeviceNotification",
        CMD_DEVICE_NOTIFICATION => "DeviceNotification",
        CMD_READ_WRITE => "ReadWrite",
        _ => "Malformed",
    }
}

fn group(ig: u32) -> String {
    format!("0x{ig:04X}")
}

fn ams_status(err: u32) -> String {
    format!("ams:0x{err:04X}")
}

fn merge(mut base: Value, extra: Value) -> Value {
    if let (Some(b), Value::Object(e)) = (base.as_object_mut(), extra) {
        b.extend(e);
    }
    base
}

/// A length and the bytes it counts: the payload of a Read or ReadWrite reply.
fn counted(bytes: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(4 + bytes.len());
    out.extend_from_slice(&(bytes.len() as u32).to_le_bytes());
    out.extend_from_slice(bytes);
    out
}

fn device_info((major, minor, build, name): (u8, u8, u16, &str)) -> Vec<u8> {
    let mut out = vec![major, minor];
    out.extend_from_slice(&build.to_le_bytes());
    let mut text = [0u8; 16];
    copy_cut(&mut text, name.as_bytes());
    out.extend_from_slice(&text);
    out
}

/// ReadState: RUN, device state 0. WriteControl is not simulated, so the state never changes.
fn state() -> Vec<u8> {
    [ADS_STATE_RUN.to_le_bytes(), 0u16.to_le_bytes()].concat()
}

/// 0xF100: offset 0 is the ADS state, offset 2 the device state, two bytes each.
fn device_data(io: u32, len: u32) -> Result<Vec<u8>, AdsErr> {
    let v = match io {
        0 => ADS_STATE_RUN,
        2 => 0,
        _ => return Err(AdsErr::InvalidOffset),
    };
    if len != 2 {
        return Err(AdsErr::InvalidSize);
    }
    Ok(v.to_le_bytes().to_vec())
}

/// A start beyond the area is an invalid offset, an end beyond it an invalid size.
fn read_bytes(mem: &[u8], io: u32, len: u32) -> Result<Vec<u8>, AdsErr> {
    let (start, end) = (io as usize, io as usize + len as usize);
    if start >= mem.len() {
        return Err(AdsErr::InvalidOffset);
    }
    mem.get(start..end).map(<[u8]>::to_vec).ok_or(AdsErr::InvalidSize)
}

/// Unverified encoding of a bit group read: one byte per bit, 0x01 or 0x00.
fn read_bits(mem: &[u8], io: u32, len: u32) -> Result<Vec<u8>, AdsErr> {
    let bits = mem.len() * 8;
    let (start, end) = (io as usize, io as usize + len as usize);
    if start >= bits {
        return Err(AdsErr::InvalidOffset);
    }
    if end > bits {
        return Err(AdsErr::InvalidSize);
    }
    Ok((start..end).map(|b| mem[b / 8] >> (b % 8) & 1).collect())
}

/// The failed items of a sum read by index, with their error, for the events log.
type ItemErrors = Map<String, Value>;

/// The reply data of one command, and what the events log records about it.
struct Answer {
    op: &'static str,
    detail: Value,
    /// 0, or the ADS error in the reply's result field.
    result: u32,
    data: Vec<u8>,
}

impl Answer {
    /// Result 0, then `payload`.
    fn ok(op: &'static str, detail: Value, payload: &[u8]) -> Answer {
        Answer { op, detail, result: 0, data: [&[0u8; 4][..], payload].concat() }
    }

    /// The error in the command's own reply layout: Read, ReadWrite and AddDeviceNotification carry a
    /// zero length or handle after the result.
    fn refuse(op: &'static str, detail: Value, cmd: u16, e: AdsErr) -> Answer {
        let mut data = (e as u32).to_le_bytes().to_vec();
        if matches!(cmd, CMD_READ | CMD_READ_WRITE | CMD_ADD_NOTIFICATION) {
            data.extend_from_slice(&[0; 4]);
        }
        Answer { op, detail, result: e as u32, data }
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
    layout: Layout,
    plcs: Vec<Runtime>,
    image: Arc<RwLock<Image>>,
}

impl Server {
    pub fn new(profile_name: &str) -> anyhow::Result<Server> {
        Server::build(profile_name, false)
    }

    /// As `new`, but the variables declared DT and TOD report those short type names, which some runtime
    /// might do (unverified). SFC maps neither, so their values arrive as raw bytes. sim.toml cannot
    /// switch this on: core::config rejects keys it does not know.
    pub fn with_alias_type_names(profile_name: &str) -> anyhow::Result<Server> {
        Server::build(profile_name, true)
    }

    fn build(profile_name: &str, alias: bool) -> anyhow::Result<Server> {
        let profile = profile(profile_name)?;
        let layout = Layout { pack: profile.pack, pointer: profile.pointer, alias };
        let plcs: Vec<Runtime> = profile
            .runtimes
            .iter()
            .map(|&port| {
                let symbols = symbols(&profile, &layout, port);
                let upload = upload(&symbols, &profile, &layout);
                let info = upload_info(symbols.len(), upload.len(), &profile);
                Runtime { port, symbols, upload, info }
            })
            .collect();
        let image = Arc::new(RwLock::new(Image::new(&plcs, layout)));
        Ok(Server { profile, layout, plcs, image })
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
            if conn.buf.len() < 6 {
                break;
            }
            let reserved = u16::from_le_bytes([conn.buf[0], conn.buf[1]]);
            let n = u32::from_le_bytes([conn.buf[2], conn.buf[3], conn.buf[4], conn.buf[5]]) as usize;
            // A non-zero first word is an AMS/TCP router command, which only a local router client sends, or
            // not AMS at all. A length outside the limits cannot frame anything either.
            if reserved != 0 || !(32..=32 + MAX_DATA).contains(&n) {
                let reason = if reserved != 0 { "reserved" } else { "length" };
                events.emit(NAME, conn.id, "Malformed", json!({"reason": reason, "reserved": reserved, "length": n}),
                            "closed");
                out.close = true;
                conn.buf.clear();
                break;
            }
            if conn.buf.len() < 6 + n {
                break;
            }
            let frame: Vec<u8> = conn.buf.drain(..6 + n).collect();
            if let Some(reply) = self.handle(conn.id, &frame, events) {
                out.replies.push(reply);
            }
        }
        out
    }

    /// Answers one complete frame: the AMS/TCP prefix, the AMS header and the ADS data. `None` drops it
    /// without a reply.
    pub fn handle(&self, conn: u64, frame: &[u8], events: &Events) -> Option<Vec<u8>> {
        let h = Header::parse(frame.get(6..38)?)?;
        let data = &frame[38..];
        let mut detail = json!({"src": h.source.to_string(), "dst": h.target.to_string(), "invoke": h.invoke});
        // A response, or a device notification, sent to the server: a TwinCAT router drops both.
        if h.flags & 0x0001 != 0 || h.cmd == CMD_DEVICE_NOTIFICATION {
            detail["reason"] = json!(if h.flags & 0x0001 != 0 { "response" } else { "device_notification" });
            events.emit(NAME, conn, "Malformed", detail, "discarded");
            return None;
        }
        // The AMS/TCP length already delimited the frame, so a disagreeing AMS length is answered.
        if h.len as usize != data.len() {
            detail["reason"] = json!("ams_length");
            detail["cmd"] = json!(h.cmd);
            detail["n"] = json!(h.len);
            events.emit(NAME, conn, "Malformed", detail, &ams_status(ERR_AMS_LENGTH));
            return Some(response(&h, ERR_AMS_LENGTH, &[]));
        }
        if h.target.net != self.profile.netid {
            events.emit(NAME, conn, op_name(h.cmd), detail, &ams_status(ERR_TARGET_MACHINE));
            return Some(response(&h, ERR_TARGET_MACHINE, &[]));
        }
        let plc = self.plcs.iter().position(|rt| rt.port == h.target.port);
        if plc.is_none() && h.target.port != SYSTEM_PORT {
            events.emit(NAME, conn, op_name(h.cmd), detail, &ams_status(ERR_TARGET_PORT));
            return Some(response(&h, ERR_TARGET_PORT, &[]));
        }
        // Unverified: how a router answers an unknown command id. SFC never sends one, and could not
        // decode the echoed id (RequestResponse.kt:139-143).
        if !(CMD_READ_DEVICE_INFO..=CMD_READ_WRITE).contains(&h.cmd) {
            let err = AdsErr::ServiceNotSupported as u32;
            detail["reason"] = json!("command");
            detail["cmd"] = json!(h.cmd);
            events.emit(NAME, conn, "Malformed", detail, &ams_status(err));
            return Some(response(&h, err, &[]));
        }
        let a = match plc {
            Some(i) => self.plc_command(i, h.cmd, data),
            None => self.system_command(h.cmd, data),
        };
        let status = if a.result == 0 { "ok".to_string() } else { format!("0x{:04X}", a.result) };
        events.emit(NAME, conn, a.op, merge(detail, a.detail), &status);
        Some(response(&h, 0, &a.data))
    }

    /// One command to the PLC runtime `plc`. Short data gets 0x705 in the command's reply layout.
    /// Writes, WriteControl, symbol handles and notifications are not simulated: they get the answers
    /// of a read-only device.
    fn plc_command(&self, plc: usize, cmd: u16, d: &[u8]) -> Answer {
        let op = op_name(cmd);
        let mut r = Reader::new(d);
        match cmd {
            CMD_READ_DEVICE_INFO => Answer::ok(op, json!({}), &device_info(self.profile.plc_device)),
            CMD_READ_STATE => Answer::ok(op, json!({}), &state()),
            CMD_READ => {
                let (Some(ig), Some(io), Some(len)) = (r.le_u32(), r.le_u32(), r.le_u32()) else {
                    return Answer::refuse(op, json!({}), cmd, AdsErr::InvalidSize);
                };
                let detail = json!({"ig": group(ig), "io": io, "len": len});
                let img = self.image.read().unwrap_or_else(|e| e.into_inner());
                match self.read(&img, plc, ig, io, len) {
                    Ok(bytes) => Answer::ok(op, detail, &counted(&bytes)),
                    Err(e) => Answer::refuse(op, detail, cmd, e),
                }
            }
            CMD_WRITE => {
                let (Some(ig), Some(io), Some(len)) = (r.le_u32(), r.le_u32(), r.le_u32()) else {
                    return Answer::refuse(op, json!({}), cmd, AdsErr::InvalidSize);
                };
                let detail = json!({"ig": group(ig), "io": io, "len": len});
                if r.remaining() < len as usize {
                    return Answer::refuse(op, detail, cmd, AdsErr::InvalidSize);
                }
                // Read-only: every group the runtime serves refuses the write.
                let e = if serves(ig) { AdsErr::InvalidAccess } else { AdsErr::InvalidGroup };
                Answer::refuse(op, detail, cmd, e)
            }
            CMD_WRITE_CONTROL => {
                let (Some(ads), Some(dev), Some(len)) = (r.le_u16(), r.le_u16(), r.le_u32()) else {
                    return Answer::refuse(op, json!({}), cmd, AdsErr::InvalidSize);
                };
                let detail = json!({"ads_state": ads, "device_state": dev});
                if r.remaining() < len as usize {
                    return Answer::refuse(op, detail, cmd, AdsErr::InvalidSize);
                }
                // RUN, STOP and RESET are not simulated: the PLC stays in RUN and refuses the service,
                // as the system service does.
                Answer::refuse(op, detail, cmd, AdsErr::ServiceNotSupported)
            }
            CMD_ADD_NOTIFICATION => {
                let (Some(ig), Some(io), Some(len)) = (r.le_u32(), r.le_u32(), r.le_u32()) else {
                    return Answer::refuse(op, json!({}), cmd, AdsErr::InvalidSize);
                };
                let detail = json!({"ig": group(ig), "io": io, "len": len});
                // Notifications would need unsolicited frames: refused, with handle 0.
                let e = if d.len() < 40 { AdsErr::InvalidSize } else { AdsErr::ServiceNotSupported };
                Answer::refuse(op, detail, cmd, e)
            }
            CMD_DELETE_NOTIFICATION => {
                let Some(handle) = r.le_u32() else {
                    return Answer::refuse(op, json!({}), cmd, AdsErr::InvalidSize);
                };
                Answer::refuse(op, json!({"handle": handle}), cmd, AdsErr::InvalidNotifyHandle)
            }
            CMD_READ_WRITE => {
                let (Some(ig), Some(io), Some(rlen), Some(wlen)) = (r.le_u32(), r.le_u32(), r.le_u32(), r.le_u32())
                else {
                    return Answer::refuse(op, json!({}), cmd, AdsErr::InvalidSize);
                };
                let op = match ig {
                    IG_SUMUP_READ => "SumRead",
                    IG_SUMUP_WRITE => "SumWrite",
                    IG_SUMUP_READWRITE => "SumReadWrite",
                    _ => op,
                };
                let mut detail = json!({"ig": group(ig), "io": io, "rlen": rlen, "wlen": wlen});
                let Some(w) = r.bytes(wlen as usize) else {
                    return Answer::refuse(op, detail, cmd, AdsErr::InvalidSize);
                };
                if ig != IG_SUMUP_READ {
                    // Symbol handles (0xF003, 0xF005, 0xF006), values and info by name (0xF004, 0xF009) and
                    // the sum write commands are not simulated: they answer as any group not served.
                    return Answer::refuse(op, detail, cmd, AdsErr::InvalidGroup);
                }
                let img = self.image.read().unwrap_or_else(|e| e.into_inner());
                match self.sum_read(&img, plc, io, rlen, w) {
                    Ok((data, errors)) => {
                        if !errors.is_empty() {
                            detail["item_errors"] = Value::Object(errors);
                        }
                        Answer::ok(op, detail, &counted(&data))
                    }
                    Err(e) => Answer::refuse(op, detail, cmd, e),
                }
            }
            _ => Answer::refuse(op, json!({}), cmd, AdsErr::ServiceNotSupported),
        }
    }

    /// One command to the system service: ReadDeviceInfo, ReadState and Read of 0xF100 only; anything
    /// else gets 0x701 in its reply layout. A real system service also switches between RUN and CONFIG
    /// and serves more groups; SFC never addresses it.
    fn system_command(&self, cmd: u16, d: &[u8]) -> Answer {
        let op = op_name(cmd);
        match cmd {
            CMD_READ_DEVICE_INFO => Answer::ok(op, json!({}), &device_info(self.profile.system_device)),
            CMD_READ_STATE => Answer::ok(op, json!({}), &state()),
            CMD_READ => {
                let mut r = Reader::new(d);
                let (Some(ig), Some(io), Some(len)) = (r.le_u32(), r.le_u32(), r.le_u32()) else {
                    return Answer::refuse(op, json!({}), cmd, AdsErr::InvalidSize);
                };
                let detail = json!({"ig": group(ig), "io": io, "len": len});
                let read = if ig == IG_DEVICE_DATA { device_data(io, len) } else { Err(AdsErr::ServiceNotSupported) };
                match read {
                    Ok(bytes) => Answer::ok(op, detail, &counted(&bytes)),
                    Err(e) => Answer::refuse(op, detail, cmd, e),
                }
            }
            _ => Answer::refuse(op, json!({}), cmd, AdsErr::ServiceNotSupported),
        }
    }

    /// One read, as command 2 or as a sum read item, from the snapshot `img`.
    fn read(&self, img: &Image, plc: usize, ig: u32, io: u32, len: u32) -> Result<Vec<u8>, AdsErr> {
        if let Some((area, bits)) = area(ig) {
            let mem = &img.plcs[plc].areas[area as usize];
            return if bits { read_bits(mem, io, len) } else { read_bytes(mem, io, len) };
        }
        let rt = &self.plcs[plc];
        let len = len as usize;
        match ig {
            IG_SYM_UPLOADINFO2 => Ok(rt.info[..len.min(rt.info.len())].to_vec()),
            IG_SYM_UPLOADINFO => Ok(rt.info[..len.min(8)].to_vec()),
            IG_SYM_UPLOAD if len < rt.upload.len() => Err(AdsErr::InvalidSize),
            IG_SYM_UPLOAD => Ok(rt.upload.clone()),
            // No data-type table, consistent with nDatatypes = 0.
            IG_SYM_DT_UPLOAD => Ok(Vec::new()),
            IG_SYM_VERSION if len == 0 => Err(AdsErr::InvalidSize),
            IG_SYM_VERSION => Ok(vec![SYMBOL_VERSION]),
            IG_DEVICE_DATA => device_data(io, len as u32),
            _ => Err(AdsErr::InvalidGroup),
        }
    }

    /// 0xF080: `k` items of {group, offset, length}. The reply is k item results, then every item's
    /// bytes at its full length, zero-filled where the item failed (MultiReadResponse.kt:34-56). Items
    /// may not be sum groups themselves.
    fn sum_read(&self, img: &Image, plc: usize, k: u32, rlen: u32, w: &[u8]) -> Result<(Vec<u8>, ItemErrors), AdsErr> {
        if k == 0 || k > MAX_SUM_ITEMS {
            return Err(AdsErr::InvalidParam);
        }
        if w.len() != 12 * k as usize {
            return Err(AdsErr::InvalidSize);
        }
        let mut r = Reader::new(w);
        let mut items = Vec::with_capacity(k as usize);
        while let (Some(ig), Some(io), Some(len)) = (r.le_u32(), r.le_u32(), r.le_u32()) {
            items.push((ig, io, len));
        }
        // The reply must fit the requested length, and one frame.
        let total = 4 * u64::from(k) + items.iter().map(|i| u64::from(i.2)).sum::<u64>();
        if u64::from(rlen) < total || total > MAX_DATA as u64 {
            return Err(AdsErr::InvalidSize);
        }
        let mut data = Vec::with_capacity(total as usize);
        let mut slots = Vec::new();
        let mut errors = Map::new();
        for (i, (ig, io, len)) in items.into_iter().enumerate() {
            let (code, mut bytes) = match self.read(img, plc, ig, io, len) {
                Ok(bytes) => (0, bytes),
                Err(e) => {
                    errors.insert(i.to_string(), json!(format!("0x{:04X}", e as u32)));
                    (e as u32, Vec::new())
                }
            };
            bytes.resize(len as usize, 0);
            data.extend_from_slice(&code.to_le_bytes());
            slots.extend_from_slice(&bytes);
        }
        data.extend_from_slice(&slots);
        Ok((data, errors))
    }

    pub fn print_map(&self) -> Value {
        let (p, l) = (&self.profile, &self.layout);
        let runtimes: Vec<Value> = self
            .plcs
            .iter()
            .map(|rt| {
                let tags: Vec<Value> = rt
                    .symbols
                    .iter()
                    .map(|s| {
                        json!({
                            "sfc": {"SymbolName": s.name}, "ig": group(s.ig), "io": s.io, "size": s.size,
                            "type": s.ty.name(l), "adst": s.ty.adst(l), "flags": s.flags, "comment": s.comment,
                            "value": shown(&s.init, &s.ty),
                        })
                    })
                    .collect();
                json!({"port": rt.port, "symbols": rt.symbols.len(), "upload_bytes": rt.upload.len(), "tags": tags})
            })
            .collect();
        let mut ports: Vec<u16> = p.runtimes.to_vec();
        ports.push(SYSTEM_PORT);
        let device = |(major, minor, build, name): (u8, u8, u16, &str)| format!("{name} {major}.{minor}.{build}");
        let areas: Map<String, Value> = Area::ALL.iter().map(|a| (group(a.group()), json!(a.size()))).collect();
        json!({
            "protocol": NAME, "profile": p.name, "device": p.title, "netid": netid(&p.netid), "ports": ports,
            "device_info": {"plc": device(p.plc_device), "system": device(p.system_device)},
            "twincat": if p.tc3 { 3 } else { 2 }, "pack": p.pack, "pointer": p.pointer,
            "type_names": if l.alias { "DT, TOD" } else { "DATE_AND_TIME, TIME_OF_DAY" },
            "areas": areas, "limits": {"max_data": MAX_DATA, "max_sum_items": MAX_SUM_ITEMS},
            "runtimes": runtimes,
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
        let mut buf = vec![0u8; 8192];
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
                // Reset rather than close, as a router does with a stream it cannot frame.
                let _ = stream.set_zero_linger();
                return "malformed";
            }
        }
    }
}

/// A symbol's value for `--print-map`.
fn shown(init: &Init, ty: &Ty) -> Value {
    match init {
        Init::Static(v) => value_json(v, ty),
        Init::Live(live) => json!(format!("dynamic: {}", live.describe())),
    }
}

fn value_json(v: &Val, ty: &Ty) -> Value {
    match (v, ty) {
        (Val::Bool(b), _) => json!(b),
        (Val::Int(i), Ty::E(e) | Ty::Enum(_, e)) if !e.signed() => {
            let bits = 8 * e.size() as u32;
            json!(if bits >= 64 { *i as u64 } else { *i as u64 & ((1u64 << bits) - 1) })
        }
        (Val::Int(i), Ty::Pointer(_)) => json!(format!("16#{i:X}")),
        (Val::Int(i), _) => json!(i),
        (Val::Real(x), _) => json!(x),
        (Val::Text(s), _) => json!(s),
        (Val::Raw(bytes), _) => json!(hex(bytes)),
        (Val::List(items), Ty::Array(_, el)) => Value::Array(items.iter().map(|x| value_json(x, el)).collect()),
        (Val::Fields(fields), Ty::Struct(_, members)) => {
            let mut out = Map::new();
            for (name, fv) in fields {
                if let Some((_, mty)) = members.iter().find(|(n, _)| n == name) {
                    out.insert(name.to_string(), value_json(fv, mty));
                }
            }
            Value::Object(out)
        }
        _ => Value::Null,
    }
}
