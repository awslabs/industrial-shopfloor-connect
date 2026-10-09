// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! SLMP golden frames: request bytes exactly as SFC's slmp adapter sends them (SlmpHeader.kt:22-29,
//! SlmpDeviceRead.kt:18-22, SlmpDeviceReadRandom.kt:19-37), expected replies from the default map. Profile
//! iq-r unless a test says otherwise; dynamic words at cycle_ms = 10.
#![cfg(feature = "slmp")]

use std::sync::Arc;
use std::time::Duration;

use omni_plc_sim::core::clock::unix_ms;
use omni_plc_sim::core::codec::{hex, unhex};
use omni_plc_sim::core::config::SimConfig;
use omni_plc_sim::core::engine::{Engine, Settings};
use omni_plc_sim::core::events::Events;
use omni_plc_sim::protocols::slmp::{Conn, Server};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

fn exchange(server: &Server, request: &str) -> Vec<String> {
    let mut conn = Conn::new(1);
    let out = server.feed(&mut conn, &unhex(request), &Events::disabled());
    assert!(!out.close, "connection closed on {request}");
    assert_eq!(conn.pending(), 0, "bytes left over from {request}");
    out.replies.iter().map(|r| hex(r)).collect()
}

fn one(server: &Server, request: &str) -> String {
    let replies = exchange(server, request);
    assert_eq!(replies.len(), 1, "{request}");
    replies[0].clone()
}

fn want(reply: &str) -> String {
    hex(&unhex(reply))
}

/// A 3E request with SFC's routing fields and monitoring timer, L counted from `body` (command onwards).
fn frame(body: &str) -> String {
    let n = unhex(body).len() + 2;
    format!("50 00 00 FF FF 03 00 {:02X} {:02X} 00 00 {body}", n & 0xFF, n >> 8)
}

/// A normal reply to SFC's routing fields carrying `data`.
fn ok(data: &str) -> String {
    let n = unhex(data).len() + 2;
    want(&format!("D0 00 00 FF FF 03 00 {:02X} {:02X} 00 00 {data}", n & 0xFF, n >> 8))
}

/// An error reply to SFC's routing fields: end code, then the 9-byte error information.
fn error(code: &str, cmd_sub: &str) -> String {
    want(&format!("D0 00 00 FF FF 03 00 0B 00 {code} 00 FF FF 03 00 {cmd_sub}"))
}

fn iqr() -> Server {
    Server::new("iq-r").unwrap()
}

/// Applies scan `k` the way the engine does at cycle_ms = 10.
fn at_scan(server: &Server, k: u64, clock_base_ms: i64) {
    let settings = Settings { cycle_ms: 10, clock_base_ms };
    let mut engine = Engine::new(&SimConfig::default(), settings, vec![server.image()]).unwrap();
    engine.apply(k);
}

const G1: &str = "50 00 00 FF FF 03 00 0C 00 00 00 01 04 00 00 C8 00 00 A8 10 00";
const G2: &str = "50 00 00 FF FF 03 00 0C 00 00 00 01 04 00 00 F0 00 00 A8 0A 00";
const G3: &str = "50 00 00 FF FF 03 00 0C 00 00 00 01 04 01 00 00 00 00 90 10 00";
const G4: &str = "50 00 00 FF FF 03 00 0C 00 00 00 01 04 00 00 18 01 00 A8 0C 00";
const G5: &str = "50 00 00 FF FF 03 00 30 00 00 00 03 04 00 00 08 02 64 00 00 A8 66 00 00 A8 67 00 00 A8 68 00 00 A8
                  00 00 00 90 01 00 00 90 00 00 00 9C 00 00 00 90 7E 00 00 A8 80 00 00 A8";
const G5_REPLY: &str = "D0 00 00 FF FF 03 00 1A 00 00 00 C7 CF A5 00 9C FF C8 00 A5 3C 52 1E 0D 00 A5 3C
                        BC 9A BC 9A 34 12 34 12";
