// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! S7 golden frames: request bytes exactly as SFC's s7 adapter sends them through PLC4X 0.9.1
//! (S7ProtocolLogic: COTP CR, Setup Communication, SZL 0x0011 while ControllerType is unset, Read Var from
//! PDU reference 10 upward; S7Controller.kt:132-141, 369-446), expected replies from the default map.
//! G1–G11 are the S7 spec's section 6, except G9, which needs the PUT/GET-off fault switch.
#![cfg(feature = "s7")]

use omni_plc_sim::core::codec::{hex, unhex};
use omni_plc_sim::core::config::SimConfig;
use omni_plc_sim::core::engine::{Engine, Settings};
use omni_plc_sim::core::events::Events;
use omni_plc_sim::protocols::s7::{Action, Conn, Server};

/// G1: SFC's defaults, LocalRack/LocalSlot 1/1, RemoteRack/RemoteSlot 0/0, PduSize 1024: called TSAP
/// 0x0100, calling TSAP 0x0311, TPDU size 1024.
const CR: &str = "03 00 00 16 11 E0 00 00 00 0F 00 C2 02 01 00 C1 02 03 11 C0 01 0A";
const CC: &str = "03 00 00 16 11 D0 00 0F 00 01 00 C0 01 0A C1 02 03 11 C2 02 01 00";
/// RemoteSlot 2 and 3, for the S7-300 and S7-400.
const CR_SLOT2: &str = "03 00 00 16 11 E0 00 00 00 0F 00 C2 02 01 02 C1 02 03 11 C0 01 0A";
const CR_SLOT3: &str = "03 00 00 16 11 E0 00 00 00 0F 00 C2 02 01 03 C1 02 03 11 C0 01 0A";
/// G2: Setup Communication, AmQ 8/8, PDU 1008 (PduSize − 16).
const SETUP: &str = "03 00 00 19 02 F0 81 32 01 00 00 00 00 00 08 00 00 F0 00 00 08 00 08 03 F0";
const SETUP_S7_1500: &str = "03 00 00 1B 02 F0 80 32 03 00 00 00 00 00 08 00 00 00 00 F0 00 00 03 00 03 03 C0";
/// G4: SZL 0x0011 index 0.
const SZL: &str = "03 00 00 21 02 F0 82 32 07 00 00 00 01 00 08 00 08 00 01 12 04 11 44 01 00 FF 09 00 04 00 11 00 00";
const SZL_S7_1500: &str = "
03 00 00 7D 02 F0 80 32 07 00 00 00 01 00 0C 00 60 00 01 12 08 12 84 01 01 00 00 00 00
FF 09 00 5C 00 11 00 00 00 1C 00 03
00 01 36 45 53 37 20 35 31 36 2D 33 41 4E 30 31 2D 30 41 42 30 20 00 00 00 01 00 01
00 06 36 45 53 37 20 35 31 36 2D 33 41 4E 30 31 2D 30 41 42 30 20 00 00 00 01 00 01
00 07 20 20 20 20 20 20 20 20 20 20 20 20 20 20 20 20 20 20 20 20 00 00 56 02 08 03";

