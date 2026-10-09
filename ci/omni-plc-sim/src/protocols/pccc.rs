// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! PCCC over EtherNet/IP: the data table of an SLC 500, MicroLogix or PLC-5 behind the CIP PCCC
//! object (EtherNet/IP encapsulation from CIP Vol. 2; PCCC commands as in the DF1 command set).
//!
//! What SFC's pccc adapter needs (its own client, Client.kt): RegisterSession answered in exactly 28
//! bytes, then SendRRData with CIP Execute PCCC (service 0x4B to class 0x67, instance 1) carrying PCCC
//! CMD 0x0F / FNC 0xA2, the protected typed logical read with three address fields. The client frames
//! each reply by its encapsulation length and never resyncs, so every reply is exactly as long as its
//! header says and comes in request order. On top of that, as a real controller would: ListIdentity,
//! UnRegisterSession and NOP, the encapsulation, CIP and PCCC error codes, and four profiles. Writes
//! are not simulated: every other PCCC command or function gets STS 0x10, the answer of a controller
//! that does not support it.
//!
//! Address map (SFC `Address` = `<type><file>:<element>`): see `--print-map pccc` and
//! ci/omni-plc-sim/README.md.

use std::net::SocketAddr;
use std::sync::{Arc, RwLock};

use anyhow::bail;
use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

use crate::core::codec::Reader;
use crate::core::engine::{Image as ScanImage, Scan, ScanTarget};
use crate::core::events::Events;
use crate::core::signal::scaled_i16;

pub const NAME: &str = "pccc";
pub const DEFAULT_PROFILE: &str = "micrologix1400";
pub const PROFILES: &[&str] = &["micrologix1400", "micrologix1100", "slc505", "plc5"];

/// The encapsulation header: command, length, session handle, status, sender context, options.
const HEADER: usize = 24;
/// The longest encapsulation data: header and data together must fit in 65535 bytes.
const MAX_DATA: usize = 65_535 - HEADER;

const NOP: u16 = 0x0000;
const LIST_IDENTITY: u16 = 0x0063;
const REGISTER_SESSION: u16 = 0x0065;
const UNREGISTER_SESSION: u16 = 0x0066;
const SEND_RR_DATA: u16 = 0x006F;

const ENCAP_UNSUPPORTED_COMMAND: u32 = 0x0001;
const ENCAP_INCORRECT_DATA: u32 = 0x0003;
const ENCAP_INVALID_SESSION: u32 = 0x0064;
const ENCAP_INVALID_LENGTH: u32 = 0x0065;
const ENCAP_UNSUPPORTED_VERSION: u32 = 0x0069;

/// Common packet format item types.
const CPF_NULL_ADDRESS: u16 = 0x0000;
const CPF_IDENTITY: u16 = 0x000C;
const CPF_UNCONNECTED_DATA: u16 = 0x00B2;

const EXECUTE_PCCC: u8 = 0x4B;
const PCCC_CLASS: u32 = 0x67;

const CIP_PATH_SEGMENT_ERROR: u8 = 0x04;
const CIP_PATH_DESTINATION_UNKNOWN: u8 = 0x05;
const CIP_SERVICE_NOT_SUPPORTED: u8 = 0x08;
const CIP_NOT_ENOUGH_DATA: u8 = 0x13;

const CMD_TYPED: u8 = 0x0F;
const FNC_TYPED_READ: u8 = 0xA2;

/// PCCC STS 0x10, illegal command or format; STS 0xF0, the error is in EXT STS.
const STS_ILLEGAL_COMMAND: u8 = 0x10;
const STS_EXT: u8 = 0xF0;
/// EXT STS 0x06, address does not point to something usable; 0x0A, transaction size plus word
/// address is too large.
const EXT_NOT_USABLE: u8 = 0x06;
const EXT_BEYOND_FILE: u8 = 0x0A;

/// Rockwell Automation/Allen-Bradley, and the CIP device type of a programmable logic controller.
const VENDOR_ID: u16 = 1;
const DEVICE_TYPE: u16 = 0x0E;
/// ListIdentity status word (no I/O connections established) and state (operational).
const IDENTITY_STATUS: u16 = 0x0030;
const IDENTITY_STATE: u8 = 0x03;

/// Control-word bits of T, C and R elements, where the client decodes them (AddressNamedSubElement.kt).
const EN: u16 = 1 << 15;
const TT: u16 = 1 << 14;
const DN: u16 = 1 << 13;
const CU: u16 = 1 << 15;

const TON_PRE: u16 = 500;
const CTU_PRE: u16 = 10;

/// The data file types the client addresses, with their PCCC type codes (DataFileType.kt:21-34).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileType {
    Output,
    Input,
    Status,
    Binary,
    Timer,
    Counter,
    Control,
    Integer,
    Float,
    Str,
    Long,
    Ascii,
}

impl FileType {
    pub fn code(self) -> u8 {
        match self {
            FileType::Status => 0x84,
            FileType::Binary => 0x85,
            FileType::Timer => 0x86,
            FileType::Counter => 0x87,
            FileType::Control => 0x88,
            FileType::Integer => 0x89,
            FileType::Float => 0x8A,
            FileType::Output => 0x8B,
            FileType::Input => 0x8C,
            FileType::Str => 0x8D,
            FileType::Ascii => 0x8E,
            FileType::Long => 0x91,
        }
    }

