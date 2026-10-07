// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! PCCC golden frames: requests byte for byte as SFC's pccc adapter builds them (Client.kt:274-327 and
//! :550-640, Address.kt:258-308), expected replies from the default map of the micrologix1400 profile.
#![cfg(feature = "pccc")]

use std::collections::BTreeMap;

use omni_plc_sim::core::codec::{hex, unhex};
use omni_plc_sim::core::config::SimConfig;
use omni_plc_sim::core::engine::{Engine, Settings};
use omni_plc_sim::core::events::Events;
use omni_plc_sim::core::signal::{splitmix64, Bank};
use omni_plc_sim::protocols::pccc::{Conn, Server, PROFILES};

/// RegisterSession, protocol version 1 (Client.kt:550-567), and its reply on connection 1.
const REGISTER: &str = "65 00 04 00 00000000 00000000 0000000000000000 00000000 0100 0000";
const REGISTERED: &str = "65 00 04 00 01000000 00000000 0000000000000000 00000000 0100 0000";

/// ST9:0 "SFC-SIM" and ST9:1 "HELLO WORLD": LEN, then the characters in swapped pairs.
const ST9_0: &str = "07 00 46 53 2D 43 49 53 00 4D";
const ST9_1: &str = "0B 00 45 48 4C 4C 20 4F 4F 57 4C 52 00 44";

fn ml1400() -> Server {
    Server::new("micrologix1400").unwrap()
}

/// The default map after scan `k` of a 10 ms cycle.
fn at_scan(profile: &str, k: u64) -> Server {
    let s = Server::new(profile).unwrap();
    let settings = Settings { cycle_ms: 10, clock_base_ms: 0 };
    Engine::new(&SimConfig::default(), settings, vec![s.image()]).unwrap().apply(k);
    s
}

/// Connection 1 with its session (handle 1) registered.
fn session(server: &Server) -> Conn {
    let mut conn = Conn::new(1);
    let out = server.feed(&mut conn, &unhex(REGISTER), &Events::disabled());
    assert_eq!(out.replies, vec![unhex(REGISTERED)]);
    conn
}

fn exchange(server: &Server, conn: &mut Conn, request: &[u8]) -> Vec<String> {
    let out = server.feed(conn, request, &Events::disabled());
    assert!(out.close.is_none(), "connection closed on {}", hex(request));
    out.replies.iter().map(|r| hex(r)).collect()
}

fn one(server: &Server, conn: &mut Conn, request: &[u8]) -> String {
    let replies = exchange(server, conn, request);
    assert_eq!(replies.len(), 1, "{}", hex(request));
    replies[0].clone()
}

/// A SendRRData carrying `cip`, framed as Client.kt:274-327 frames it: interface handle 0, timeout 10,
/// a Null Address item and an Unconnected Data item, no connect path.
fn rr(session: u32, cip: &[u8]) -> Vec<u8> {
    let mut f = unhex("6F 00");
    f.extend_from_slice(&(16 + cip.len() as u16).to_le_bytes());
    f.extend_from_slice(&session.to_le_bytes());
    f.extend_from_slice(&[0; 16]);
    f.extend_from_slice(&unhex("00000000 0A00 0200 0000 0000 B200"));
    f.extend_from_slice(&(cip.len() as u16).to_le_bytes());
    f.extend_from_slice(cip);
    f
}

/// Execute PCCC to 20 67 24 01 with the client's 7-byte requestor ID and STS 0, then `cmd`, the TNS and
/// the function's bytes.
fn pccc(cmd: u8, tns: u16, function: &str) -> Vec<u8> {
    let mut cip = unhex("4B 02 20 67 24 01 07 00 00 00 00 00 00");
    cip.extend_from_slice(&[cmd, 0]);
    cip.extend_from_slice(&tns.to_le_bytes());
    cip.extend_from_slice(&unhex(function));
    cip
}