const S3: &str = "54 00 34 12 00 00 00 FF FF 03 00 0C 00 00 00 01 04 00 00 64 00 00 A8 01 00";
const S3_REPLY: &str = "D4 00 34 12 00 00 00 FF FF 03 00 04 00 00 00 C7 CF";

fn g1_reply() -> String {
    want(&format!("D0 00 00 FF FF 03 00 22 00 00 00 53 46 43 2D 53 49 4D 00{}", " 00".repeat(24)))
}

fn g2_reply() -> String {
    want("D0 00 00 FF FF 03 00 16 00 00 00 01 00 FE FF 03 00 FC FF F4 01 A8 FD 58 1B C0 E0 FF 7F 00 80")
}

#[test]
fn g1_string_16_words_from_d200() {
    assert_eq!(one(&iqr(), G1), g1_reply());
}

#[test]
fn g2_int_array_from_d240() {
    assert_eq!(one(&iqr(), G2), g2_reply());
}

#[test]
fn g3_16_m_relays_in_bit_units() {
    assert_eq!(one(&iqr(), G3), want("D0 00 00 FF FF 03 00 0A 00 00 00 10 10 01 01 00 11 11 00"));
}

#[test]
fn g4_recipe_struct_12_words_from_d280() {
    let reply = format!("D0 00 00 FF FF 03 00 1A 00 00 00 07 00 FA 00 50 55 4D 50 2D 30 31 00{}", " 00".repeat(12));
    assert_eq!(one(&iqr(), G4), want(&reply));
}

#[test]
fn g5_random_read_of_word_bit_and_double_word_items() {
    assert_eq!(one(&iqr(), G5), want(G5_REPLY));
}

#[test]
fn p5_the_pilot_random_read_at_scan_1234() {
    let s = iqr();
    at_scan(&s, 1234, 0);
    let request = "50 00 00 FF FF 03 00 44 00 00 00 03 04 00 00 0D 02 64 00 00 A8 66 00 00 A8 67 00 00 A8 68 00 00 A8
                   00 00 00 90 01 00 00 90 00 00 00 90 00 00 00 9C 90 01 00 91 91 01 00 91 A4 01 00 A9 4C 04 00 A8
                   9C 01 00 91 7E 00 00 A8 80 00 00 A8";
    // SM400 and SM401 as 16-bit words, SD420 = 1234, D1100 = sine_int 8443, SM412 as a word (t = 12.34 s).
    let reply = "D0 00 00 FF FF 03 00 24 00 00 00 C7 CF A5 00 9C FF C8 00 A5 3C 52 1E A5 3C 0D 00
                 09 34 04 1A D2 04 FB 20 03 00 BC 9A BC 9A 34 12 34 12";
    assert_eq!(one(&s, request), want(reply));
}

#[test]
fn e1_long_timer_batch_read_as_sfc_sends_it() {
    // LTN0 DOUBLEWORD[2]: subcommand 0002 with a Q/L device field, L = 12.
    let request = "50 00 00 FF FF 03 00 0C 00 00 00 01 04 02 00 00 00 00 52 02 00";
    assert_eq!(one(&iqr(), request), error("61 C0", "01 04 02 00"));
    for name in ["q", "l", "iq-f"] {
        assert_eq!(one(&Server::new(name).unwrap(), request), error("59 C0", "01 04 02 00"), "{name}");
    }
}

#[test]
fn e2_long_index_register_on_a_q_cpu() {
    let request = "50 00 00 FF FF 03 00 0C 00 00 00 03 04 00 00 00 01 00 00 00 62";
    assert_eq!(one(&Server::new("q").unwrap(), request), error("5B C0", "03 04 00 00"));
}