    /// The address prefix: O0:0, ST9:0.
    pub fn prefix(self) -> &'static str {
        match self {
            FileType::Output => "O",
            FileType::Input => "I",
            FileType::Status => "S",
            FileType::Binary => "B",
            FileType::Timer => "T",
            FileType::Counter => "C",
            FileType::Control => "R",
            FileType::Integer => "N",
            FileType::Float => "F",
            FileType::Str => "ST",
            FileType::Long => "L",
            FileType::Ascii => "A",
        }
    }

    /// Bytes per element, the S of `element·S + sub·2` (sizeOfSingleItemInBytes in DataFileType.kt).
    pub fn element_bytes(self) -> usize {
        match self {
            FileType::Timer | FileType::Counter | FileType::Control => 6,
            FileType::Float | FileType::Long => 4,
            FileType::Str => 84,
            _ => 2,
        }
    }
}

/// ListIdentity values. They are illustrative: plausible for the controller, not read from a real one.
#[derive(Debug, Clone)]
pub struct Identity {
    pub product_code: u16,
    pub revision: (u8, u8),
    pub serial: u32,
    pub product_name: &'static str,
}

#[derive(Debug, Clone)]
pub struct Profile {
    pub name: &'static str,
    pub title: &'static str,
    /// Data files: number, type, elements.
    pub files: Vec<(u16, FileType, usize)>,
    /// FNC 0xA2 is an SLC 500 and MicroLogix function; a PLC-5 answers it with STS 0x10.
    pub typed_reads: bool,
    pub identity: Identity,
}

/// The RSLogix 500 default files O0 to N7 and F8, then ST9, L10 and A11 as SFC's example numbers them.
const LAYOUT: [(u16, FileType); 12] = [
    (0, FileType::Output),
    (1, FileType::Input),
    (2, FileType::Status),
    (3, FileType::Binary),
    (4, FileType::Timer),
    (5, FileType::Counter),
    (6, FileType::Control),
    (7, FileType::Integer),
    (8, FileType::Float),
    (9, FileType::Str),
    (10, FileType::Long),
    (11, FileType::Ascii),
];

/// The files of [`LAYOUT`] with these element counts; 0 leaves a file out.
fn files(elements: [usize; 12]) -> Vec<(u16, FileType, usize)> {
    LAYOUT.iter().zip(elements).filter(|(_, n)| *n > 0).map(|(&(number, kind), n)| (number, kind, n)).collect()
}

pub fn profile(name: &str) -> anyhow::Result<Profile> {
    // Element counts in LAYOUT order: O0 I1 S2 B3 T4 C5 R6 N7 F8 ST9 L10 A11. Every file a profile has
    // holds all of its default-map tags, so the client's merged reads of them (up to 220 bytes, gaps up
    // to MaxReadGap, Client.kt:395-471) stay inside the files; past the end of a file is EXT STS 0x0A.
    Ok(match name {
        "micrologix1400" => Profile {
            name: "micrologix1400",
            title: "MicroLogix 1400 (1766-L32BXB), embedded EtherNet/IP",
            files: files([4, 4, 66, 16, 8, 8, 4, 64, 32, 4, 16, 4]),
            typed_reads: true,
            identity: Identity {
                product_code: 90,
                revision: (21, 3),
                serial: 0x0014_0001,
                product_name: "1766-L32BXB B/21.03",
            },
        },
        "micrologix1100" => Profile {
            name: "micrologix1100",
            title: "MicroLogix 1100 (1763-L16BWA), embedded EtherNet/IP",
            files: files([2, 2, 66, 4, 4, 4, 2, 16, 24, 2, 12, 4]),
            typed_reads: true,
            identity: Identity {
                product_code: 88,
                revision: (16, 0),
                serial: 0x0011_0001,
                product_name: "1763-L16BWA B/16.00",
            },
        },
        // The SLC 500 has no L files.
        "slc505" => Profile {
            name: "slc505",
            title: "SLC 5/05 (1747-L552), Series C",
            files: files([4, 4, 164, 16, 8, 8, 4, 64, 32, 4, 0, 4]),
            typed_reads: true,
            identity: Identity {
                product_code: 87,
                revision: (10, 0),
                serial: 0x0505_0001,
                product_name: "1747-L552/C C/10.00",
            },
        },
        // A PLC-5 reads with FNC 0x68 and word-range reads, which are not simulated: its files are
        // listed for --print-map, but no client can read them.
        "plc5" => Profile {
            name: "plc5",
            title: "PLC-5/40E (1785-L40E), Series F",
            files: files([4, 4, 128, 16, 8, 8, 4, 64, 32, 4, 0, 4]),
            typed_reads: false,
            identity: Identity {
                product_code: 21,
                revision: (15, 0),
                serial: 0x0540_0001,
                product_name: "1785-L40E/F",
            },
        },
        other => bail!("unknown pccc profile {other:?}; known: {}", PROFILES.join(", ")),
    })
}