/// A typed read, CMD 0x0F with the address block `A2 <size> <file> <type> <element> <sub>`.
fn read(session: u32, tns: u16, address: &str) -> Vec<u8> {
    rr(session, &pccc(0x0F, tns, address))
}

/// A SendRRData reply around `cip`: status 0, interface handle 0, timeout 0, a Null Address item.
fn rr_reply(session: u32, cip: &[u8]) -> Vec<u8> {
    let mut f = unhex("6F 00");
    f.extend_from_slice(&(16 + cip.len() as u16).to_le_bytes());
    f.extend_from_slice(&session.to_le_bytes());
    f.extend_from_slice(&[0; 16]);
    f.extend_from_slice(&unhex("00000000 0000 0200 0000 0000 B200"));
    f.extend_from_slice(&(cip.len() as u16).to_le_bytes());
    f.extend_from_slice(cip);
    f
}

/// The reply to a PCCC command: CB 00 00 00, the echoed requestor ID, CMD | 0x40, STS and the TNS,
/// then the data or the EXT STS.
fn pccc_reply(session: u32, cmd: u8, tns: u16, sts: u8, rest: &[u8]) -> Vec<u8> {
    let mut cip = unhex("CB 00 00 00 07 00 00 00 00 00 00");
    cip.extend_from_slice(&[cmd | 0x40, sts]);
    cip.extend_from_slice(&tns.to_le_bytes());
    cip.extend_from_slice(rest);
    rr_reply(session, &cip)
}

/// The reply to a typed read the client accepts (Client.kt:224-243, :336-382).
fn data_reply(session: u32, tns: u16, data: &[u8]) -> Vec<u8> {
    pccc_reply(session, 0x0F, tns, 0, data)
}

fn padded(bytes: &str, len: usize) -> Vec<u8> {
    let mut v = unhex(bytes);
    v.resize(len, 0);
    v
}

/// examples/in-process-pccc-s3 with OptimizeReads on: 11 requests a cycle, one per file, each from
/// element 0, with the sizes of Address.kt:301-308. (address block, reply data)
fn example() -> Vec<(&'static str, Vec<u8>)> {
    let mut strings = padded(ST9_0, 84);
    strings.extend(padded(ST9_1, 84));
    vec![
        ("A2 04 00 8B 00 00", unhex("00 00 00 00")),
        ("A2 02 01 8C 00 00", unhex("81 00")),
        ("A2 02 03 85 00 00", unhex("C3 A5")),
        ("A2 06 04 86 00 00", unhex("00 A0 64 00 64 00")),
        ("A2 06 05 87 00 00", unhex("00 00 0A 00 07 00")),
        ("A2 06 06 88 00 00", unhex("00 00 0A 00 03 00")),
        ("A2 04 07 89 00 00", unhex("C7 CF 39 30")),
        ("A2 08 08 8A 00 00", unhex("00 E6 40 46 00 00 80 BE")),
        ("A2 A8 09 8D 00 00", strings),
        ("A2 08 0A 91 00 00", unhex("2E FD 69 B6 D2 02 96 49")),
        ("A2 04 0B 8E 00 00", unhex("46 53 2D 43")),
    ]
}

/// F8:10..21 after scan `k` of a 10 ms cycle, as the engine computes them.
fn signals(k: u64) -> Vec<u8> {
    let v = Bank::new(&BTreeMap::new()).unwrap().values(k, k as f64 * 10.0 / 1000.0);
    [v.sine, v.cosine, v.tangent, v.cotangent, v.exp, v.quadratic, v.sawtooth, v.triangle, v.square, v.damped,
     v.noise, v.randomwalk]
        .iter()
        .flat_map(|x| (*x as f32).to_le_bytes())
        .collect()
}