/// G5: `%DB1.DBW4:INT`, reference 10.
const G5: &str = "03 00 00 1F 02 F0 8A 32 01 00 00 00 0A 00 0E 00 00 04 01 12 0A 10 05 00 01 00 01 84 00 00 20";
const G5_REPLY: &str = "03 00 00 1B 02 F0 80 32 03 00 00 00 0A 00 02 00 06 00 00 04 01 FF 05 00 10 CF C7";
/// G6: BOOL, BYTE, REAL and STRING(16), which SFC reads as USINT[16] at offset 86; odd items are padded.
const G6: &str = "
03 00 00 43 02 F0 8B 32 01 00 00 00 0B 00 32 00 00 04 04
12 0A 10 01 00 01 00 01 84 00 00 00 12 0A 10 02 00 01 00 01 84 00 00 08
12 0A 10 08 00 01 00 01 84 00 00 B0 12 0A 10 02 00 10 00 01 84 00 02 B0";
const G6_REPLY: &str = "
03 00 00 3D 02 F0 80 32 03 00 00 00 0B 00 02 00 28 00 00 04 04
FF 03 00 01 01 00 FF 04 00 08 A5 00 FF 07 00 04 46 40 E6 00
FF 04 00 80 53 46 43 2D 53 49 4D 00 00 00 00 00 00 00 00 00";
/// G7: LINT as SINT[8], TIME as BYTE[4], M0.0, DATE as BYTE[2].
const G7: &str = "
03 00 00 43 02 F0 8C 32 01 00 00 00 0C 00 32 00 00 04 04
12 0A 10 02 00 08 00 01 84 00 01 10 12 0A 10 02 00 04 00 01 84 00 01 90
12 0A 10 01 00 01 00 00 83 00 00 00 12 0A 10 02 00 02 00 01 84 00 01 B0";
const G7_REPLY: &str = "
03 00 00 35 02 F0 80 32 03 00 00 00 0C 00 02 00 20 00 00 04 04
FF 04 00 40 FF FF FE E0 8E 04 FB 35 FF 04 00 20 00 00 04 D2 FF 03 00 01 01 00 FF 04 00 10 30 BD";
/// G8: `int`, `%DB2.DBW0:INT` (no DB2) and `%DB1.DBW300:INT` (past the end of DB1).
const G8: &str = "
03 00 00 37 02 F0 8D 32 01 00 00 00 0D 00 26 00 00 04 03
12 0A 10 05 00 01 00 01 84 00 00 20 12 0A 10 05 00 01 00 02 84 00 00 00 12 0A 10 05 00 01 00 01 84 00 09 60";
const G8_REPLY: &str = "
03 00 00 23 02 F0 80 32 03 00 00 00 0D 00 02 00 0E 00 00 04 03
FF 05 00 10 CF C7 0A 00 00 00 05 00 00 00";
/// G10: INT[4], REAL[4], DINT, UDINT.
const G10: &str = "
03 00 00 43 02 F0 8F 32 01 00 00 00 0F 00 32 00 00 04 04
12 0A 10 05 00 04 00 01 84 00 04 50 12 0A 10 08 00 04 00 01 84 00 04 90
12 0A 10 07 00 01 00 01 84 00 00 50 12 0A 10 07 00 01 00 01 84 00 00 70";
const G10_REPLY: &str = "
03 00 00 45 02 F0 80 32 03 00 00 00 0F 00 02 00 30 00 00 04 04
FF 05 00 40 00 01 FF FE 01 2C 80 00 FF 07 00 10 3F 00 00 00 BF A0 00 00 44 80 00 00 BC 00 00 00
FF 05 00 20 B6 69 FD 2E FF 05 00 20 B2 D0 5E 00";
/// G11: CHAR, WCHAR as SINT[2], TIME_OF_DAY as BYTE[4], DATE_AND_TIME as SINT[8].
const G11: &str = "
03 00 00 43 02 F0 90 32 01 00 00 00 10 00 32 00 00 04 04
12 0A 10 03 00 01 00 01 84 00 02 80 12 0A 10 02 00 02 00 01 84 00 02 90
12 0A 10 02 00 04 00 01 84 00 01 C0 12 0A 10 02 00 08 00 01 84 00 01 E0";
const G11_REPLY: &str = "
03 00 00 35 02 F0 80 32 03 00 00 00 10 00 02 00 20 00 00 04 04
FF 09 00 01 53 00 FF 04 00 10 00 57 FF 04 00 20 01 D3 26 D2 FF 04 00 40 24 02 29 13 45 30 12 35";

/// Spec §4.1: DB1 bytes 0–207; the rest of the 256 bytes is 0.
const DB1_STATIC: &str = "
01 A5 9C C8 CF C7 D4 31 D4 31 B6 69 FD 2E B2 D0 5E 00 B2 D0 5E 00 46 40 E6 00 C0 F8 1C D7 00 00
00 00 FF FF FE E0 8E 04 FB 35 00 00 0B 3A 73 CE 2F F2 00 00 04 D2 30 BD 01 D3 26 D2 24 02 29 13
45 30 12 35 07 E8 02 1D 05 0D 2D 1E 07 5B CD 15 53 C4 00 57 10 07 53 46 43 2D 53 49 4D 00 00 00
00 00 00 00 00 00 00 10 00 07 00 53 00 46 00 43 00 2D 00 53 00 49 00 4D 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 01 FF FE 01 2C 80 00 3F 00 00 00 BF A0 00 00 44 80 00 00 BC 00
00 00 00 00 00 00 59 68 2F 00 01 23 45 67 89 AB CD EF 00 00 FF FF FF FF FF FF FF FF FF FF FB 2E
10 05 47 72 FC DF 65 00 00 00 00 00 00 00 00 00";