/// How a static element is laid out: little-endian, as everything on the wire (Decoders.kt:60-83).
#[derive(Debug, Clone)]
enum Enc {
    /// A 16-bit word: O, I, S and B elements.
    Word(u16),
    /// An N element.
    Int(i16),
    /// An F element, IEEE 754.
    Real(f32),
    /// An L element.
    Long(i32),
    /// A T, C or R element: control word, PRE (LEN), ACC (POS).
    Struct(u16, u16, u16),
    /// An ST element: LEN, then up to 82 characters.
    Text(&'static str),
    /// `words` A elements, two characters each.
    Ascii(&'static str, usize),
}

impl Enc {
    fn bytes(&self) -> Vec<u8> {
        match self {
            Enc::Word(w) => w.to_le_bytes().to_vec(),
            Enc::Int(v) => v.to_le_bytes().to_vec(),
            Enc::Real(v) => v.to_le_bytes().to_vec(),
            Enc::Long(v) => v.to_le_bytes().to_vec(),
            Enc::Struct(w0, w1, w2) => [w0.to_le_bytes(), w1.to_le_bytes(), w2.to_le_bytes()].concat(),
            Enc::Text(s) => {
                let mut out = (s.len() as u16).to_le_bytes().to_vec();
                out.extend(swapped_pairs(s, 82));
                out
            }
            Enc::Ascii(s, words) => swapped_pairs(s, 2 * words),
        }
    }

    fn shown(&self) -> Value {
        match self {
            Enc::Word(w) => json!(format!("0x{w:04X}")),
            Enc::Int(v) => json!(v),
            Enc::Real(v) => json!(v),
            Enc::Long(v) => json!(v),
            Enc::Struct(w0, w1, w2) => json!([format!("0x{w0:04X}"), w1, w2]),
            Enc::Text(s) | Enc::Ascii(s, _) => json!(s),
        }
    }
}

/// Characters two to a word with the first in the high byte, so each pair travels swapped
/// (Decoders.kt:33-53, :86-91); NUL-padded to `bytes`.
fn swapped_pairs(text: &str, bytes: usize) -> Vec<u8> {
    let mut chars: Vec<u8> = text.bytes().collect();
    chars.resize(bytes.next_multiple_of(2), 0);
    chars.chunks(2).flat_map(|p| [p[1], p[0]]).collect()
}

struct StaticTag {
    tag: &'static str,
    file: u16,
    element: usize,
    kind: &'static str,
    enc: Enc,
}

fn st(tag: &'static str, file: u16, element: usize, kind: &'static str, enc: Enc) -> StaticTag {
    StaticTag { tag, file, element, kind, enc }
}

fn statics() -> Vec<StaticTag> {
    vec![
        st("inputs", 1, 0, "WORD, inputs 0 and 7 on", Enc::Word(0x0081)),
        st("mode", 2, 1, "S:1, processor mode bits 0-4 = 1 1110 (RUN)", Enc::Word(0x001E)),
        st("status_word", 3, 0, "WORD (bits 0,1,6,7,8,10,13,15)", Enc::Word(0xA5C3)),
        st("timer", 4, 0, "TIMER: EN and DN set, PRE 100, ACC 100", Enc::Struct(EN | DN, 100, 100)),
        st("counter", 5, 0, "COUNTER: PRE 10, ACC 7", Enc::Struct(0, 10, 7)),
        st("control", 6, 0, "CONTROL: LEN 10, POS 3", Enc::Struct(0, 10, 3)),
        st("int", 7, 0, "INT", Enc::Int(-12345)),
        st("int_pos", 7, 1, "INT", Enc::Int(12345)),
        st("int_max", 7, 2, "INT", Enc::Int(i16::MAX)),
        st("int_min", 7, 3, "INT", Enc::Int(i16::MIN)),
        st("real", 8, 0, "REAL", Enc::Real(12345.5)),
        st("real_neg", 8, 1, "REAL", Enc::Real(-0.25)),
        st("real_int", 8, 2, "REAL", Enc::Real(3.0)),
        st("real_half", 8, 3, "REAL", Enc::Real(0.5)),
        st("string", 9, 0, "STRING", Enc::Text("SFC-SIM")),
        st("string_2", 9, 1, "STRING", Enc::Text("HELLO WORLD")),
        st("dint", 10, 0, "LONG", Enc::Long(-1_234_567_890)),
        st("dint_pos", 10, 1, "LONG", Enc::Long(1_234_567_890)),
        st("ascii", 11, 0, "ASCII, 2 characters a word", Enc::Ascii("SFC-SIM", 4)),
    ]
}

/// The dynamic tags, for `--print-map`: (file, SFC address, tag, encoding).
const DYNAMIC: &[(u16, &str, &str, &str)] = &[
    (2, "S2:4", "free_running_clock", "WORD, +1 every scan"),
    (3, "B3:1/0", "blink_1hz", "BIT"),
    (3, "B3:1/1", "blink_5hz", "BIT"),
    (4, "T4:1", "ton", "TIMER: TON, PRE 500, base 0.01 s, reset by its own DN bit"),
    (5, "C5:1", "ctu", "COUNTER: PRE 10, ACC = whole seconds mod 16, CU = the 1 Hz pulse it counts"),
    (7, "N7:10", "sine_int", "INT round(100·sine)"),
    (7, "N7:11", "scan15", "INT scan mod 32768"),
    (8, "F8:10", "sine", "REAL"),
    (8, "F8:11", "cosine", "REAL"),
    (8, "F8:12", "tangent", "REAL"),
    (8, "F8:13", "cotangent", "REAL"),
    (8, "F8:14", "exp", "REAL"),
    (8, "F8:15", "quadratic", "REAL"),
    (8, "F8:16", "sawtooth", "REAL"),
    (8, "F8:17", "triangle", "REAL"),
    (8, "F8:18", "square", "REAL"),
    (8, "F8:19", "damped", "REAL"),
    (8, "F8:20", "noise", "REAL"),
    (8, "F8:21", "randomwalk", "REAL"),
    (10, "L10:10", "scan", "LONG scan"),
];

/// A data file: its elements back to back, as the wire carries them.
#[derive(Debug, Clone)]
pub struct DataFile {
    pub number: u16,
    pub kind: FileType,
    pub bytes: Vec<u8>,
}

/// The data table: the profile's files.
pub struct Image {
    pub files: Vec<DataFile>,
}

impl Image {
    fn new(p: &Profile) -> Image {
        let files = p
            .files
            .iter()
            .map(|&(number, kind, elements)| DataFile { number, kind, bytes: vec![0; elements * kind.element_bytes()] })
            .collect();
        let mut img = Image { files };
        for tag in statics() {
            img.put(tag.file, tag.element, &tag.enc.bytes());
        }
        img
    }

    pub fn file(&self, number: u16) -> Option<&DataFile> {
        self.files.iter().find(|f| f.number == number)
    }

    /// Writes `bytes` from the start of `element`; a profile without that file or element skips it.
    fn put(&mut self, number: u16, element: usize, bytes: &[u8]) {
        let Some(file) = self.files.iter_mut().find(|f| f.number == number) else {
            return;
        };
        let start = element * file.kind.element_bytes();
        if let Some(slot) = file.bytes.get_mut(start..start + bytes.len()) {
            slot.copy_from_slice(bytes);
        }
    }

    fn put_words(&mut self, number: u16, element: usize, words: &[u16]) {
        let bytes: Vec<u8> = words.iter().flat_map(|w| w.to_le_bytes()).collect();
        self.put(number, element, &bytes);
    }
}

impl ScanImage for Image {
    fn scan(&mut self, s: &Scan) {
        let v = &s.v;
        let k = s.k;
        // Timers and counters run on PLC time, which is k · cycle_ms.
        let ms = k.saturating_mul(s.cycle_ms);

        // S:4, the free-running clock: +1 every 10 ms of PLC time, whatever the scan cycle.
        self.put_words(2, 4, &[(ms / 10) as u16]);
        self.put_words(3, 1, &[(v.blink_1hz as u16) | (v.blink_5hz as u16) << 1]);

        // T4:1 is the classic free-running timer, `XIO T4:1/DN  TON T4:1 0.01 500`: it times up to PRE
        // in 10 ms ticks, is done for one tick, and its own DN bit resets it on the next.
        let tick = ms / 10 % (TON_PRE as u64 + 2);
        let (w0, acc) = if tick < TON_PRE as u64 {
            (EN | TT, tick as u16)
        } else if tick == TON_PRE as u64 {
            (EN | DN, TON_PRE)
        } else {
            (0, 0)
        };
        self.put_words(4, 1, &[w0, TON_PRE, acc]);

        // C5:1 counts a 1 Hz pulse, which CU follows, and the program resets it after 15.
        let count = (ms / 1000 % 16) as u16;
        let mut c0 = if ms % 1000 < 500 { CU } else { 0 };
        if count >= CTU_PRE {
            c0 |= DN;
        }
        self.put_words(5, 1, &[c0, CTU_PRE, count]);

        self.put_words(7, 10, &[scaled_i16(v.sine, 100.0) as u16, (k % 32768) as u16]);
        let reals = [v.sine, v.cosine, v.tangent, v.cotangent, v.exp, v.quadratic, v.sawtooth, v.triangle, v.square,
                     v.damped, v.noise, v.randomwalk];
        for (i, x) in reals.iter().enumerate() {
            self.put(8, 10 + i, &(*x as f32).to_le_bytes());
        }
        self.put(10, 10, &(k as u32).to_le_bytes());
    }
}

/// A connection's unparsed input and its session.
#[derive(Debug, Default)]
pub struct Conn {
    pub id: u64,
    buf: Vec<u8>,
    /// The session RegisterSession opened on this connection.
    session: Option<u32>,
    /// The address the client connected to, which ListIdentity reports.
    local: Option<SocketAddr>,
}

impl Conn {
    pub fn new(id: u64) -> Conn {
        Conn { id, ..Conn::default() }
    }

    /// The handle RegisterSession gives this connection: its number, so it is non-zero and unique
    /// within the process.
    fn session_handle(&self) -> u32 {
        (self.id as u32).max(1)
    }
}

/// The outcome of feeding bytes to a connection.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct Output {
    /// Replies, in request order; each one goes out in a single write.
    pub replies: Vec<Vec<u8>>,
    /// Why the connection must close: the stream cannot be framed any more (`bad_length`), or the
    /// client unregistered its session (`unregistered`).
    pub close: Option<&'static str>,
}

/// What one encapsulation request is answered with.
enum Answer {
    Reply(Vec<u8>),
    /// NOP, or a request the receiver must discard: nothing goes back.
    Silent,
    /// UnRegisterSession: the connection closes without a reply.
    Close(&'static str),
}

/// The encapsulation header of a request.
#[derive(Debug, Clone, Copy)]
struct Header {
    command: u16,
    session: u32,
    status: u32,
    context: [u8; 8],
    options: u32,
}

impl Header {
    fn parse(frame: &[u8]) -> Option<Header> {
        let mut r = Reader::new(frame);
        let command = r.le_u16()?;
        r.skip(2)?;
        let session = r.le_u32()?;
        let status = r.le_u32()?;
        let context = r.bytes(8)?.try_into().ok()?;
        let options = r.le_u32()?;
        Some(Header { command, session, status, context, options })
    }

