// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! Modbus golden frames: request bytes exactly as SFC's modbus-tcp adapter sends them
//! (MBAPHeader.kt:114-126, RequestBase.kt:69-74), expected replies from the default map.
#![cfg(feature = "modbus")]

use omni_plc_sim::core::codec::{hex, unhex};
use omni_plc_sim::core::events::Events;
use omni_plc_sim::protocols::modbus::{Conn, Server};

fn exchange(server: &Server, request: &str) -> Vec<String> {
    let mut conn = Conn::new(1);
    let out = server.feed(&mut conn, &unhex(request), &Events::disabled());
    assert!(!out.close, "connection closed on {request}");
    out.replies.iter().map(|r| hex(r)).collect()
}

fn one(server: &Server, request: &str) -> String {
    let replies = exchange(server, request);
    assert_eq!(replies.len(), 1, "{request}");
    replies[0].clone()
}

fn generic() -> Server {
    Server::new("generic").unwrap()
}

const G3_WORDS: &str = "
0001 0000 00A5 FF9C 00C8 CFC7 D431 D431 B669 FD2E B2D0 5E00 B2D0 5E00 FFFF FEE0 8E04 FB35 0000 0B3A
73CE 2FF2 4640 E600 C0F8 1CD7 0000 0000 0000 04D2 5346 432D 5349 4D00 0000 0000 0000 0000 4653 2D43
4953 004D 0000 0000 0000 0000 1234 A5C3 3128 02B3 2C95 2406 1512 3456 7897 07E8 060F 070C 2238 2F07
2F40 07E8 0006 000F 000C 0022 0038 0315 666D 8A70 3039 1A85 E600 4640 4046 00E6 00E6 4046 FD2E B669
0000 FFFF 1234 AAAA 5555 7FFF 8000 3FFF 4000 0000 0001 FFFF 03E8 FC18 7FFF 8000 3039 0000 0000 3F80
0000 BF80 0000 4049 0FDB 0007 44BB 8800 0001 0005";

#[test]
fn g1_coils_static() {
    assert_eq!(one(&generic(), "00 01 00 00 00 06 01 01 00 00 00 0A"), hex(&unhex("00 01 00 00 00 05 01 01 02 95 02")));
}

#[test]
fn g2_discrete_inputs_static() {
    assert_eq!(one(&generic(), "00 02 00 00 00 06 01 02 00 00 00 0A"), hex(&unhex("00 02 00 00 00 05 01 02 02 6A 01")));
}

#[test]
fn g3_holding_registers_static_block() {
    let want = format!("00 03 00 00 00 DF 01 03 DC {G3_WORDS}");
    assert_eq!(one(&generic(), "00 03 00 00 00 06 01 03 00 00 00 6E"), hex(&unhex(&want)));
}

#[test]
fn g4_input_registers_analog_counts() {
    assert_eq!(
        one(&generic(), "00 04 00 00 00 06 01 04 00 08 00 08"),
        hex(&unhex("00 04 00 00 00 13 01 04 10 00 00 1B 00 36 00 51 00 6C 00 7E FF 7F FF 94 00"))
    );
}

#[test]
fn g5_single_reads_without_optimization() {
    let s = generic();
    assert_eq!(one(&s, "00 01 00 00 00 06 01 03 00 05 00 01"), hex(&unhex("00 01 00 00 00 05 01 03 02 CF C7")));
    assert_eq!(one(&s, "00 02 00 00 00 06 01 03 00 16 00 02"), hex(&unhex("00 02 00 00 00 07 01 03 04 46 40 E6 00")));
    assert_eq!(
        one(&s, "00 03 00 00 00 06 01 03 00 1E 00 08"),
        hex(&unhex("00 03 00 00 00 13 01 03 10 53 46 43 2D 53 49 4D 00 00 00 00 00 00 00 00 00"))
    );
    assert_eq!(one(&s, "00 04 00 00 00 06 01 03 00 18 00 04"), hex(&unhex("00 04 00 00 00 0B 01 03 08 C0 F8 1C D7 00 00 00 00")));
}

#[test]
fn g6_pipelined_frames_in_one_buffer() {
    let replies = exchange(&generic(), "00 01 00 00 00 06 01 03 00 05 00 01 00 02 00 00 00 06 01 03 00 16 00 02");
    assert_eq!(replies, vec![hex(&unhex("00 01 00 00 00 05 01 03 02 CF C7")), hex(&unhex("00 02 00 00 00 07 01 03 04 46 40 E6 00"))]);
}

#[test]
fn g7_g8_s7_1200_table_limits() {
    let s = Server::new("s7-1200").unwrap();
    assert_eq!(one(&s, "00 01 00 00 00 06 01 04 02 00 00 01"), hex(&unhex("00 01 00 00 00 03 01 84 02")));
    assert_eq!(one(&s, "00 01 00 00 00 06 01 03 03 E6 00 04"), hex(&unhex("00 01 00 00 00 03 01 83 02")));
}