#[test]
fn g1_register_session_is_exactly_28_bytes() {
    let s = ml1400();
    let mut conn = Conn::new(1);
    let out = s.feed(&mut conn, &unhex(REGISTER), &Events::disabled());
    assert_eq!(out.replies, vec![unhex(REGISTERED)]);
    assert_eq!(out.replies[0].len(), 28);
    // Another connection gets another handle.
    let out = s.feed(&mut Conn::new(7), &unhex(REGISTER), &Events::disabled());
    assert_eq!(hex(&out.replies[0]), hex(&unhex("65 00 04 00 07000000 00000000 0000000000000000 00000000 0100 0000")));
}

#[test]
fn g2_n7_0_byte_for_byte() {
    // N7:0 with handle 1 and TNS 1, literally as the client sends it, and the reply it accepts.
    let request = unhex(
        "6F 00 27 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
         00 00 00 00 0A 00 02 00 00 00 00 00 B2 00 17 00
         4B 02 20 67 24 01 07 00 00 00 00 00 00 0F 00 01 00
         A2 02 07 89 00 00",
    );
    let reply = unhex(
        "6F 00 21 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
         00 00 00 00 00 00 02 00 00 00 00 00 B2 00 11 00
         CB 00 00 00 07 00 00 00 00 00 00 4F 00 01 00
         C7 CF",
    );
    assert_eq!(request, read(1, 1, "A2 02 07 89 00 00"));
    assert_eq!(reply, data_reply(1, 1, &[0xC7, 0xCF]));
    let s = ml1400();
    let mut conn = session(&s);
    assert_eq!(one(&s, &mut conn, &request), hex(&reply));
}

#[test]
fn g3_single_reads_without_optimization() {
    let s = ml1400();
    let mut conn = session(&s);
    let cases = [
        // F8:0,2: 12345.5 and -0.25.
        (2, "A2 08 08 8A 00 00", unhex("00 E6 40 46 00 00 80 BE")),
        // B3:0 = 0xA5C3.
        (3, "A2 02 03 85 00 00", unhex("C3 A5")),
        // T4:0: EN and DN, PRE 100, ACC 100.
        (4, "A2 06 04 86 00 00", unhex("00 A0 64 00 64 00")),
        // ST9:0 "SFC-SIM", the whole 84-byte element.
        (5, "A2 54 09 8D 00 00", padded(ST9_0, 84)),
        // L10:0 = -1234567890.
        (6, "A2 04 0A 91 00 00", unhex("2E FD 69 B6")),
        // ST9:1, N7:0,4 and A11:0.
        (7, "A2 54 09 8D 01 00", padded(ST9_1, 84)),
        (8, "A2 08 07 89 00 00", unhex("C7 CF 39 30 FF 7F 00 80")),
        (9, "A2 02 0B 8E 00 00", unhex("46 53")),
        // S:1, the processor mode: RUN.
        (10, "A2 02 02 84 01 00", unhex("1E 00")),
        // Elements in the 3-byte form (FF + u16) parse too: N7:1 and N7:0 sub-element 1.
        (11, "A2 02 07 89 FF 01 00 00", unhex("39 30")),
        (12, "A2 02 07 89 00 FF 01 00", unhex("39 30")),
    ];
    for (tns, address, data) in cases {
        assert_eq!(one(&s, &mut conn, &read(1, tns, address)), hex(&data_reply(1, tns, &data)), "{address}");
    }
}

#[test]
fn g4_the_example_cycle_pipelined() {
    let s = ml1400();
    let mut conn = session(&s);
    let mut input = Vec::new();
    let mut want = Vec::new();
    for (i, (address, data)) in example().iter().enumerate() {
        let tns = i as u16 + 1;
        let request = read(1, tns, address);
        assert_eq!(request.len(), 63);
        input.extend(request);
        want.push(hex(&data_reply(1, tns, data)));
    }
    let replies = exchange(&s, &mut conn, &input);
    assert_eq!(replies, want);
    let lengths: Vec<usize> = replies.iter().map(|r| unhex(r).len()).collect();
    assert_eq!(lengths, vec![59, 57, 57, 61, 61, 61, 59, 63, 223, 63, 59]);
}