fn feed(server: &Server, conn: &mut Conn, request: &str) -> Vec<String> {
    let out = server.feed(conn, &unhex(request), &Events::disabled());
    assert_eq!(out.close, None, "connection closed on {request}");
    out.replies.iter().map(|r| hex(r)).collect()
}

fn one(server: &Server, conn: &mut Conn, request: &str) -> String {
    let replies = feed(server, conn, request);
    assert_eq!(replies.len(), 1, "{request}");
    replies[0].clone()
}

/// The connection ends without a reply; the reason.
fn closes(server: &Server, conn: &mut Conn, request: &str) -> &'static str {
    let out = server.feed(conn, &unhex(request), &Events::disabled());
    assert!(out.replies.is_empty(), "replied to {request}");
    out.close.unwrap_or_else(|| panic!("still open after {request}"))
}

fn h(frame: &str) -> String {
    hex(&unhex(frame))
}

fn s7_1500() -> Server {
    Server::new("s7-1500").unwrap()
}

/// Connection 1 after CR, Setup and SZL, the way PLC4X opens it.
fn connected(server: &Server, cr: &str) -> Conn {
    let mut conn = Conn::new(1);
    one(server, &mut conn, cr);
    one(server, &mut conn, SETUP);
    one(server, &mut conn, SZL);
    conn
}

#[test]
fn g1_g2_g4_handshake() {
    let s = s7_1500();
    let mut conn = Conn::new(1);
    assert_eq!(one(&s, &mut conn, CR), h(CC));
    assert_eq!(one(&s, &mut conn, SETUP), h(SETUP_S7_1500));
    assert_eq!(one(&s, &mut conn, SZL), h(SZL_S7_1500));
}

#[test]
fn g3_setup_s7_300() {
    let s = Server::new("s7-300").unwrap();
    let mut conn = Conn::new(1);
    assert_eq!(one(&s, &mut conn, CR_SLOT2), h("03 00 00 16 11 D0 00 0F 00 01 00 C0 01 0A C1 02 03 11 C2 02 01 02"));
    assert_eq!(
        one(&s, &mut conn, SETUP),
        h("03 00 00 1B 02 F0 80 32 03 00 00 00 00 00 08 00 00 00 00 F0 00 00 01 00 01 00 F0")
    );
}

#[test]
fn g5_single_int() {
    let s = s7_1500();
    assert_eq!(one(&s, &mut connected(&s, CR), G5), h(G5_REPLY));
}

#[test]
fn g6_bool_byte_real_string_with_padding() {
    let s = s7_1500();
    assert_eq!(one(&s, &mut connected(&s, CR), G6), h(G6_REPLY));
}

#[test]
fn g7_raw_lint_time_marker_bit_date() {
    let s = s7_1500();
    assert_eq!(one(&s, &mut connected(&s, CR), G7), h(G7_REPLY));
}

#[test]
fn g8_item_errors() {
    let s = s7_1500();
    assert_eq!(one(&s, &mut connected(&s, CR), G8), h(G8_REPLY));
}

#[test]
fn g10_arrays_dint_udint() {
    let s = s7_1500();
    assert_eq!(one(&s, &mut connected(&s, CR), G10), h(G10_REPLY));
}

#[test]
fn g11_char_wchar_tod_dt() {
    let s = s7_1500();
    assert_eq!(one(&s, &mut connected(&s, CR), G11), h(G11_REPLY));
}