#[test]
fn g10_g11_g12_unit_and_transaction_echo() {
    let s = generic();
    assert_eq!(one(&s, "00 01 00 00 00 06 FF 03 00 05 00 01"), hex(&unhex("00 01 00 00 00 05 FF 03 02 CF C7")));
    assert_eq!(one(&s, "00 01 00 00 00 06 00 03 00 05 00 01"), hex(&unhex("00 01 00 00 00 05 00 03 02 CF C7")));
    assert_eq!(one(&s, "FF FF 00 00 00 06 01 03 00 05 00 01"), hex(&unhex("FF FF 00 00 00 05 01 03 02 CF C7")));
}

#[test]
fn t1_t2_device_identification() {
    let s = generic();
    let mut want = unhex("00 01 00 00 00 33 01 2B 0E 01 83 00 00 03 00 13");
    want.extend_from_slice(b"Amazon Web Services");
    want.extend_from_slice(&[0x01, 0x0E]);
    want.extend_from_slice(b"OPS-MB-GENERIC");
    want.extend_from_slice(&[0x02, 0x04]);
    want.extend_from_slice(b"V1.0");
    assert_eq!(one(&s, "00 01 00 00 00 05 01 2B 0E 01 00"), hex(&want));
    assert_eq!(
        one(&s, "00 02 00 00 00 05 01 2B 0E 04 80"),
        hex(&unhex("00 02 00 00 00 12 01 2B 0E 04 83 00 00 01 80 08 53 49 4D 2D 30 30 30 31"))
    );
    // The S7-1200 MB_SERVER has no device identification.
    let s7 = Server::new("s7-1200").unwrap();
    assert_eq!(one(&s7, "00 01 00 00 00 05 01 2B 0E 01 00"), hex(&unhex("00 01 00 00 00 03 01 AB 01")));
}

#[test]
fn t3_to_t6_validation() {
    let s = generic();
    assert_eq!(one(&s, "00 01 00 00 00 02 01 11"), hex(&unhex("00 01 00 00 00 03 01 91 01")));
    assert_eq!(one(&s, "00 01 00 00 00 06 01 03 00 00 00 7E"), hex(&unhex("00 01 00 00 00 03 01 83 03")));
    assert_eq!(one(&s, "00 01 00 00 00 07 01 03 00 00 00 01 00"), hex(&unhex("00 01 00 00 00 03 01 83 03")));
    assert!(exchange(&s, "00 01 00 01 00 06 01 03 00 00 00 01").is_empty(), "protocol id 1 is dropped");
    // Writes are not simulated: a read-only device answers illegal function.
    assert_eq!(one(&s, "00 01 00 00 00 06 01 05 00 00 FF 00"), hex(&unhex("00 01 00 00 00 03 01 85 01")));
}

#[test]
fn a_bad_length_closes_the_connection() {
    let mut conn = Conn::new(1);
    let out = generic().feed(&mut conn, &unhex("00 01 00 00 01 00 01 03"), &Events::disabled());
    assert!(out.close && out.replies.is_empty());
}

#[test]
fn byte_by_byte_gives_the_same_replies() {
    let s = generic();
    let input = unhex("00 01 00 00 00 06 01 01 00 00 00 0A 00 03 00 00 00 06 01 03 00 00 00 6E 00 04 00 00 00 06 01 04 00 08 00 08");
    let whole = s.feed(&mut Conn::new(1), &input, &Events::disabled()).replies;
    let mut conn = Conn::new(2);
    let mut split = Vec::new();
    for b in &input {
        split.extend(s.feed(&mut conn, &[*b], &Events::disabled()).replies);
    }
    assert_eq!(whole.len(), 3);
    assert_eq!(whole, split);
}

#[test]
fn modicon_word_and_byte_order() {
    let s = Server::new("modicon-m340").unwrap();
    // real 12345.5 low word first; the string with its first character in the low byte.
    assert_eq!(one(&s, "00 01 00 00 00 06 01 03 00 16 00 02"), hex(&unhex("00 01 00 00 00 07 01 03 04 E6 00 46 40")));
    assert_eq!(
        one(&s, "00 02 00 00 00 06 01 03 00 1E 00 04"),
        hex(&unhex("00 02 00 00 00 0B 01 03 08 46 53 2D 43 49 53 00 4D"))
    );
    // FC 4 reads the holding registers.
    assert_eq!(one(&s, "00 03 00 00 00 06 01 04 00 05 00 01"), hex(&unhex("00 03 00 00 00 05 01 04 02 CF C7")));
}