#[test]
fn g5_the_pilots_merged_reads() {
    // The pilot's channels as the optimiser merges them (Client.kt:395-471), after scan 25 (t = 0.25 s).
    let s = at_scan("micrologix1400", 25);
    let mut conn = session(&s);
    let f8 = signals(25);
    let mut n7 = unhex("C7 CF 39 30 FF 7F 00 80");
    n7.resize(20, 0);
    n7.extend(unhex("10 27 19 00"));
    let cases = [
        // B3:0, B3:0/5 and B3:1/0: B3:1 = blink_1hz | blink_5hz << 1, both on at 0.25 s.
        ("A2 04 03 85 00 00", unhex("C3 A5 03 00")),
        // T4:0, T4:1 and T4:1.ACC: T4:1 is timing (EN, TT) at ACC 25.
        ("A2 0C 04 86 00 00", unhex("00 A0 64 00 64 00 00 C0 F4 01 19 00")),
        // C5:0 and C5:1: C5:1 has CU on (the first half second), PRE 10, ACC 0.
        ("A2 0C 05 87 00 00", unhex("00 00 0A 00 07 00 00 80 0A 00 00 00")),
        // N7:0, N7:0,4, N7:10 (round(100·sine) = 10000) and N7:11 (scan 25).
        ("A2 18 07 89 00 00", n7),
        // F8:10..19, then F8:20..21: a gap of 35 bytes to F8:10's end splits them (MaxReadGap 32).
        ("A2 28 08 8A 0A 00", f8[..40].to_vec()),
        ("A2 08 08 8A 14 00", f8[40..].to_vec()),
        // L10:10 and S:4, the scan.
        ("A2 04 0A 91 0A 00", unhex("19 00 00 00")),
        ("A2 02 02 84 04 00", unhex("19 00")),
    ];
    for (i, (address, data)) in cases.iter().enumerate() {
        let tns = i as u16 + 1;
        assert_eq!(one(&s, &mut conn, &read(1, tns, address)), hex(&data_reply(1, tns, data)), "{address}");
    }
}

#[test]
fn g6_the_running_timer_and_counter() {
    let t4 = |k: u64| {
        let s = at_scan("micrologix1400", k);
        let mut conn = session(&s);
        one(&s, &mut conn, &read(1, 1, "A2 06 04 86 01 00"))
    };
    // Timing, done for one 10 ms tick, reset by its own DN on the next, timing again.
    assert_eq!(t4(499), hex(&data_reply(1, 1, &unhex("00 C0 F4 01 F3 01"))));
    assert_eq!(t4(500), hex(&data_reply(1, 1, &unhex("00 A0 F4 01 F4 01"))));
    assert_eq!(t4(501), hex(&data_reply(1, 1, &unhex("00 00 F4 01 00 00"))));
    assert_eq!(t4(509), hex(&data_reply(1, 1, &unhex("00 C0 F4 01 07 00"))));
    let c5 = |k: u64| {
        let s = at_scan("micrologix1400", k);
        let mut conn = session(&s);
        one(&s, &mut conn, &read(1, 1, "A2 06 05 87 01 00"))
    };
    // 12 s: CU and DN; 12.5 s: DN only; 9.5 s: neither; 16 s: back to 0 with CU.
    assert_eq!(c5(1200), hex(&data_reply(1, 1, &unhex("00 A0 0A 00 0C 00"))));
    assert_eq!(c5(1250), hex(&data_reply(1, 1, &unhex("00 20 0A 00 0C 00"))));
    assert_eq!(c5(950), hex(&data_reply(1, 1, &unhex("00 00 0A 00 09 00"))));
    assert_eq!(c5(1600), hex(&data_reply(1, 1, &unhex("00 80 0A 00 00 00"))));
    // S:4 and L10:10 past 2^16 scans: S:4 wraps, L10:10 does not.
    let s = at_scan("micrologix1400", 70_000);
    let mut conn = session(&s);
    assert_eq!(one(&s, &mut conn, &read(1, 1, "A2 02 02 84 04 00")), hex(&data_reply(1, 1, &unhex("70 11"))));
    assert_eq!(one(&s, &mut conn, &read(1, 2, "A2 04 0A 91 0A 00")), hex(&data_reply(1, 2, &unhex("70 11 01 00"))));
}