#[test]
fn whole_session_in_one_buffer_and_byte_by_byte() {
    let s = s7_1500();
    let input: Vec<u8> = [CR, SETUP, SZL, G5, G6, G7].iter().flat_map(|f| unhex(f)).collect();
    let want: Vec<Vec<u8>> =
        [CC, SETUP_S7_1500, SZL_S7_1500, G5_REPLY, G6_REPLY, G7_REPLY].iter().map(|f| unhex(f)).collect();
    let whole = s.feed(&mut Conn::new(1), &input, &Events::disabled());
    assert_eq!(whole.close, None);
    assert_eq!(whole.replies, want);
    let mut conn = Conn::new(1);
    let mut split = Vec::new();
    for b in &input {
        let out = s.feed(&mut conn, &[*b], &Events::disabled());
        assert_eq!(out.close, None);
        split.extend(out.replies);
    }
    assert_eq!(split, want);
}

#[test]
fn pipelined_reads_are_answered_in_order() {
    let s = s7_1500();
    let replies = feed(&s, &mut connected(&s, CR), &format!("{G8} {G5} {G11} {G10}"));
    assert_eq!(replies, vec![h(G8_REPLY), h(G5_REPLY), h(G11_REPLY), h(G10_REPLY)]);
}

#[test]
fn a_partial_frame_waits_for_its_declared_length() {
    let s = s7_1500();
    let mut conn = connected(&s, CR);
    let frame = unhex(G6);
    let first = s.feed(&mut conn, &frame[..20], &Events::disabled());
    assert!(first.replies.is_empty() && first.close.is_none());
    let rest = s.feed(&mut conn, &frame[20..], &Events::disabled());
    assert_eq!((rest.replies, rest.close), (vec![unhex(G6_REPLY)], None));
}

#[test]
fn db1_static_block() {
    let s = s7_1500();
    // %DB1:0:BYTE[256], reference 49.
    let request = "03 00 00 1F 02 F0 B1 32 01 00 00 00 31 00 0E 00 00 04 01 12 0A 10 02 01 00 00 01 84 00 00 00";
    let want = format!("03 00 01 19 02 F0 80 32 03 00 00 00 31 00 02 01 04 00 00 04 01 FF 04 08 00 {DB1_STATIC} {}",
                       "00 ".repeat(48));
    assert_eq!(one(&s, &mut connected(&s, CR), request), h(&want));
}

#[test]
fn marker_input_output_static_bytes() {
    let s = s7_1500();
    // MB0..27, IB0..7, QB0..7; the marker and input mirrors stay 0 until the first scan.
    let request = "
03 00 00 37 02 F0 B2 32 01 00 00 00 32 00 26 00 00 04 03
12 0A 10 02 00 1C 00 00 83 00 00 00 12 0A 10 02 00 08 00 00 81 00 00 00 12 0A 10 02 00 08 00 00 82 00 00 00";
    let reply = "
03 00 00 4D 02 F0 80 32 03 00 00 00 32 00 02 00 38 00 00 04 03
FF 04 00 E0 A5 00 CF C7 46 40 E6 00 00 00 00 00 00 00 00 00 00 00 00 00 3F F8 00 00 00 00 00 00
FF 04 00 40 81 00 30 39 3F C0 00 00 FF 04 00 40 3C 00 FF FE BE 80 00 00";
    assert_eq!(one(&s, &mut connected(&s, CR), request), h(reply));
}