#[test]
fn e3_e5_reads_past_the_end_of_d() {
    let s = iqr();
    assert_eq!(
        one(&s, "50 00 00 FF FF 03 00 0C 00 00 00 01 04 00 00 FE 47 00 A8 04 00"),
        error("56 C0", "01 04 00 00")
    );
    // KD-11: STRING(16) reads 16 words, past the tail string in the last 8 words of D.
    assert_eq!(
        one(&s, "50 00 00 FF FF 03 00 0C 00 00 00 01 04 00 00 F8 47 00 A8 10 00"),
        error("56 C0", "01 04 00 00")
    );
    // The same 8 words alone are the tail string.
    assert_eq!(one(&s, &frame("01 04 00 00 F8 47 00 A8 08 00")), ok("54 41 49 4C 2D 4F 46 2D 44 45 56 49 43 45 21 00"));
}

#[test]
fn e4_961_words_exceed_the_batch_limit() {
    let request = "50 00 00 FF FF 03 00 0C 00 00 00 01 04 00 00 00 00 00 A8 C1 03";
    for name in ["iq-r", "q", "l"] {
        assert_eq!(one(&Server::new(name).unwrap(), request), error("51 C0", "01 04 00 00"), "{name}");
    }
    assert_eq!(one(&Server::new("iq-f").unwrap(), request), error("52 C0", "01 04 00 00"));
}

#[test]
fn e6_long_timer_contact_in_a_random_read() {
    let request = "50 00 00 FF FF 03 00 0C 00 00 00 03 04 00 00 01 00 00 00 00 51";
    assert_eq!(one(&iqr(), request), error("5B C0", "03 04 00 00"));
}

#[test]
fn k4_x10_reads_device_number_ten() {
    // SFC numbers are decimal: "X10" is number 10 (MELSEC X0A), off; numbers 16 and 24 are bits 6 and 14.
    let request = "50 00 00 FF FF 03 00 0C 00 00 00 03 04 00 00 01 00 0A 00 00 9C";
    assert_eq!(one(&iqr(), request), want("D0 00 00 FF FF 03 00 04 00 00 00 40 40"));
}

#[test]
fn s1_read_type_name() {
    let request = "50 00 00 FF FF 03 00 06 00 00 00 01 01 00 00";
    let r04 = format!("D0 00 00 FF FF 03 00 14 00 00 00 52 30 34 43 50 55{} 00 48", " 20".repeat(10));
    assert_eq!(one(&iqr(), request), want(&r04));
    let fx5 = "D0 00 00 FF FF 03 00 14 00 00 00 46 58 35 55 2D 33 32 4D 52 2F 45 53 20 20 20 20 21 4A";
    assert_eq!(one(&Server::new("iq-f").unwrap(), request), want(fx5));
    for name in ["q", "l"] {
        assert_eq!(one(&Server::new(name).unwrap(), request), error("59 C0", "01 01 00 00"), "{name}");
    }
}

#[test]
fn s2_loopback() {
    let request = "50 00 00 FF FF 03 00 0D 00 00 00 19 06 00 00 05 00 41 42 43 44 45";
    assert_eq!(one(&iqr(), request), want("D0 00 00 FF FF 03 00 09 00 00 00 05 00 41 42 43 44 45"));
    // A count that does not match the data, and a count of 0.
    assert_eq!(one(&iqr(), &frame("19 06 00 00 04 00 41 42 43 44 45")), error("61 C0", "19 06 00 00"));
    assert_eq!(one(&iqr(), &frame("19 06 00 00 00 00")), error("61 C0", "19 06 00 00"));
}

#[test]
fn s3_4e_frame_on_iq_r_closes_elsewhere() {
    assert_eq!(one(&iqr(), S3), want(S3_REPLY));
    for name in ["q", "l", "iq-f"] {
        let out = Server::new(name).unwrap().feed(&mut Conn::new(1), &unhex(S3), &Events::disabled());
        assert!(out.close && out.replies.is_empty(), "{name}");
    }
}