#[test]
fn e1_unknown_session() {
    let s = ml1400();
    // A handle this connection was not given: a header-only reply with status 0x64 and the request's
    // handle, which the client turns into one read error (Client.kt:364-369).
    let mut conn = session(&s);
    assert_eq!(
        one(&s, &mut conn, &read(2, 1, "A2 02 07 89 00 00")),
        hex(&unhex("6F 00 00 00 02 00 00 00 64 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"))
    );
    // No RegisterSession yet.
    let mut fresh = Conn::new(1);
    assert_eq!(
        one(&s, &mut fresh, &read(1, 1, "A2 02 07 89 00 00")),
        hex(&unhex("6F 00 00 00 01 00 00 00 64 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"))
    );
}

#[test]
fn e2_sts_f0_bad_file_type_or_range() {
    let s = ml1400();
    let mut conn = session(&s);
    let ext = |tns: u16, code: u8| hex(&pccc_reply(1, 0x0F, tns, 0xF0, &[code]));
    // N7:64, one past the 64-word file; N7:63 with 4 bytes; N7:300 in the 3-byte form; all of N7 + 2.
    assert_eq!(one(&s, &mut conn, &read(1, 1, "A2 02 07 89 40 00")), ext(1, 0x0A));
    assert_eq!(one(&s, &mut conn, &read(1, 2, "A2 04 07 89 3F 00")), ext(2, 0x0A));
    assert_eq!(one(&s, &mut conn, &read(1, 3, "A2 02 07 89 FF 2C 01 00")), ext(3, 0x0A));
    assert_eq!(one(&s, &mut conn, &read(1, 4, "A2 82 07 89 00 00")), ext(4, 0x0A));
    // N12 does not exist, N255 neither (file number in the 3-byte form), and file 7 is not an F file.
    assert_eq!(one(&s, &mut conn, &read(1, 5, "A2 02 0C 89 00 00")), ext(5, 0x06));
    assert_eq!(one(&s, &mut conn, &read(1, 6, "A2 02 FF FF 00 89 00 00")), ext(6, 0x06));
    assert_eq!(one(&s, &mut conn, &read(1, 7, "A2 04 07 8A 00 00")), ext(7, 0x06));
    assert_eq!(unhex(&ext(1, 0x0A)).len(), 56);
    // The SLC 5/05 has no L file; the MicroLogix 1100's N7 has 16 words.
    let slc = Server::new("slc505").unwrap();
    let mut conn = session(&slc);
    assert_eq!(one(&slc, &mut conn, &read(1, 1, "A2 04 0A 91 00 00")), ext(1, 0x06));
    let ml1100 = Server::new("micrologix1100").unwrap();
    let mut conn = session(&ml1100);
    assert_eq!(one(&ml1100, &mut conn, &read(1, 1, "A2 02 07 89 10 00")), ext(1, 0x0A));
    assert_eq!(one(&ml1100, &mut conn, &read(1, 2, "A2 02 07 89 0F 00")), hex(&data_reply(1, 2, &[0, 0])));
}