#[test]
fn dynamic_block_and_mirrors_come_from_one_scan() {
    let s = s7_1500();
    let settings = Settings { cycle_ms: 10, clock_base_ms: 0 };
    let mut engine = Engine::new(&SimConfig::default(), settings, vec![s.image()]).unwrap();
    // Scan 25: t = 0.25 s, sine = 100, both blinks in their first half period.
    let scan = engine.apply(25);
    assert!((scan.v.sine - 100.0).abs() < 1e-9 && scan.v.blink_1hz && scan.v.blink_5hz);
    // DB100: DINT 0, LREAL 4 as BYTE[8], REAL 12, INT 68, BOOL 70.0 and 70.1; MD8, MD12, M16.0, I8.0.
    let request = "
03 00 00 8B 02 F0 B0 32 01 00 00 00 30 00 7A 00 00 04 0A
12 0A 10 07 00 01 00 64 84 00 00 00 12 0A 10 02 00 08 00 64 84 00 00 20 12 0A 10 08 00 01 00 64 84 00 00 60
12 0A 10 05 00 01 00 64 84 00 02 20 12 0A 10 01 00 01 00 64 84 00 02 30 12 0A 10 01 00 01 00 64 84 00 02 31
12 0A 10 07 00 01 00 00 83 00 00 40 12 0A 10 08 00 01 00 00 83 00 00 60 12 0A 10 01 00 01 00 00 83 00 00 80
12 0A 10 01 00 01 00 00 81 00 00 40";
    let reply = "
03 00 00 5E 02 F0 80 32 03 00 00 00 30 00 02 00 49 00 00 04 0A
FF 05 00 20 00 00 00 19 FF 04 00 40 3F D0 00 00 00 00 00 00 FF 07 00 04 42 C8 00 00 FF 05 00 10 27 10
FF 03 00 01 01 00 FF 03 00 01 01 00 FF 05 00 20 00 00 00 19 FF 07 00 04 42 C8 00 00 FF 03 00 01 01 00
FF 03 00 01 01";
    assert_eq!(one(&s, &mut connected(&s, CR), request), h(reply));
}

#[test]
fn every_profile_identifies_its_family_to_plc4x() {
    // PLC4X's controller type is the character after the first space of record 0x0001's order number.
    for (profile, cr, family) in [("s7-300", CR_SLOT2, '3'), ("s7-400", CR_SLOT3, '4'), ("s7-1200", CR, '2'),
                                  ("s7-1500", CR, '5')] {
        let s = Server::new(profile).unwrap();
        let reply = {
            let mut conn = Conn::new(1);
            one(&s, &mut conn, cr);
            one(&s, &mut conn, SETUP);
            unhex(&one(&s, &mut conn, SZL))
        };
        // After TPKT, COTP, the UserData header, its parameter and the 12-byte data header.
        let record = &reply[41..69];
        let mlfb = String::from_utf8_lossy(&record[2..22]).to_string();
        assert_eq!(record[..2], [0x00, 0x01], "{profile}");
        assert!(mlfb.len() == 20 && mlfb.starts_with("6ES7 "), "{profile}: {mlfb}");
        assert_eq!(mlfb.chars().nth(5), Some(family), "{profile}: {mlfb}");
    }
}

#[test]
fn setup_negotiates_down_to_the_profile() {
    for (profile, cr, setup) in [
        ("s7-400", CR_SLOT3, "03 00 00 1B 02 F0 80 32 03 00 00 00 00 00 08 00 00 00 00 F0 00 00 08 00 08 01 E0"),
        ("s7-1200", CR, "03 00 00 1B 02 F0 80 32 03 00 00 00 00 00 08 00 00 00 00 F0 00 00 03 00 03 00 F0"),
    ] {
        let s = Server::new(profile).unwrap();
        let mut conn = Conn::new(1);
        one(&s, &mut conn, cr);
        assert_eq!(one(&s, &mut conn, SETUP), h(setup), "{profile}");
    }
    // AmQ 0 is raised to 1: PLC4X would never send a request with no slot in flight.
    let s = s7_1500();
    let mut conn = Conn::new(1);
    one(&s, &mut conn, CR);
    assert_eq!(
        one(&s, &mut conn, "03 00 00 19 02 F0 81 32 01 00 00 00 00 00 08 00 00 F0 00 00 00 00 00 03 F0"),
        h("03 00 00 1B 02 F0 80 32 03 00 00 00 00 00 08 00 00 00 00 F0 00 00 01 00 01 03 C0")
    );
}