#[test]
fn s4_iq_r_format_random_read_of_lz0() {
    let request = "50 00 00 FF FF 03 00 0E 00 00 00 03 04 02 00 00 01 00 00 00 00 62 00";
    assert_eq!(one(&iqr(), request), want("D0 00 00 FF FF 03 00 06 00 00 00 A0 86 01 00"));
    assert_eq!(one(&Server::new("q").unwrap(), request), error("59 C0", "03 04 02 00"));
}

#[test]
fn s5_writes_are_answered_as_by_a_read_only_device() {
    // Spec §6 S5 expects the write acknowledgement; writes are not simulated, so 1401 gets C059.
    let request = "50 00 00 FF FF 03 00 10 00 00 00 01 14 00 00 F4 01 00 A8 02 00 01 00 02 00";
    let s = iqr();
    assert_eq!(one(&s, request), error("59 C0", "01 14 00 00"));
    // D500 is still 0.
    assert_eq!(one(&s, &frame("01 04 00 00 F4 01 00 A8 02 00")), ok("00 00 00 00"));
}

#[test]
fn iq_r_format_batch_reads() {
    let s = iqr();
    // 0401/0002: D100 with a 4-byte number and a 2-byte code, L = 14. 0401/0003: M0..M3 in bit units.
    assert_eq!(one(&s, &frame("01 04 02 00 64 00 00 00 A8 00 01 00")), ok("C7 CF"));
    assert_eq!(one(&s, &frame("01 04 03 00 00 00 00 00 90 00 04 00")), ok("10 10"));
    // LTN0 as SFC would have to read it: one 4-word block in the iQ-R format.
    at_scan(&s, 1234, 0);
    assert_eq!(one(&s, &frame("01 04 02 00 00 00 00 00 52 00 04 00")), ok("80 96 98 00 03 00 00 00"));
    // A 2-byte code above 0xFF is no device.
    assert_eq!(one(&s, &frame("01 04 02 00 64 00 00 00 A8 01 01 00")), error("5B C0", "01 04 02 00"));
}

#[test]
fn routing_fields_are_echoed() {
    // Network 1, PC 2, I/O 03E0, station 5, monitoring timer 4 (1 s): all echoed, the timer ignored.
    let request = "50 00 01 02 E0 03 05 0C 00 04 00 01 04 00 00 64 00 00 A8 01 00";
    assert_eq!(one(&iqr(), request), want("D0 00 01 02 E0 03 05 04 00 00 00 C7 CF"));
    assert_eq!(
        one(&iqr(), "50 00 01 02 E0 03 05 06 00 04 00 34 12 00 00"),
        want("D0 00 01 02 E0 03 05 0B 00 59 C0 01 02 E0 03 05 34 12 00 00")
    );
}

#[test]
fn whole_frames_byte_by_byte_and_pipelined_give_the_same_replies() {
    let s = iqr();
    let input = unhex(&[G1, G2, G3, G4, G5, S3].join(" "));
    let whole = s.feed(&mut Conn::new(1), &input, &Events::disabled());
    assert!(!whole.close);
    assert_eq!(whole.replies.len(), 6);
    assert_eq!(hex(&whole.replies[0]), g1_reply());
    assert_eq!(hex(&whole.replies[1]), g2_reply());
    assert_eq!(hex(&whole.replies[4]), want(G5_REPLY));
    assert_eq!(hex(&whole.replies[5]), want(S3_REPLY));
    let mut conn = Conn::new(2);
    let mut split = Vec::new();
    for b in &input {
        let out = s.feed(&mut conn, &[*b], &Events::disabled());
        assert!(!out.close);
        split.extend(out.replies);
    }
    assert_eq!(whole.replies, split);
    assert_eq!((conn.requests, conn.pending()), (6, 0));
}