#[test]
fn e3_sts_10_for_everything_not_simulated() {
    let s = ml1400();
    let mut conn = session(&s);
    let illegal = |cmd: u8, tns: u16| hex(&pccc_reply(1, cmd, tns, 0x10, &[]));
    // FNC 0xA1 (two address fields), FNC 0xAA (a typed write), CMD 0x06 FNC 0x03 (diagnostic status).
    assert_eq!(one(&s, &mut conn, &rr(1, &pccc(0x0F, 1, "A1 02 07 89 00"))), illegal(0x0F, 1));
    assert_eq!(one(&s, &mut conn, &rr(1, &pccc(0x0F, 2, "AA 02 07 89 00 00 39 30"))), illegal(0x0F, 2));
    assert_eq!(one(&s, &mut conn, &rr(1, &pccc(0x06, 3, "03"))), illegal(0x06, 3));
    // A truncated address and a trailing byte are illegal format.
    assert_eq!(one(&s, &mut conn, &read(1, 4, "A2 02 07")), illegal(0x0F, 4));
    assert_eq!(one(&s, &mut conn, &read(1, 5, "A2 02 07 89 00 00 00")), illegal(0x0F, 5));
    // A PLC-5 does not know FNC 0xA2.
    let plc5 = Server::new("plc5").unwrap();
    let mut conn = session(&plc5);
    assert_eq!(one(&plc5, &mut conn, &read(1, 1, "A2 02 07 89 00 00")), illegal(0x0F, 1));
}

#[test]
fn e4_cip_errors_are_44_bytes() {
    let s = ml1400();
    let mut conn = session(&s);
    let tail = "07 00 00 00 00 00 00 0F 00 01 00 A2 02 07 89 00 00";
    let cip = |head: &str| rr(1, &unhex(&format!("{head} {tail}")));
    let error = |reply: &str| hex(&rr_reply(1, &unhex(reply)));
    // Class 0x66, instance 2, then service 0x4C to the PCCC object, then Get_Attributes_All to the
    // Identity object, which this device does not route to (the path is resolved first).
    assert_eq!(one(&s, &mut conn, &cip("4B 02 20 66 24 01")), error("CB 00 05 00"));
    assert_eq!(one(&s, &mut conn, &cip("4B 02 20 67 24 02")), error("CB 00 05 00"));
    assert_eq!(one(&s, &mut conn, &cip("4C 02 20 67 24 01")), error("CC 00 08 00"));
    assert_eq!(one(&s, &mut conn, &cip("01 02 20 01 24 01")), error("81 00 05 00"));
    // An attribute segment, and a path longer than the request.
    assert_eq!(one(&s, &mut conn, &cip("4B 02 20 67 30 01")), error("CB 00 04 00"));
    assert_eq!(one(&s, &mut conn, &rr(1, &unhex("4B 05 20 67 24 01"))), error("CB 00 04 00"));
    // A requestor ID shorter than 7 bytes, or no PCCC command after it.
    let short_id = unhex("4B 02 20 67 24 01 05 00 00 00 00 0F 00 01 00");
    assert_eq!(one(&s, &mut conn, &rr(1, &short_id)), error("CB 00 13 00"));
    let no_command = unhex("4B 02 20 67 24 01 07 00 00 00 00 00 00");
    assert_eq!(one(&s, &mut conn, &rr(1, &no_command)), error("CB 00 13 00"));
    assert_eq!(unhex(&error("CB 00 05 00")).len(), 44);
    // The 16-bit class form reaches the PCCC object too.
    assert_eq!(
        one(&s, &mut conn, &cip("4B 03 21 00 67 00 24 01")),
        hex(&data_reply(1, 1, &[0xC7, 0xCF]))
    );
}