#[test]
fn szl_001c_component_identification() {
    let s = Server::new("s7-300").unwrap();
    let mut conn = connected(&s, CR_SLOT2);
    let reply = unhex(&one(
        &s,
        &mut conn,
        "03 00 00 21 02 F0 83 32 07 00 00 00 02 00 08 00 08 00 01 12 04 11 44 01 00 FF 09 00 04 00 1C 00 00",
    ));
    // Six 34-byte records: a 238-byte PDU, inside the S7-300's 240.
    let head = "03 00 00 F5 02 F0 80 32 07 00 00 00 02 00 0C 00 D8 00 01 12 08 12 84 01 01 00 00 00 00 \
                FF 09 00 D4 00 1C 00 00 00 22 00 06";
    assert_eq!(hex(&reply[..41]), h(head));
    // The offsets snap7's GetCpuInfo reads: station name 2, module name 36, copyright 104, serial 138,
    // module type 172.
    let records = &reply[41..];
    let text = |at: usize, n: usize| String::from_utf8_lossy(&records[at..at + n]).trim_end_matches('\0').to_string();
    assert_eq!(text(2, 24), "SIMATIC 300(1)");
    assert_eq!(text(36, 24), "CPU 315-2 PN/DP");
    assert_eq!(text(104, 26), "Original Siemens Equipment");
    assert_eq!(text(138, 24), "S C-SIM000000315");
    assert_eq!(text(172, 32), "CPU 315-2 PN/DP");
}

#[test]
fn item_error_order_and_timers() {
    let s = s7_1500();
    // Syntax 0x11; WCHAR's transport size 0x13; BIT count 2; INT at bit 4.1; area P; INT at DB1.255; BYTE on T;
    // timer T0; COUNTER on DB1; DATE_AND_TIME at DB1.60.
    let request = "
03 00 00 8B 02 F0 A0 32 01 00 00 00 20 00 7A 00 00 04 0A
12 0A 11 05 00 01 00 01 84 00 00 20 12 0A 10 13 00 01 00 01 84 00 02 90 12 0A 10 01 00 02 00 01 84 00 00 00
12 0A 10 05 00 01 00 01 84 00 00 21 12 0A 10 05 00 01 00 00 80 00 00 00 12 0A 10 05 00 01 00 01 84 00 07 F8
12 0A 10 02 00 01 00 00 1D 00 00 00 12 0A 10 1D 00 01 00 00 1D 00 00 00 12 0A 10 1C 00 01 00 01 84 00 00 00
12 0A 10 0F 00 01 00 01 84 00 01 E0";
    let reply = "
03 00 00 47 02 F0 80 32 03 00 00 00 20 00 02 00 32 00 00 04 0A
05 00 00 00 06 00 00 00 05 00 00 00 05 00 00 00 05 00 00 00 05 00 00 00 06 00 00 00
FF 09 00 02 00 00 06 00 00 00 FF 04 00 40 24 02 29 13 45 30 12 35";
    assert_eq!(one(&s, &mut connected(&s, CR), request), h(reply));
}

#[test]
fn s7_1200_has_no_date_and_time_timers_or_counters() {
    let s = Server::new("s7-1200").unwrap();
    // DATE_AND_TIME at DB1.60, T0, C0.
    let request = "
03 00 00 37 02 F0 A1 32 01 00 00 00 21 00 26 00 00 04 03
12 0A 10 0F 00 01 00 01 84 00 01 E0 12 0A 10 1D 00 01 00 00 1D 00 00 00 12 0A 10 1C 00 01 00 00 1C 00 00 00";
    let reply = "03 00 00 21 02 F0 80 32 03 00 00 00 21 00 02 00 0C 00 00 04 03 06 00 00 00 0A 00 00 00 0A 00 00 00";
    assert_eq!(one(&s, &mut connected(&s, CR), request), h(reply));
}

#[test]
fn a_reply_must_fit_the_negotiated_pdu() {
    let s = s7_1500();
    let mut conn = connected(&s, CR);
    // MB0..941: SFC's limit of PDU − 18 data bytes fills the 960-byte PDU exactly.
    let request = "03 00 00 1F 02 F0 A2 32 01 00 00 00 22 00 0E 00 00 04 01 12 0A 10 02 03 AE 00 00 83 00 00 00";
    let reply = one(&s, &mut conn, request);
    assert_eq!(unhex(&reply).len(), 7 + 960);
    assert!(reply.starts_with(&h("03 00 03 C7 02 F0 80 32 03 00 00 00 22 00 02 03 B2 00 00 04 01 FF 04 1D 70 A5")));
    // One byte more: header error 0x85/0x00.
    let request = "03 00 00 1F 02 F0 A3 32 01 00 00 00 23 00 0E 00 00 04 01 12 0A 10 02 03 AF 00 00 83 00 00 00";
    assert_eq!(one(&s, &mut conn, request), h("03 00 00 15 02 F0 80 32 03 00 00 00 23 00 02 00 00 85 00 04 00"));
}