    /// A reply with the request's command and sender context.
    fn reply(&self, session: u32, status: u32, data: &[u8]) -> Vec<u8> {
        let mut out = Vec::with_capacity(HEADER + data.len());
        out.extend_from_slice(&self.command.to_le_bytes());
        out.extend_from_slice(&(data.len() as u16).to_le_bytes());
        out.extend_from_slice(&session.to_le_bytes());
        out.extend_from_slice(&status.to_le_bytes());
        out.extend_from_slice(&self.context);
        out.extend_from_slice(&0u32.to_le_bytes());
        out.extend_from_slice(data);
        out
    }
}

fn encap(status: u32) -> String {
    format!("encap 0x{status:04X}")
}

/// How a request failed below the encapsulation: a CIP general status, or a PCCC STS and, for STS
/// 0xF0, its EXT STS.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Fault {
    Cip(u8),
    Sts(u8, Option<u8>),
}

impl Fault {
    /// Adds the codes to an event's detail and returns the event's status.
    fn report(self, detail: &mut Value) -> String {
        match self {
            Fault::Cip(code) => {
                detail["cip_status"] = json!(code);
                format!("cip 0x{code:02X}")
            }
            Fault::Sts(sts, None) => {
                detail["sts"] = json!(sts);
                format!("sts 0x{sts:02X}")
            }
            Fault::Sts(sts, Some(ext)) => {
                detail["sts"] = json!(sts);
                detail["ext_sts"] = json!(ext);
                format!("sts 0x{sts:02X} ext 0x{ext:02X}")
            }
        }
    }
}

/// A PCCC STS and its EXT STS.
type Sts = (u8, Option<u8>);

/// A CIP request's event op and detail, its failure if any, and the CIP reply.
type CipOutcome = (&'static str, Value, Option<Fault>, Vec<u8>);

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

    /// Splits `input` (appended to what the connection already holds) into encapsulation frames by
    /// their declared length, and answers each.
    pub fn feed(&self, conn: &mut Conn, input: &[u8], events: &Events) -> Output {
        conn.buf.extend_from_slice(input);
        let mut out = Output::default();
        while conn.buf.len() >= HEADER {
            let command = u16::from_le_bytes([conn.buf[0], conn.buf[1]]);
            let len = u16::from_le_bytes([conn.buf[2], conn.buf[3]]) as usize;
            if len > MAX_DATA {
                let detail = json!({"command": command, "reason": "bad_length", "length": len});
                events.emit(NAME, conn.id, "drop", detail, "dropped");
                out.close = Some("bad_length");
                conn.buf.clear();
                break;
            }
            if conn.buf.len() < HEADER + len {
                break;
            }
            let frame: Vec<u8> = conn.buf.drain(..HEADER + len).collect();
            match self.handle(conn, &frame, events) {
                Answer::Reply(reply) => out.replies.push(reply),
                Answer::Silent => {}
                Answer::Close(reason) => {
                    out.close = Some(reason);
                    conn.buf.clear();
                    break;
                }
            }
        }
        out
    }

    /// Answers one complete frame, header and data.
    fn handle(&self, conn: &mut Conn, frame: &[u8], events: &Events) -> Answer {
        let Some(h) = Header::parse(frame) else {
            return Answer::Silent;
        };
        let data = &frame[HEADER..];
        if h.status != 0 || h.options != 0 {
            // A receiver discards, without a reply, a request whose status or options are not zero.
            let detail = json!({"command": h.command, "reason": "status_or_options", "status": h.status,
                                "options": h.options});
            events.emit(NAME, conn.id, "drop", detail, "dropped");
            return Answer::Silent;
        }
        match h.command {
            NOP => {
                events.emit(NAME, conn.id, "nop", json!({"length": data.len()}), "ok");
                Answer::Silent
            }
            LIST_IDENTITY => self.list_identity(conn, &h, events),
            REGISTER_SESSION => self.register_session(conn, &h, data, events),
            UNREGISTER_SESSION => {
                let mut detail = json!({"session": h.session});
                if conn.session == Some(h.session) {
                    conn.session = None;
                    events.emit(NAME, conn.id, "unregister_session", detail, "ok");
                    // The receiver closes the connection and sends no reply.
                    Answer::Close("unregistered")
                } else {
                    detail["encap_status"] = json!(ENCAP_INVALID_SESSION);
                    events.emit(NAME, conn.id, "unregister_session", detail, &encap(ENCAP_INVALID_SESSION));
                    Answer::Reply(h.reply(h.session, ENCAP_INVALID_SESSION, &[]))
                }
            }
            SEND_RR_DATA => self.send_rr_data(conn, &h, data, events),
            command => {
                // ListServices, ListInterfaces, SendUnitData and the rest: connected messaging and the
                // other services are not simulated.
                let detail = json!({"command": command, "encap_status": ENCAP_UNSUPPORTED_COMMAND});
                events.emit(NAME, conn.id, "unsupported_command", detail, &encap(ENCAP_UNSUPPORTED_COMMAND));
                Answer::Reply(h.reply(h.session, ENCAP_UNSUPPORTED_COMMAND, &[]))
            }
        }
    }

    fn register_session(&self, conn: &mut Conn, h: &Header, data: &[u8], events: &Events) -> Answer {
        let mut r = Reader::new(data);
        let (version, options) = (r.le_u16(), r.le_u16());
        let (status, session) = if data.len() != 4 {
            (ENCAP_INVALID_LENGTH, 0)
        } else if version != Some(1) || options != Some(0) {
            (ENCAP_UNSUPPORTED_VERSION, 0)
        } else if let Some(open) = conn.session {
            // One session per connection: a second RegisterSession is refused, with the open handle.
            (ENCAP_UNSUPPORTED_COMMAND, open)
        } else {
            let handle = conn.session_handle();
            conn.session = Some(handle);
            (0, handle)
        };
        let mut detail = json!({"session": session, "version": version, "options": options});
        let result = if status == 0 {
            "ok".to_string()
        } else {
            detail["encap_status"] = json!(status);
            encap(status)
        };
        events.emit(NAME, conn.id, "register_session", detail, &result);
        // Always 28 bytes, errors included: the client reads exactly 28 before it looks at any of them
        // (Client.kt:100-114). The data is the protocol version this device supports.
        Answer::Reply(h.reply(session, status, &[1, 0, 0, 0]))
    }

    /// ListIdentity: one CIP Identity item.
    fn list_identity(&self, conn: &Conn, h: &Header, events: &Events) -> Answer {
        let id = &self.profile.identity;
        let (ip, port) = match conn.local {
            Some(SocketAddr::V4(a)) => (a.ip().octets(), a.port()),
            _ => ([0; 4], 44818),
        };
        let mut item = Vec::new();
        item.extend_from_slice(&1u16.to_le_bytes());
        // The socket address is a struct sockaddr_in, big-endian.
        item.extend_from_slice(&2u16.to_be_bytes());
        item.extend_from_slice(&port.to_be_bytes());
        item.extend_from_slice(&ip);
        item.extend_from_slice(&[0; 8]);
        item.extend_from_slice(&VENDOR_ID.to_le_bytes());
        item.extend_from_slice(&DEVICE_TYPE.to_le_bytes());
        item.extend_from_slice(&id.product_code.to_le_bytes());
        item.extend_from_slice(&[id.revision.0, id.revision.1]);
        item.extend_from_slice(&IDENTITY_STATUS.to_le_bytes());
        item.extend_from_slice(&id.serial.to_le_bytes());
        item.push(id.product_name.len() as u8);
        item.extend_from_slice(id.product_name.as_bytes());
        item.push(IDENTITY_STATE);
        let mut data = Vec::with_capacity(6 + item.len());
        data.extend_from_slice(&1u16.to_le_bytes());
        data.extend_from_slice(&CPF_IDENTITY.to_le_bytes());
        data.extend_from_slice(&(item.len() as u16).to_le_bytes());
        data.extend_from_slice(&item);
        events.emit(NAME, conn.id, "list_identity", json!({"product_code": id.product_code}), "ok");
        Answer::Reply(h.reply(h.session, 0, &data))
    }

    fn send_rr_data(&self, conn: &Conn, h: &Header, data: &[u8], events: &Events) -> Answer {
        if conn.session != Some(h.session) {
            let detail = json!({"session": h.session, "encap_status": ENCAP_INVALID_SESSION});
            events.emit(NAME, conn.id, "send_rr_data", detail, &encap(ENCAP_INVALID_SESSION));
            // Header only: the client checks the status before it looks past byte 24 (Client.kt:364-369).
            return Answer::Reply(h.reply(h.session, ENCAP_INVALID_SESSION, &[]));
        }
        let Some(request) = unconnected_data(data) else {
            let detail = json!({"session": h.session, "encap_status": ENCAP_INCORRECT_DATA});
            events.emit(NAME, conn.id, "send_rr_data", detail, &encap(ENCAP_INCORRECT_DATA));
            return Answer::Reply(h.reply(h.session, ENCAP_INCORRECT_DATA, &[]));
        };
        let (op, mut detail, fault, cip) = self.cip(request);
        detail["session"] = json!(h.session);
        let status = match fault {
            Some(f) => f.report(&mut detail),
            None => "ok".to_string(),
        };
        events.emit(NAME, conn.id, op, detail, &status);
        Answer::Reply(h.reply(h.session, 0, &rr_data(&cip)))
    }

    /// One CIP request. The PCCC object (class 0x67, instance 1) is the only object a client reaches
    /// and Execute PCCC its only service; as in a CIP message router, the path is resolved before the
    /// service is looked at.
    fn cip(&self, request: &[u8]) -> CipOutcome {
        let op = "cip_request";
        let mut r = Reader::new(request);
        let service = r.u8().unwrap_or(0);
        let path = r.u8().and_then(|words| r.bytes(2 * words as usize)).and_then(logical_path);
        let Some((class, instance)) = path else {
            return cip_fault(op, json!({"service": service}), service, CIP_PATH_SEGMENT_ERROR);
        };
        let detail = json!({"service": service, "class": class, "instance": instance});
        if (class, instance) != (PCCC_CLASS, 1) {
            return cip_fault(op, detail, service, CIP_PATH_DESTINATION_UNKNOWN);
        }
        if service != EXECUTE_PCCC {
            return cip_fault(op, detail, service, CIP_SERVICE_NOT_SUPPORTED);
        }
        self.execute_pccc(r.rest())
    }

    /// Execute PCCC: the requestor ID (its length byte included, at least 7 bytes), then the PCCC
    /// command: CMD, STS, TNS and the function's data. The reply echoes the requestor ID and the TNS;
    /// the client checks the ID's length byte, the reply CMD 0x4F, STS and TNS (Client.kt:336-362).
    fn execute_pccc(&self, request: &[u8]) -> CipOutcome {
        let mut r = Reader::new(request);
        let id_len = request.first().copied().unwrap_or(0) as usize;
        let requestor = if id_len >= 7 { r.bytes(id_len) } else { None };
        let (Some(requestor), Some(cmd), Some(_sts), Some(tns)) = (requestor, r.u8(), r.u8(), r.bytes(2)) else {
            return cip_fault("execute_pccc", json!({}), EXECUTE_PCCC, CIP_NOT_ENOUGH_DATA);
        };
        let (op, mut detail, result) = self.pccc(cmd, &mut r);
        detail["cmd"] = json!(cmd);
        detail["tns"] = json!(u16::from_le_bytes([tns[0], tns[1]]));
        let mut reply = requestor.to_vec();
        reply.push(cmd | 0x40);
        let fault = match result {
            Ok(data) => {
                reply.push(0);
                reply.extend_from_slice(tns);
                reply.extend_from_slice(&data);
                None
            }
            Err((sts, ext)) => {
                reply.push(sts);
                reply.extend_from_slice(tns);
                reply.extend(ext);
                Some(Fault::Sts(sts, ext))
            }
        };
        (op, detail, fault, cip_reply(EXECUTE_PCCC, 0, &reply))
    }

    /// The PCCC command behind the TNS. CMD 0x0F / FNC 0xA2 is the only one simulated; every other
    /// command or function, writes included, is answered STS 0x10 (illegal command or format).
    fn pccc(&self, cmd: u8, r: &mut Reader) -> (&'static str, Value, Result<Vec<u8>, Sts>) {
        let fnc = if cmd == CMD_TYPED { r.u8() } else { None };
        if fnc != Some(FNC_TYPED_READ) || !self.profile.typed_reads {
            return ("pccc_command", json!({"fnc": fnc}), Err((STS_ILLEGAL_COMMAND, None)));
        }
        self.typed_read(r)
    }

    /// FNC 0xA2, protected typed logical read with three address fields: byte size, file number, file
    /// type, element and sub-element. It returns exactly `size` bytes from `element·S + sub·2` of the
    /// file, so one read can span elements, as the client's merged reads do (Client.kt:473-495).
    fn typed_read(&self, r: &mut Reader) -> (&'static str, Value, Result<Vec<u8>, Sts>) {
        let op = "typed_read";
        let (Some(size), Some(file), Some(code), Some(element), Some(sub)) =
            (r.u8(), number(r), r.u8(), number(r), number(r))
        else {
            return (op, json!({}), Err((STS_ILLEGAL_COMMAND, None)));
        };
        let detail = json!({"size": size, "file": file, "type": code, "element": element, "sub": sub});
        if r.remaining() > 0 {
            return (op, detail, Err((STS_ILLEGAL_COMMAND, None)));
        }
        // One snapshot per request: the read lock is taken once.
        let img = self.image.read().unwrap_or_else(|e| e.into_inner());
        let Some(f) = img.file(file).filter(|f| f.kind.code() == code) else {
            return (op, detail, Err((STS_EXT, Some(EXT_NOT_USABLE))));
        };
        let start = element as usize * f.kind.element_bytes() + sub as usize * 2;
        match f.bytes.get(start..start + size as usize) {
            Some(data) => (op, detail, Ok(data.to_vec())),
            None => (op, detail, Err((STS_EXT, Some(EXT_BEYOND_FILE)))),
        }
    }

    pub fn print_map(&self) -> Value {
        let kind = |number: u16| self.profile.files.iter().find(|f| f.0 == number).map(|f| f.1);
        let mut rows = Vec::new();
        for tag in statics() {
            if let Some(k) = kind(tag.file) {
                rows.push(json!({
                    "address": format!("{}{}:{}", k.prefix(), tag.file, tag.element), "tag": tag.tag,
                    "type": tag.kind, "value": tag.enc.shown(),
                }));
            }
        }
        for (file, address, tag, enc) in DYNAMIC {
            if kind(*file).is_some() {
                rows.push(json!({"address": address, "tag": tag, "type": enc, "value": "dynamic"}));
            }
        }
        let files: Vec<Value> = self
            .profile
            .files
            .iter()
            .map(|(number, k, elements)| {
                json!({"file": format!("{}{number}", k.prefix()), "type": format!("0x{:02X}", k.code()),
                       "element_bytes": k.element_bytes(), "elements": elements})
            })
            .collect();
        let id = &self.profile.identity;
        json!({
            "protocol": NAME, "profile": self.profile.name, "device": self.profile.title,
            "typed_reads": self.profile.typed_reads,
            "identity": {"vendor": VENDOR_ID, "device_type": DEVICE_TYPE, "product_code": id.product_code,
                         "revision": format!("{}.{:03}", id.revision.0, id.revision.1),
                         "serial": format!("0x{:08X}", id.serial), "product_name": id.product_name},
            "files": files,
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
        conn.local = stream.local_addr().ok();
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

/// The CIP request in a SendRRData: interface handle and timeout, then a common packet format whose
/// first items are a Null Address and an Unconnected Data item. Further items (socket address info)
/// are skipped, and the items must fill the data exactly.
fn unconnected_data(data: &[u8]) -> Option<&[u8]> {
    let mut r = Reader::new(data);
    r.skip(6)?;
    let count = r.le_u16()?;
    if count < 2 {
        return None;
    }
    let (address_type, address_len) = (r.le_u16()?, r.le_u16()?);
    r.skip(address_len as usize)?;
    let (data_type, data_len) = (r.le_u16()?, r.le_u16()?);
    let request = r.bytes(data_len as usize)?;
    for _ in 2..count {
        r.skip(2)?;
        let len = r.le_u16()?;
        r.skip(len as usize)?;
    }
    let unconnected = address_type == CPF_NULL_ADDRESS && address_len == 0 && data_type == CPF_UNCONNECTED_DATA;
    (unconnected && !request.is_empty() && r.remaining() == 0).then_some(request)
}

/// The class and instance of a path of logical segments, each 8, 16 or 32 bits (the wider ones
/// after a pad byte).
fn logical_path(path: &[u8]) -> Option<(u32, u32)> {
    let mut r = Reader::new(path);
    let (mut class, mut instance) = (None, None);
    while r.remaining() > 0 {
        let segment = r.u8()?;
        let value = match segment & 0x03 {
            0 => r.u8()? as u32,
            1 => r.skip(1).and_then(|_| r.le_u16())? as u32,
            2 => r.skip(1).and_then(|_| r.le_u32())?,
            _ => return None,
        };
        match segment & 0xFC {
            0x20 => class = Some(value),
            0x24 => instance = Some(value),
            _ => return None,
        }
    }
    Some((class?, instance?))
}

/// A file, element or sub-element number: one byte, or 0xFF then a little-endian u16 for 255 and up
/// (Address.kt:94-99).
fn number(r: &mut Reader) -> Option<u16> {
    match r.u8()? {
        0xFF => r.le_u16(),
        n => Some(n as u16),
    }
}

/// A CIP reply: the service with bit 7 set, a reserved byte, the general status, no additional status.
fn cip_reply(service: u8, status: u8, data: &[u8]) -> Vec<u8> {
    let mut out = vec![service | 0x80, 0, status, 0];
    out.extend_from_slice(data);
    out
}

/// A CIP error. Its 4-byte CIP reply makes the SendRRData reply 44 bytes, the shortest the client
/// can check without an index error (Client.kt:371).
fn cip_fault(op: &'static str, detail: Value, service: u8, status: u8) -> CipOutcome {
    (op, detail, Some(Fault::Cip(status)), cip_reply(service, status, &[]))
}

/// The data of a SendRRData reply: interface handle 0 and timeout 0, then a Null Address item and an
/// Unconnected Data item with the CIP reply. The client requires the interface handle and the address
/// item's length to be 0 (Client.kt:377-381).
fn rr_data(cip: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(16 + cip.len());
    out.extend_from_slice(&0u32.to_le_bytes());
    out.extend_from_slice(&0u16.to_le_bytes());
    out.extend_from_slice(&2u16.to_le_bytes());
    out.extend_from_slice(&CPF_NULL_ADDRESS.to_le_bytes());
    out.extend_from_slice(&0u16.to_le_bytes());
    out.extend_from_slice(&CPF_UNCONNECTED_DATA.to_le_bytes());
    out.extend_from_slice(&(cip.len() as u16).to_le_bytes());
    out.extend_from_slice(cip);
    out
}