#[test]
fn e5_encapsulation_errors() {
    let s = ml1400();
    let mut conn = session(&s);
    let header = |command: &str, session: &str, status: &str| {
        hex(&unhex(&format!("{command} 00 00 {session} {status} 00 00 00 00 00 00 00 00 00 00 00 00")))
    };
    // A connected address item, one item only, and an item longer than the data: 0x0003.
    let bad = [
        "00000000 0A00 0200 A100 0400 01000000 B200 0200 4B02",
        "00000000 0A00 0100 0000 0000",
        "00000000 0A00 0200 0000 0000 B200 1700 4B02",
    ];
    for data in bad {
        let data = unhex(data);
        let mut f = unhex("6F 00");
        f.extend_from_slice(&(data.len() as u16).to_le_bytes());
        f.extend_from_slice(&unhex("01000000 00000000 0000000000000000 00000000"));
        f.extend_from_slice(&data);
        assert_eq!(one(&s, &mut conn, &f), header("6F 00", "01 00 00 00", "03 00 00 00"));
    }
    // ListServices is not simulated: 0x0001.
    let list_services = unhex("04 00 00 00 00000000 00000000 0000000000000000 00000000");
    assert_eq!(one(&s, &mut conn, &list_services), header("04 00", "00 00 00 00", "01 00 00 00"));
    // A request with a non-zero status or options field is discarded; NOP never has a reply.
    let mut with_status = read(1, 1, "A2 02 07 89 00 00");
    with_status[8] = 1;
    assert!(exchange(&s, &mut conn, &with_status).is_empty());
    let mut with_options = read(1, 1, "A2 02 07 89 00 00");
    with_options[20] = 1;
    assert!(exchange(&s, &mut conn, &with_options).is_empty());
    let nop = unhex("00 00 02 00 00000000 00000000 0000000000000000 00000000 AA BB");
    assert!(exchange(&s, &mut conn, &nop).is_empty());
    // RegisterSession: protocol version 2 is unsupported (0x69), a wrong length is 0x65; still 28 bytes.
    let mut fresh = Conn::new(1);
    let v2 = unhex("65 00 04 00 00000000 00000000 0000000000000000 00000000 0200 0000");
    assert_eq!(
        one(&s, &mut fresh, &v2),
        hex(&unhex("65 00 04 00 00000000 69000000 0000000000000000 00000000 0100 0000"))
    );
    let long = unhex("65 00 06 00 00000000 00000000 0000000000000000 00000000 0100 0000 0000");
    assert_eq!(
        one(&s, &mut fresh, &long),
        hex(&unhex("65 00 04 00 00000000 65000000 0000000000000000 00000000 0100 0000"))
    );
}

#[test]
fn t1_list_identity() {
    let s = ml1400();
    let mut want = unhex(
        "63 00 3B 00 00000000 00000000 0102030405060708 00000000
         0100 0C00 3500 0100 0002 AF12 00000000 0000000000000000
         0100 0E00 5A00 15 03 3000 01001400 13",
    );
    want.extend_from_slice(b"1766-L32BXB B/21.03");
    want.push(0x03);
    // No session needed; the sender context is echoed.
    let request = unhex("63 00 00 00 00000000 00000000 0102030405060708 00000000");
    assert_eq!(one(&s, &mut Conn::new(1), &request), hex(&want));
}

#[test]
fn t2_one_session_per_connection_and_unregister() {
    let s = ml1400();
    let mut conn = session(&s);
    // A second RegisterSession is refused with the handle already given.
    assert_eq!(
        one(&s, &mut conn, &unhex(REGISTER)),
        hex(&unhex("65 00 04 00 01000000 01000000 0000000000000000 00000000 0100 0000"))
    );
    // UnRegisterSession with another handle is refused; with its own it closes the connection with
    // no reply, and whatever follows it is not answered.
    let unregister = |handle: &str| unhex(&format!("66 00 00 00 {handle} 00000000 0000000000000000 00000000"));
    assert_eq!(
        one(&s, &mut conn, &unregister("02000000")),
        hex(&unhex("66 00 00 00 02000000 64000000 0000000000000000 00000000"))
    );
    let mut input = unregister("01000000");
    input.extend(read(1, 1, "A2 02 07 89 00 00"));
    let out = s.feed(&mut conn, &input, &Events::disabled());
    assert_eq!(out.close, Some("unregistered"));
    assert!(out.replies.is_empty());
}