#[test]
fn other_functions_get_error_replies() {
    let s = s7_1500();
    let mut conn = connected(&s, CR);
    // PLC stop ("P_PROGRAM"): Ack with 0x81/0x04.
    let request = "03 00 00 21 02 F0 A4 32 01 00 00 00 24 00 10 00 00 29 00 00 00 00 00 09 50 5F 50 52 4F 47 52 41 4D";
    assert_eq!(one(&s, &mut conn, request), h("03 00 00 13 02 F0 80 32 02 00 00 00 24 00 00 00 00 81 04"));
    // Write Var 42 to DB1.DBW4: not simulated, answered as with PUT/GET off; DB1.DBW4 keeps its value.
    let request = "03 00 00 25 02 F0 A5 32 01 00 00 00 25 00 0E 00 06
                   05 01 12 0A 10 05 00 01 00 01 84 00 00 20 00 04 00 10 00 2A";
    assert_eq!(one(&s, &mut conn, request), h("03 00 00 15 02 F0 80 32 03 00 00 00 25 00 02 00 00 81 04 05 00"));
    assert_eq!(one(&s, &mut conn, G5), h(G5_REPLY));
    // SZL 0x0424 does not exist here: 0xD401.
    let request = "03 00 00 21 02 F0 A6 32 07 00 00 00 26 00 08 00 08 00 01 12 04 11 44 01 00 FF 09 00 04 04 24 00 00";
    let reply = "03 00 00 21 02 F0 80 32 07 00 00 00 26 00 0C 00 04 00 01 12 08 12 84 01 00 00 00 D4 01 0A 00 00 00";
    assert_eq!(one(&s, &mut conn, request), h(reply));
    // Read clock (group 7): 0x8104.
    let request = "03 00 00 1D 02 F0 A7 32 07 00 00 00 27 00 08 00 04 00 01 12 04 11 47 01 00 0A 00 00 00";
    let reply = "03 00 00 21 02 F0 80 32 07 00 00 00 27 00 0C 00 04 00 01 12 08 12 87 01 00 00 00 81 04 0A 00 00 00";
    assert_eq!(one(&s, &mut conn, request), h(reply));
}

#[test]
fn strict_tsap_closes_without_a_reply() {
    // Slot 2 on an S7-1500, SFC's default slot 0 on an S7-300, connection type 04, and no called TSAP.
    for (profile, cr) in [
        ("s7-1500", CR_SLOT2),
        ("s7-300", CR),
        ("s7-1500", "03 00 00 16 11 E0 00 00 00 0F 00 C2 02 04 00 C1 02 03 11 C0 01 0A"),
        ("s7-1500", "03 00 00 12 0D E0 00 00 00 0F 00 C1 02 03 11 C0 01 0A"),
    ] {
        assert_eq!(closes(&Server::new(profile).unwrap(), &mut Conn::new(1), cr), "tsap", "{profile} {cr}");
    }
    // Slot 1 on an S7-1500 and slot 3 on an S7-400 are accepted.
    let reply = one(&s7_1500(), &mut Conn::new(1), "03 00 00 16 11 E0 00 00 00 0F 00 C2 02 01 01 C1 02 03 11 C0 01 0A");
    assert_eq!(reply, h("03 00 00 16 11 D0 00 0F 00 01 00 C0 01 0A C1 02 03 11 C2 02 01 01"));
    let reply = one(&Server::new("s7-400").unwrap(), &mut Conn::new(1), CR_SLOT3);
    assert_eq!(reply, h("03 00 00 16 11 D0 00 0F 00 01 00 C0 01 0A C1 02 03 11 C2 02 01 03"));
}

#[test]
fn a_disconnect_request_gets_a_dc_then_closes() {
    let s = s7_1500();
    let mut conn = Conn::new(1);
    one(&s, &mut conn, CR);
    let out = s.feed(&mut conn, &unhex("03 00 00 0B 06 80 00 01 00 0F 00"), &Events::disabled());
    assert_eq!(out.replies, vec![unhex("03 00 00 0A 05 C0 00 0F 00 01")]);
    assert_eq!(out.close, Some("dr"));
}