#[test]
fn a_frame_split_inside_its_header_waits_for_the_rest() {
    let s = iqr();
    let input = unhex(G2);
    let mut conn = Conn::new(1);
    for cut in [1, 8, 20] {
        assert!(s.feed(&mut conn, &input[..cut], &Events::disabled()).replies.is_empty());
        let out = s.feed(&mut conn, &input[cut..], &Events::disabled());
        assert_eq!(out.replies.iter().map(|r| hex(r)).collect::<Vec<_>>(), vec![g2_reply()]);
    }
}

#[test]
fn ascii_code_closes_the_connection() {
    // "500000FF03FF00..." in ASCII code: a binary port does not answer.
    let mut conn = Conn::new(1);
    let out = iqr().feed(&mut conn, b"500000FF03FF000018000004010000D*0001000010", &Events::disabled());
    assert!(out.close && out.replies.is_empty());
}

#[test]
fn replies_before_a_bad_frame_still_go_out() {
    let out = iqr().feed(&mut Conn::new(1), &unhex(&format!("{G2} 35 30 30 30")), &Events::disabled());
    assert!(out.close);
    assert_eq!(out.replies.iter().map(|r| hex(r)).collect::<Vec<_>>(), vec![g2_reply()]);
}

#[test]
fn a_length_above_8192_closes_the_connection() {
    let mut conn = Conn::new(1);
    let out = iqr().feed(&mut conn, &unhex("50 00 00 FF FF 03 00 01 20"), &Events::disabled());
    assert!(out.close && out.replies.is_empty());
}

#[test]
fn a_length_below_6_gets_c061_and_the_connection_stays() {
    // L = 4: timer and command only; the missing subcommand is 0 in the error information.
    let s = iqr();
    let replies = exchange(&s, &format!("50 00 00 FF FF 03 00 04 00 00 00 01 04 {G2}"));
    assert_eq!(replies, vec![error("61 C0", "01 04 00 00"), g2_reply()]);
    assert_eq!(exchange(&s, "50 00 00 FF FF 03 00 00 00"), vec![error("61 C0", "00 00 00 00")]);
}

#[test]
fn a_short_frame_given_to_handle_does_not_panic() {
    let s = iqr();
    let input = unhex(G5);
    for n in 0..input.len() {
        let reply = s.handle(1, &input[..n], &Events::disabled());
        assert!(reply.len() >= 11, "{n}");
    }
}

#[test]
fn validation_order_and_codes() {
    let s = iqr();
    // An unknown command and an unknown subcommand: C059.
    assert_eq!(one(&s, &frame("01 08 00 00")), error("59 C0", "01 08 00 00"));
    assert_eq!(one(&s, &frame("01 04 80 00 64 00 00 A8 01 00")), error("59 C0", "01 04 80 00"));
    // L one byte short or long for 0401: C061.
    assert_eq!(one(&s, &frame("01 04 00 00 64 00 00 A8 01")), error("61 C0", "01 04 00 00"));
    assert_eq!(one(&s, &frame("01 04 00 00 64 00 00 A8 01 00 00")), error("61 C0", "01 04 00 00"));
    // 0 points; 7169 bits; an unknown device code; bit units on a word device.
    assert_eq!(one(&s, &frame("01 04 00 00 64 00 00 A8 00 00")), error("51 C0", "01 04 00 00"));
    assert_eq!(one(&s, &frame("01 04 01 00 00 00 00 90 01 1C")), error("52 C0", "01 04 01 00"));
    assert_eq!(one(&s, &frame("01 04 00 00 00 00 00 01 01 00")), error("5B C0", "01 04 00 00"));
    assert_eq!(one(&s, &frame("01 04 01 00 64 00 00 A8 01 00")), error("5C C0", "01 04 01 00"));
    // The count is checked before the device: 961 words of an unknown code is C051.
    assert_eq!(one(&s, &frame("01 04 00 00 00 00 00 01 C1 03")), error("51 C0", "01 04 00 00"));
    // A device with 0 points (S on iq-r) is in range nowhere.
    assert_eq!(one(&s, &frame("01 04 01 00 00 00 00 98 01 00")), error("56 C0", "01 04 01 00"));
}