#[test]
fn f1_whole_byte_by_byte_and_split_give_the_same_replies() {
    let s = ml1400();
    let mut input = unhex(REGISTER);
    for (i, (address, _)) in example().iter().enumerate() {
        input.extend(read(1, i as u16 + 1, address));
    }
    input.extend(read(2, 12, "A2 02 07 89 00 00"));
    input.extend(read(1, 13, "A2 02 07 89 40 00"));
    let whole = s.feed(&mut Conn::new(1), &input, &Events::disabled());
    assert!(whole.close.is_none());
    assert_eq!(whole.replies.len(), 14);
    let mut conn = Conn::new(1);
    let mut bytewise = Vec::new();
    for b in &input {
        bytewise.extend(s.feed(&mut conn, &[*b], &Events::disabled()).replies);
    }
    assert_eq!(whole.replies, bytewise);
    for cut in (1..input.len()).step_by(7) {
        let mut conn = Conn::new(1);
        let mut split = s.feed(&mut conn, &input[..cut], &Events::disabled()).replies;
        split.extend(s.feed(&mut conn, &input[cut..], &Events::disabled()).replies);
        assert_eq!(whole.replies, split, "split at {cut}");
    }
}

#[test]
fn f2_a_bad_length_closes_the_connection() {
    let s = ml1400();
    let mut conn = session(&s);
    // 65535 bytes of data cannot fit in a 65535-byte packet with its header.
    let mut input = read(1, 1, "A2 02 07 89 00 00");
    input.extend(unhex("6F 00 FF FF 01000000 00000000 0000000000000000 00000000"));
    let out = s.feed(&mut conn, &input, &Events::disabled());
    assert_eq!(out.close, Some("bad_length"));
    assert_eq!(out.replies, vec![data_reply(1, 1, &[0xC7, 0xCF])]);
}

#[test]
fn f3_short_and_mangled_frames_never_panic() {
    let s = ml1400();
    let mut requests = vec![unhex(REGISTER), unhex("63 00 00 00 00000000 00000000 0000000000000000 00000000")];
    for (i, (address, _)) in example().iter().enumerate() {
        requests.push(read(1, i as u16 + 1, address));
    }
    requests.push(read(1, 1, "A2 02 07 89 FF 2C 01 00"));
    // Every request cut short, with its length field telling the truth: an error reply or none, never
    // a panic, and every reply as long as its header says.
    for request in &requests {
        for cut in 24..request.len() {
            let mut frame = request[..cut].to_vec();
            frame[2..4].copy_from_slice(&((cut - 24) as u16).to_le_bytes());
            let mut conn = session(&s);
            let out = s.feed(&mut conn, &frame, &Events::disabled());
            assert!(out.close.is_none());
            for r in &out.replies {
                assert_eq!(r.len(), 24 + u16::from_le_bytes([r[2], r[3]]) as usize, "{}", hex(&frame));
            }
        }
    }
    // Random bytes in every position of every request.
    let mut x = 0x5EED;
    for request in &requests {
        for _ in 0..200 {
            x = splitmix64(x);
            let mut frame = request.clone();
            let at = 4 + (x as usize >> 8) % (frame.len() - 4);
            frame[at] = x as u8;
            let mut conn = session(&s);
            for r in s.feed(&mut conn, &frame, &Events::disabled()).replies {
                assert_eq!(r.len(), 24 + u16::from_le_bytes([r[2], r[3]]) as usize, "{}", hex(&frame));
            }
        }
    }
}

#[test]
fn every_profile_builds_and_maps() {
    for name in PROFILES {
        let map = Server::new(name).unwrap().print_map();
        assert_eq!(map["profile"], *name);
        assert!(!map["tags"].as_array().unwrap().is_empty());
    }
    assert!(Server::new("plc6").is_err());
    let slc = Server::new("slc505").unwrap().print_map();
    assert!(slc["files"].as_array().unwrap().iter().all(|f| f["file"] != "L10"));
    assert!(slc["tags"].as_array().unwrap().iter().all(|t| !t["address"].as_str().unwrap().starts_with("L10")));
}