#[test]
fn malformed_input_closes_the_connection() {
    let s = s7_1500();
    for (reason, frame) in [
        ("tpkt_version", "04 00 00 07 02 F0 80"),
        ("tpkt_length", "03 00 00 06 02 F0"),
        ("cotp_length", "03 00 00 07 05 F0 80"),
        ("dt_before_cc", SETUP),
        // A DR before the CC.
        ("unexpected_tpdu", "03 00 00 0B 06 80 00 00 00 0F 00"),
    ] {
        assert_eq!(closes(&s, &mut Conn::new(1), frame), reason, "{frame}");
    }
    for (reason, frame) in [
        // A second CR.
        ("unexpected_tpdu", CR),
        ("job_before_setup", G5),
        ("user_data_before_setup", SZL),
        ("setup_length", "03 00 00 18 02 F0 81 32 01 00 00 00 00 00 07 00 00 F0 00 00 08 00 08 03"),
        ("setup_pdu", "03 00 00 19 02 F0 81 32 01 00 00 00 00 00 08 00 00 F0 00 00 08 00 08 00 0F"),
        // EOT clear.
        ("segmented_dt", "03 00 00 19 02 F0 01 32 01 00 00 00 00 00 08 00 00 F0 00 00 08 00 08 03 F0"),
    ] {
        let mut conn = Conn::new(1);
        one(&s, &mut conn, CR);
        assert_eq!(closes(&s, &mut conn, frame), reason, "{frame}");
    }
    for (reason, frame) in [
        ("protocol_id", "03 00 00 1F 02 F0 8A 33 01 00 00 00 0A 00 0E 00 00 04 01 12 0A 10 05 00 01 00 01 84 00 00 20"),
        ("s7_length", "03 00 00 1F 02 F0 8A 32 01 00 00 00 0A 00 0F 00 00 04 01 12 0A 10 05 00 01 00 01 84 00 00 20"),
        ("rosctr", "03 00 00 1F 02 F0 8A 32 03 00 00 00 0A 00 0E 00 00 04 01 12 0A 10 05 00 01 00 01 84 00 00 20"),
        ("read_var_length", "03 00 00 13 02 F0 8A 32 01 00 00 00 0A 00 02 00 00 04 00"),
        ("read_var_item",
         "03 00 00 1F 02 F0 8A 32 01 00 00 00 0A 00 0E 00 00 04 01 12 0B 10 05 00 01 00 01 84 00 00 20"),
        // Two items in the parameter.
        ("user_data_parameter",
         "03 00 00 21 02 F0 82 32 07 00 00 00 01 00 08 00 08 00 02 12 04 11 44 01 00 FF 09 00 04 00 11 00 00"),
        ("szl_data", "03 00 00 1D 02 F0 82 32 07 00 00 00 01 00 08 00 04 00 01 12 04 11 44 01 00 0A 00 00 00"),
        // A COTP ER.
        ("unexpected_tpdu", "03 00 00 07 02 70 00"),
    ] {
        assert_eq!(closes(&s, &mut connected(&s, CR), frame), reason, "{frame}");
    }
}

#[test]
fn truncated_frames_close_and_never_panic() {
    let s = s7_1500();
    for (request, handshake) in [(CR, false), (SETUP, true), (SZL, true), (G6, true), (G8, true), (G11, true)] {
        let full = unhex(request);
        for cut in 7..full.len() {
            // A frame whose TPKT length is right but whose content stops early.
            let mut frame = full[..cut].to_vec();
            frame[2..4].copy_from_slice(&(cut as u16).to_be_bytes());
            let mut conn = if handshake { connected(&s, CR) } else { Conn::new(1) };
            let out = s.feed(&mut conn, &frame, &Events::disabled());
            assert!(out.replies.is_empty() && out.close.is_some(), "{request} cut at {cut}");
        }
    }
    // Called directly, a frame shorter than TPKT and COTP headers is refused as well.
    let frame = unhex(G5);
    for cut in 0..7 {
        let action = s.handle(&mut connected(&s, CR), &frame[..cut], &Events::disabled());
        assert!(matches!(action, Action::Close(_)), "cut at {cut}");
    }
}