#[test]
fn random_read_counts_and_rules() {
    let s = iqr();
    // No entries: C054. L too short for the entries announced: C061.
    assert_eq!(one(&s, &frame("03 04 00 00 00 00")), error("54 C0", "03 04 00 00"));
    assert_eq!(one(&s, &frame("03 04 00 00 02 00 64 00 00 A8")), error("61 C0", "03 04 00 00"));
    // 193 word entries in the Q/L format, 97 in the iQ-R format: C054.
    let ql = frame(&format!("03 04 00 00 C1 00{}", " 64 00 00 A8".repeat(193)));
    assert_eq!(one(&s, &ql), error("54 C0", "03 04 00 00"));
    let iq = frame(&format!("03 04 02 00 61 00{}", " 64 00 00 00 A8 00".repeat(97)));
    assert_eq!(one(&s, &iq), error("54 C0", "03 04 02 00"));
    // 192 entries are fine.
    let max = frame(&format!("03 04 00 00 C0 00{}", " 64 00 00 A8".repeat(192)));
    assert_eq!(one(&s, &max), ok(&" C7 CF".repeat(192)));
    // LZ0 as a word entry: C05B. LZ0 as a double-word entry in the Q/L format: 100000.
    assert_eq!(one(&s, &frame("03 04 00 00 01 00 00 00 00 62")), error("5B C0", "03 04 00 00"));
    assert_eq!(one(&s, &frame("03 04 00 00 00 01 00 00 00 62")), ok("A0 86 01 00"));
    // D18431 as a double word runs past the end of D.
    assert_eq!(one(&s, &frame("03 04 00 00 00 01 FF 47 00 A8")), error("56 C0", "03 04 00 00"));
    // Double words of a word and a bit device: D106/D107 low word first, M0..M31.
    assert_eq!(one(&s, &frame("03 04 00 00 00 02 6A 00 00 A8 00 00 00 90")), ok("2E FD 69 B6 A5 3C 00 00"));
}

#[test]
fn other_devices_of_the_default_map() {
    let s = iqr();
    at_scan(&s, 50, 0); // t = 0.5 s: blink_1hz is off, so is Y0 (the lamp)
    // W0, W1, R0, ZR1 (the memory of R1), Z0, Z1, then L0, B0 and Y0 as 16-bit words (B7 and Y1 on): 0403.
    let request = frame("03 04 00 00 09 00 00 00 00 B4 01 00 00 B4 00 00 00 AF 01 00 00 B0 00 00 00 CC 01 00 00 CC
                         00 00 00 92 00 00 00 A0 00 00 00 9D");
    assert_eq!(one(&s, &request), ok("34 12 78 56 E8 03 D0 07 0A 00 FF FF 01 00 81 00 02 00"));
    // M0 in word units through 0401: the 16 relays as one word (other clients; SFC never sends this).
    assert_eq!(one(&s, &frame("01 04 00 00 00 00 00 90 01 00")), ok("A5 3C"));
    // The Shift-JIS string, the UTF-16 string and the Status struct, raw.
    assert_eq!(one(&s, &frame("01 04 00 00 0E 01 00 A8 03 00")), ok("D3 B0 C0 B0 00 00"));
    assert_eq!(one(&s, &frame("01 04 00 00 DC 00 00 A8 02 00")), ok("53 00 46 00"));
    assert_eq!(one(&s, &frame("01 04 00 00 40 01 00 A8 02 00")), ok("02 00 05 00"));
}

#[test]
fn absent_families_follow_the_profile() {
    let (q, iqf) = (Server::new("q").unwrap(), Server::new("iq-f").unwrap());
    // V0 and DX0..DX3 in bit units: present on iq-r and q, absent on iq-f. DX reads the X memory.
    let v0 = frame("01 04 01 00 00 00 00 94 01 00");
    assert_eq!(one(&iqr(), &v0), ok("00"));
    assert_eq!(one(&q, &v0), ok("00"));
    assert_eq!(one(&iqf, &v0), error("5B C0", "01 04 01 00"));
    let dx0 = frame("01 04 01 00 00 00 00 A2 04 00");
    assert_eq!(one(&iqr(), &dx0), ok("10 11"));
    assert_eq!(one(&iqf, &dx0), error("5B C0", "01 04 01 00"));
    // X1023 is the last input of an FX5U.
    assert_eq!(one(&iqf, &frame("01 04 01 00 FF 03 00 9C 01 00")), ok("00"));
    assert_eq!(one(&iqf, &frame("01 04 01 00 FF 03 00 9C 02 00")), error("56 C0", "01 04 01 00"));
    // The tail string sits in the last 8 words of D on every profile.
    for (name, head) in [("q", "F8 2F"), ("l", "F8 2F"), ("iq-f", "38 1F")] {
        let request = frame(&format!("01 04 00 00 {head} 00 A8 01 00"));
        assert_eq!(one(&Server::new(name).unwrap(), &request), ok("54 41"), "{name}");
    }
}

#[test]
fn long_timer_in_4_word_blocks_and_long_counter() {
    let s = iqr();
    at_scan(&s, 1234, 0); // t = 12.34 s: coil on, value capped at 10 s, contact on
    assert_eq!(one(&s, &frame("01 04 00 00 00 00 00 52 04 00")), ok("80 96 98 00 03 00 00 00"));
    assert_eq!(one(&s, &frame("01 04 00 00 00 00 00 52 03 00")), error("5C C0", "01 04 00 00"));
    // LTN0 in bit units is C05C; LTS0 and LCN0 in word units, C05B; LCC0..LCC3 in bit units are allowed
    // (LCC0 = SM412, on).
    assert_eq!(one(&s, &frame("01 04 01 00 00 00 00 52 01 00")), error("5C C0", "01 04 01 00"));
    assert_eq!(one(&s, &frame("01 04 00 00 00 00 00 51 01 00")), error("5B C0", "01 04 00 00"));
    assert_eq!(one(&s, &frame("01 04 00 00 00 00 00 56 01 00")), error("5B C0", "01 04 00 00"));
    assert_eq!(one(&s, &frame("01 04 01 00 00 00 00 54 04 00")), ok("10 00"));
    // LCN0 = floor(t) = 12 and LTN0 = 10 000 000 µs as double-word entries.
    assert_eq!(one(&s, &frame("03 04 00 00 00 02 00 00 00 56 00 00 00 52")), ok("0C 00 00 00 80 96 98 00"));
}

#[test]
fn timer_counter_and_special_registers_at_a_fixed_scan() {
    let s = iqr();
    at_scan(&s, 1234, 0);
    // TN0 = 100, CN0 = 12 mod 11 = 1, SD412 = 12, SD420 = 1234, SD520 = 10 ms; then TS0, TC0, CC0 on and CS0
    // off, each as a 16-bit word whose bit 0 is the device.
    let request = frame("03 04 00 00 09 00 00 00 00 C2 00 00 00 C5 9C 01 00 A9 A4 01 00 A9 08 02 00 A9
                         00 00 00 C1 00 00 00 C0 00 00 00 C3 00 00 00 C4");
    assert_eq!(one(&s, &request), ok("64 00 01 00 0C 00 D2 04 0A 00 01 00 01 00 01 00 00 00"));
    // The first scan: SM402 on, SM403 off.
    let first = iqr();
    at_scan(&first, 0, 0);
    assert_eq!(one(&first, &frame("01 04 01 00 92 01 00 91 02 00")), ok("10"));
}

#[test]
fn the_clock_registers_follow_the_profile() {
    let base = unix_ms(2024, 6, 15, 12, 34, 56, 789); // a Saturday
    let read = |name: &str, request: &str| {
        let s = Server::new(name).unwrap();
        at_scan(&s, 0, base);
        one(&s, &frame(request))
    };
    // SD210 on: binary year, month, day, hour, minute, second, day of week on iq-r and iq-f.
    let binary = ok("E8 07 06 00 0F 00 0C 00 22 00 38 00 06 00");
    assert_eq!(read("iq-r", "01 04 00 00 D2 00 00 A9 07 00"), binary);
    assert_eq!(read("iq-f", "01 04 00 00 D2 00 00 A9 07 00"), binary);
    // BCD 24/06, 15/12, 34/56, 20/day of week on q and l.
    assert_eq!(read("q", "01 04 00 00 D2 00 00 A9 04 00"), ok("06 24 12 15 56 34 06 20"));
    assert_eq!(read("l", "01 04 00 00 D2 00 00 A9 04 00"), ok("06 24 12 15 56 34 06 20"));
    // The FX copy: SD8013 second ... SD8019 day of week.
    assert_eq!(read("iq-f", "01 04 00 00 4D 1F 00 A9 07 00"), ok("38 00 22 00 0C 00 0F 00 06 00 E8 07 06 00"));
}

#[test]
fn device_point_registers() {
    // iq-r: SD260/261 = X 12288; SD300 Z 20, SD302 LZ 2, SD306/307 ZR 32768.
    assert_eq!(one(&iqr(), &frame("01 04 00 00 04 01 00 A9 02 00")), ok("00 30 00 00"));
    let registers = ok("14 00 00 00 02 00 00 00 00 00 00 00 00 80 00 00");
    assert_eq!(one(&iqr(), &frame("01 04 00 00 2C 01 00 A9 08 00")), registers);
    // q: SD290 = X 8192, SD302 = D 12288.
    let q = Server::new("q").unwrap();
    assert_eq!(one(&q, &frame("01 04 00 00 22 01 00 A9 01 00")), ok("00 20"));
    assert_eq!(one(&q, &frame("01 04 00 00 2E 01 00 A9 01 00")), ok("00 30"));
    // iq-f: SD304/305 = R 32768, and SD306 (ZR) and SD272 (V) stay 0 because the families are absent.
    let iqf = Server::new("iq-f").unwrap();
    assert_eq!(one(&iqf, &frame("01 04 00 00 30 01 00 A9 04 00")), ok("00 80 00 00 00 00 00 00"));
    assert_eq!(one(&iqf, &frame("01 04 00 00 10 01 00 A9 02 00")), ok("00 00 00 00"));
}

#[tokio::test]
async fn v0_a_probe_then_a_live_connection() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(Arc::new(iqr()).serve(listener, Events::disabled()));
    // The harness readiness probe connects and closes without sending.
    drop(TcpStream::connect(addr).await.unwrap());
    let mut s = TcpStream::connect(addr).await.unwrap();
    // Vector 0: no bytes are sent unasked.
    let mut byte = [0u8; 1];
    assert!(tokio::time::timeout(Duration::from_millis(200), s.read(&mut byte)).await.is_err());
    // Two requests in one write: both replies, in order.
    s.write_all(&unhex(&format!("{G2} {G5}"))).await.unwrap();
    let expected = unhex(&format!("{} {}", g2_reply(), want(G5_REPLY)));
    let mut got = vec![0u8; expected.len()];
    tokio::time::timeout(Duration::from_secs(5), s.read_exact(&mut got)).await.unwrap().unwrap();
    assert_eq!(hex(&got), hex(&expected));
    // An idle connection stays open and still answers.
    tokio::time::sleep(Duration::from_millis(100)).await;
    s.write_all(&unhex(G1)).await.unwrap();
    let mut got = vec![0u8; unhex(&g1_reply()).len()];
    tokio::time::timeout(Duration::from_secs(5), s.read_exact(&mut got)).await.unwrap().unwrap();
    assert_eq!(hex(&got), g1_reply());
}
