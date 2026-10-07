// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! ADS golden frames: request bytes exactly as SFC's ads adapter builds them (RequestResponse.kt:54-82,
//! GetSymbolsLengthRequest.kt:25-34, GetSymbolsRequest.kt:26-37, MultiReadRequest.kt:27-59), expected
//! replies from the default map. The client is 192.168.100.1.1.1:32905, the PLC 192.168.100.10.1.1:851
//! (profile tc3-ipc); invoke ids follow Client.kt:25-30.
#![cfg(feature = "ads")]

use std::collections::BTreeMap;

use omni_plc_sim::core::codec::{hex, unhex};
use omni_plc_sim::core::engine::Scan;
use omni_plc_sim::core::events::Events;
use omni_plc_sim::core::signal::Bank;
use omni_plc_sim::protocols::ads::{Conn, Server};

fn feed(server: &Server, request: &[u8]) -> Vec<Vec<u8>> {
    let mut conn = Conn::new(1);
    let out = server.feed(&mut conn, request, &Events::disabled());
    assert!(!out.close, "connection closed on {}", hex(request));
    out.replies
}

fn exchange(server: &Server, request: &str) -> Vec<String> {
    feed(server, &unhex(request)).iter().map(|r| hex(r)).collect()
}

fn one(server: &Server, request: &str) -> String {
    let replies = exchange(server, request);
    assert_eq!(replies.len(), 1, "{request}");
    replies[0].clone()
}

fn tc3() -> Server {
    Server::new("tc3-ipc").unwrap()
}

/// SHA-256 (FIPS 180-4), to compare the 9 KB upload with the spec's digests without a dependency.
fn sha256(data: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
    ];
    let mut h: [u32; 8] =
        [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    let mut msg = data.to_vec();
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&(data.len() as u64 * 8).to_be_bytes());
    for block in msg.chunks(64) {
        let mut w = [0u32; 64];
        for (i, word) in block.chunks(4).enumerate() {
            w[i] = u32::from_be_bytes([word[0], word[1], word[2], word[3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16].wrapping_add(s0).wrapping_add(w[i - 7]).wrapping_add(s1);
        }
        let mut v = h;
        for i in 0..64 {
            let s1 = v[4].rotate_right(6) ^ v[4].rotate_right(11) ^ v[4].rotate_right(25);
            let ch = (v[4] & v[5]) ^ (!v[4] & v[6]);
            let t1 = v[7].wrapping_add(s1).wrapping_add(ch).wrapping_add(K[i]).wrapping_add(w[i]);
            let s0 = v[0].rotate_right(2) ^ v[0].rotate_right(13) ^ v[0].rotate_right(22);
            let maj = (v[0] & v[1]) ^ (v[0] & v[2]) ^ (v[1] & v[2]);
            v = [t1.wrapping_add(s0.wrapping_add(maj)), v[0], v[1], v[2], v[3].wrapping_add(t1), v[4], v[5], v[6]];
        }
        for (x, y) in h.iter_mut().zip(v) {
            *x = x.wrapping_add(y);
        }
    }
    h.iter().map(|x| format!("{x:08x}")).collect()
}

const V1: &str = "
00 00 2c 00 00 00 c0 a8 64 0a 01 01 53 03 c0 a8 64 01 01 01 89 80 02 00 04 00 0c 00 00 00 00 00
00 00 01 00 00 00 0f f0 00 00 00 00 00 00 30 00 00 00";

const V1_REPLY: &str = "
00 00 58 00 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 0a 01 01 53 03 02 00 05 00 38 00 00 00 00 00
00 00 01 00 00 00 00 00 00 00 30 00 00 00 71 00 00 00 e4 22 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 e4 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00";

const V2: &str = "
00 00 2c 00 00 00 c0 a8 64 0a 01 01 53 03 c0 a8 64 01 01 01 89 80 02 00 04 00 0c 00 00 00 00 00
00 00 02 00 00 00 0b f0 00 00 00 00 00 00 e4 22 00 00";

const V2_HEAD: &str = "
00 00 0c 23 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 0a 01 01 53 03 02 00 05 00 ec 22 00 00 00 00
00 00 02 00 00 00 00 00 00 00 e4 22 00 00";

/// GVL_Static.bBoolTrue: entryLength 84, group 0x4040, offset 0x1000, size 1, ADST_BIT, TYPEGUID, then
/// name, type and comment, the type GUID of BOOL and 2 bytes of padding.
const V2_FIRST_ENTRY: &str = "
54 00 00 00 40 40 00 00 00 10 00 00 01 00 00 00 21 00 00 00 08 00 00 00 14 00 04 00 09 00
47 56 4c 5f 53 74 61 74 69 63 2e 62 42 6f 6f 6c 54 72 75 65 00  42 4f 4f 4c 00  62 6f 6f 6c 5f 74 72 75 65 00
95 19 07 18 00 00 00 00 00 00 00 00 00 00 00 30  00 00";

/// bool_true, byte, sint, int, uint, dint, udint, real, lreal.
const V3: &str = "
00 00 9c 00 00 00 c0 a8 64 0a 01 01 53 03 c0 a8 64 01 01 01 89 80 09 00 04 00 7c 00 00 00 00 00
00 00 03 00 00 00 80 f0 00 00 09 00 00 00 3f 00 00 00 6c 00 00 00 40 40 00 00 00 10 00 00 01 00
00 00 40 40 00 00 02 10 00 00 01 00 00 00 40 40 00 00 03 10 00 00 01 00 00 00 40 40 00 00 06 10
00 00 02 00 00 00 40 40 00 00 08 10 00 00 02 00 00 00 40 40 00 00 0c 10 00 00 04 00 00 00 40 40
00 00 10 10 00 00 04 00 00 00 40 40 00 00 30 10 00 00 04 00 00 00 40 40 00 00 38 10 00 00 08 00
00 00";

const V3_REPLY: &str = "
00 00 67 00 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 0a 01 01 53 03 09 00 05 00 47 00 00 00 00 00
00 00 03 00 00 00 00 00 00 00 3f 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 01 a5 9c c7 cf 31 d4 2e fd 69 b6 00 5e d0
b2 00 e6 40 46 00 00 00 00 d7 1c f8 c0";

#[test]
fn v1_upload_info() {
    assert_eq!(one(&tc3(), V1), hex(&unhex(V1_REPLY)));
}

#[test]
fn v2_symbol_upload_in_both_type_name_spellings() {
    assert_eq!(sha256(b"abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    let reply = feed(&tc3(), &unhex(V2)).remove(0);
    assert_eq!(reply.len(), 8978);
    assert_eq!(hex(&reply[..46]), hex(&unhex(V2_HEAD)));
    assert_eq!(hex(&reply[46..130]), hex(&unhex(V2_FIRST_ENTRY)));
    assert_eq!(sha256(&reply[46..]), "d15cb9afcedc1b51c8a33a549001c3ff4a92c8247249d19467521383f9b23166");
    assert_eq!(sha256(&reply), "fe1a59b37eb54f06f817fba75747161e0e39b1f0233fe55825b7443a3ef9b035");

    // DT and TOD declarations reported with the short names: 36 bytes less.
    let alias = Server::with_alias_type_names("tc3-ipc").unwrap();
    let info = feed(&alias, &unhex(V1)).remove(0);
    assert_eq!(hex(&info[50..52]), "c0 22");
    let request = unhex(&V2.replace("e4 22 00 00", "c0 22 00 00"));
    let reply = feed(&alias, &request).remove(0);
    assert_eq!(reply.len(), 8942);
    assert_eq!(hex(&[reply[2], reply[3], reply[26], reply[27], reply[42], reply[43]]), "e8 22 c8 22 c0 22");
    assert_eq!(sha256(&reply[46..]), "3a4c13b4ee07eeb1f453c144382e3c27627239a034091045f6a1f8efabf83e36");
    assert_eq!(sha256(&reply), "b57250319d3f1f7a5085fe2dea9d14bcca0dd645917ad8d521fd82e794be59dc");
}

#[test]
fn v3_sum_read_of_nine_scalars() {
    assert_eq!(one(&tc3(), V3), hex(&unhex(V3_REPLY)));
}

#[test]
fn v4_sum_read_of_strings_times_and_dates() {
    // lint, ulint, string, time, ltime, date, date_and_time; invoke 4.
    let request = "
00 00 84 00 00 00 c0 a8 64 0a 01 01 53 03 c0 a8 64 01 01 01 89 80 09 00 04 00 64 00 00 00 00 00
00 00 04 00 00 00 80 f0 00 00 07 00 00 00 91 00 00 00 54 00 00 00 40 40 00 00 18 10 00 00 08 00
00 00 40 40 00 00 20 10 00 00 08 00 00 00 40 40 00 00 40 10 00 00 51 00 00 00 40 40 00 00 94 10
00 00 04 00 00 00 40 40 00 00 98 10 00 00 08 00 00 00 40 40 00 00 a0 10 00 00 04 00 00 00 40 40
00 00 a4 10 00 00 04 00 00 00";
    // The STRING(80) slot is 'SFC-SIM' and 74 NULs.
    let want = format!("
00 00 b9 00 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 0a 01 01 53 03 09 00 05 00 99 00 00 00 00 00
00 00 04 00 00 00 00 00 00 00 91 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 35 fb 04 8e e0 fe ff ff f2 2f ce 73 3a 0b 00 00 53 46 43 2d 53 49
4d {} d2 04 00 00 d2 02 96 49 00 00 00 00 80 8f f3 65 70 40 f4 65", "00 ".repeat(74));
    let reply = one(&tc3(), request);
    assert_eq!(unhex(&reply).len(), 191);
    assert_eq!(reply, hex(&unhex(&want)));
}

#[test]
fn v5_sum_read_of_structs_arrays_and_other_groups() {
    // runtime_version, lib_version, array_int, array_byte_2d, io_setpoint (0xF030), io_status (0x4020).
    let request = "
00 00 78 00 00 00 c0 a8 64 0a 01 01 53 03 c0 a8 64 01 01 01 89 80 09 00 04 00 58 00 00 00 00 00
00 00 05 00 00 00 80 f0 00 00 06 00 00 00 58 00 00 00 48 00 00 00 40 40 00 00 10 40 00 00 08 00
00 00 40 40 00 00 00 41 00 00 24 00 00 00 40 40 00 00 56 11 00 00 0a 00 00 00 40 40 00 00 6c 11
00 00 06 00 00 00 30 f0 00 00 02 00 00 00 02 00 00 00 20 40 00 00 00 00 00 00 02 00 00 00";
    let want = "
00 00 80 00 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 0a 01 01 53 03 09 00 05 00 60 00 00 00 00 00
00 00 05 00 00 00 00 00 00 00 58 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 03 00 01 00 b8 0f 38 00 03 00 03 00 03 00 00 00 00 00 00 00 33 2e 33 2e 33 2e
30 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 38 ff 9c ff 00 00 64 00 c8 00 01 02 03 04
05 06 dc 05 c3 00";
    assert_eq!(one(&tc3(), request), hex(&unhex(want)));
}

#[test]
fn v6_v7_router_errors_in_the_ams_header() {
    let s = tc3();
    // AMS port 853 is not served.
    assert_eq!(
        one(&s, &V1.replace("01 01 53 03 c0", "01 01 55 03 c0")),
        hex(&unhex("
00 00 20 00 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 0a 01 01 55 03 02 00 05 00 00 00 00 00 06 00
00 00 01 00 00 00"))
    );
    // NetId 192.168.100.99.1.1 is not this PLC.
    assert_eq!(
        one(&s, &V1.replace("c0 a8 64 0a", "c0 a8 64 63")),
        hex(&unhex("
00 00 20 00 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 63 01 01 53 03 02 00 05 00 00 00 00 00 07 00
00 00 01 00 00 00"))
    );
}

#[test]
fn v8_failed_items_keep_their_zero_filled_slots() {
    // (0x4040, 0x1006, 2), (0x1234, 0, 4), (0x4040, 0x10000, 4), (0x4040, 0xFFFE, 4); invoke 6.
    let request = "
00 00 60 00 00 00 c0 a8 64 0a 01 01 53 03 c0 a8 64 01 01 01 89 80 09 00 04 00 40 00 00 00 00 00
00 00 06 00 00 00 80 f0 00 00 04 00 00 00 1e 00 00 00 30 00 00 00 40 40 00 00 06 10 00 00 02 00
00 00 34 12 00 00 00 00 00 00 04 00 00 00 40 40 00 00 00 00 01 00 04 00 00 00 40 40 00 00 fe ff
00 00 04 00 00 00";
    // Item results 0, 0x702, 0x703, 0x705.
    let want = "
00 00 46 00 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 0a 01 01 53 03 09 00 05 00 26 00 00 00 00 00
00 00 06 00 00 00 00 00 00 00 1e 00 00 00 00 00 00 00 02 07 00 00 03 07 00 00 05 07 00 00 c7 cf
00 00 00 00 00 00 00 00 00 00 00 00";
    assert_eq!(one(&tc3(), request), hex(&unhex(want)));
}

#[test]
fn v13_upload_shorter_than_nsymsize() {
    let request = V2.replace("e4 22 00 00", "40 1f 00 00");
    let want = "
00 00 28 00 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 0a 01 01 53 03 02 00 05 00 08 00 00 00 00 00
00 00 02 00 00 00 05 07 00 00 00 00 00 00";
    assert_eq!(one(&tc3(), &request), hex(&unhex(want)));
}

#[test]
fn v9_v10_device_info_and_state() {
    let s = tc3();
    assert_eq!(
        one(&s, "00 00 20 00 00 00 c0 a8 64 0a 01 01 53 03 c0 a8 64 01 01 01 89 80 01 00 04 00 00 00 00 00 00 00
                 00 00 07 00 00 00"),
        hex(&unhex("
00 00 38 00 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 0a 01 01 53 03 01 00 05 00 18 00 00 00 00 00
00 00 07 00 00 00 00 00 00 00 03 01 b8 0f 50 6c 63 33 30 20 41 70 70 00 00 00 00 00 00 00"))
    );
    assert_eq!(
        one(&s, "00 00 20 00 00 00 c0 a8 64 0a 01 01 53 03 c0 a8 64 01 01 01 89 80 04 00 04 00 00 00 00 00 00 00
                 00 00 08 00 00 00"),
        hex(&unhex("00 00 28 00 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 0a 01 01 53 03 04 00 05 00 08 00 00 00 00 00
                    00 00 08 00 00 00 00 00 00 00 05 00 00 00"))
    );
}

#[test]
fn v11_v12_symbol_handles_are_not_simulated() {
    // Handles are out of scope: 0xF003 (handle by name) and 0xF005 (value by handle) answer 0x702, as
    // any group this device does not serve. The spec's full vectors expect handle 1 and 3.75.
    let s = tc3();
    let mut conn = Conn::new(1);
    let v11 = "
00 00 4b 00 00 00 c0 a8 64 0a 01 01 53 03 c0 a8 64 01 01 01 89 80 09 00 04 00 2b 00 00 00 00 00
00 00 09 00 00 00 03 f0 00 00 00 00 00 00 04 00 00 00 1b 00 00 00 47 56 4c 5f 53 74 61 74 69 63
2e 73 74 4d 6f 74 6f 72 2e 66 43 75 72 72 65 6e 74";
    let v12 = "
00 00 2c 00 00 00 c0 a8 64 0a 01 01 53 03 c0 a8 64 01 01 01 89 80 02 00 04 00 0c 00 00 00 00 00
00 00 0a 00 00 00 05 f0 00 00 01 00 00 00 04 00 00 00";
    let out = s.feed(&mut conn, &unhex(&format!("{v11} {v12}")), &Events::disabled());
    assert_eq!(out.replies.iter().map(|r| hex(r)).collect::<Vec<_>>(), vec![
        hex(&unhex("00 00 28 00 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 0a 01 01 53 03 09 00 05 00 08 00 00 00
                    00 00 00 00 09 00 00 00 02 07 00 00 00 00 00 00")),
        hex(&unhex("00 00 28 00 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 0a 01 01 53 03 02 00 05 00 08 00 00 00
                    00 00 00 00 0a 00 00 00 02 07 00 00 00 00 00 00")),
    ]);
    // The REAL V12 would read through the handle: GVL_Static.stMotor.fCurrent at 0x1198 + 4.
    assert_eq!(
        one(&s, "00 00 2c 00 00 00 c0 a8 64 0a 01 01 53 03 c0 a8 64 01 01 01 89 80 02 00 04 00 0c 00 00 00 00 00
                 00 00 0a 00 00 00 40 40 00 00 9c 11 00 00 04 00 00 00"),
        hex(&unhex("00 00 2c 00 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 0a 01 01 53 03 02 00 05 00 0c 00 00 00 00 00
                    00 00 0a 00 00 00 00 00 00 00 04 00 00 00 00 00 70 40"))
    );
}

#[test]
fn the_adapter_handshake_pipelined_and_byte_by_byte() {
    let s = tc3();
    let input = unhex(&format!("{V1} {V2} {V3}"));
    let whole = feed(&s, &input);
    assert_eq!(whole.len(), 3);
    assert_eq!(hex(&whole[0]), hex(&unhex(V1_REPLY)));
    assert_eq!(sha256(&whole[1]), "fe1a59b37eb54f06f817fba75747161e0e39b1f0233fe55825b7443a3ef9b035");
    assert_eq!(hex(&whole[2]), hex(&unhex(V3_REPLY)));
    let mut conn = Conn::new(2);
    let mut split = Vec::new();
    for b in &input {
        let out = s.feed(&mut conn, &[*b], &Events::disabled());
        assert!(!out.close);
        split.extend(out.replies);
    }
    assert_eq!(whole, split);
}

#[test]
fn unframeable_input_closes_the_connection() {
    let s = tc3();
    for input in [
        V1.replacen("00 00 2c", "01 00 2c", 1), // an AMS/TCP router command
        "00 00 1f 00 00 00".to_string(),        // shorter than an AMS header
        "00 00 21 00 10 00".to_string(),        // 32 + 1 MiB + 1
    ] {
        let out = s.feed(&mut Conn::new(1), &unhex(&input), &Events::disabled());
        assert!(out.close && out.replies.is_empty(), "{input}");
    }
    // Replies to the frames before the bad one still go out.
    let out = s.feed(&mut Conn::new(1), &unhex(&format!("{V1} 01 00 00 00 00 00")), &Events::disabled());
    assert!(out.close);
    assert_eq!(out.replies.iter().map(|r| hex(r)).collect::<Vec<_>>(), vec![hex(&unhex(V1_REPLY))]);
}

#[test]
fn ams_header_checks() {
    let s = tc3();
    // The AMS length (11) disagrees with the AMS/TCP length (32 + 12): error 0xE, the stream stays open.
    assert_eq!(
        one(&s, &V1.replace("04 00 0c 00", "04 00 0b 00")),
        hex(&unhex("00 00 20 00 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 0a 01 01 53 03 02 00 05 00 00 00 00 00
                    0e 00 00 00 01 00 00 00"))
    );
    // A response (state flag 0x0001) and a device notification sent to the PLC get no reply.
    assert!(exchange(&s, &V1.replace("02 00 04 00 0c", "02 00 05 00 0c")).is_empty());
    assert!(exchange(&s, &V1.replace("02 00 04 00 0c", "08 00 04 00 0c")).is_empty());
    // Command id 10 does not exist: 0x701 in the header, the id echoed.
    assert_eq!(
        one(&s, &V1.replace("02 00 04 00 0c", "0a 00 04 00 0c")),
        hex(&unhex("00 00 20 00 00 00 c0 a8 64 01 01 01 89 80 c0 a8 64 0a 01 01 53 03 0a 00 05 00 00 00 00 00
                    01 07 00 00 01 00 00 00"))
    );
}

/// A request to `target` (NetId and port, hex) as SFC builds it: state flags 0x0004, error 0.
fn request(target: &str, cmd: u16, invoke: u32, data: &[u8]) -> Vec<u8> {
    let mut out = vec![0, 0];
    out.extend_from_slice(&(32 + data.len() as u32).to_le_bytes());
    out.extend(unhex(target));
    out.extend(unhex("c0 a8 64 01 01 01 89 80"));
    out.extend_from_slice(&cmd.to_le_bytes());
    out.extend_from_slice(&[4, 0]);
    out.extend_from_slice(&(data.len() as u32).to_le_bytes());
    out.extend_from_slice(&[0; 4]);
    out.extend_from_slice(&invoke.to_le_bytes());
    out.extend_from_slice(data);
    out
}

fn words(values: &[u32]) -> Vec<u8> {
    values.iter().flat_map(|v| v.to_le_bytes()).collect()
}

/// The ADS data of the one reply to `frame`, after checking what every reply has: AMS error 0, state
/// flags 0x0005 and lengths that agree.
fn data_of(server: &Server, frame: &[u8]) -> String {
    let reply = feed(server, frame).remove(0);
    let n = u32::from_le_bytes([reply[26], reply[27], reply[28], reply[29]]) as usize;
    assert_eq!(hex(&reply[24..26]), "05 00");
    assert_eq!(hex(&reply[30..34]), "00 00 00 00");
    assert_eq!(reply.len(), 38 + n);
    hex(&reply[38..])
}

const PLC: &str = "c0 a8 64 0a 01 01 53 03";

#[test]
fn short_and_refused_requests() {
    let s = tc3();
    let refused = |cmd: u16, data: &[u8]| data_of(&s, &request(PLC, cmd, 1, data));
    // Data too short for the command: 0x705 in the command's reply layout.
    assert_eq!(refused(2, &[]), "05 07 00 00 00 00 00 00");
    assert_eq!(refused(2, &words(&[0xF00F, 0])), "05 07 00 00 00 00 00 00");
    assert_eq!(refused(9, &words(&[0xF080, 1, 16, 12])), "05 07 00 00 00 00 00 00");
    // Sum reads: no items, a write length that is not 12 per item, a read length too short for the reply.
    assert_eq!(refused(9, &words(&[0xF080, 0, 0, 0])), "0b 07 00 00 00 00 00 00");
    assert_eq!(refused(9, &words(&[0xF080, 1, 6, 8, 0x4040, 0x1000])), "05 07 00 00 00 00 00 00");
    assert_eq!(refused(9, &words(&[0xF080, 1, 4, 12, 0x4040, 0x1000, 1])), "05 07 00 00 00 00 00 00");
    // A sum read inside a sum read is an invalid group.
    assert_eq!(refused(9, &words(&[0xF080, 1, 4, 12, 0xF080, 0, 0])), "00 00 00 00 04 00 00 00 02 07 00 00");
    // Read-only: a write to a served group is not permitted, to any other group the group is invalid.
    assert_eq!(refused(3, &[words(&[0x4040, 0x1000, 1]), vec![1]].concat()), "04 07 00 00");
    assert_eq!(refused(3, &[words(&[0x1234, 0, 1]), vec![1]].concat()), "02 07 00 00");
    assert_eq!(refused(3, &words(&[0x4040, 0x1000, 1])), "05 07 00 00");
    // No sum writes, no WriteControl, no notifications.
    assert_eq!(refused(9, &words(&[0xF081, 1, 4, 13, 0x4040, 0x1000, 1, 0])), "02 07 00 00 00 00 00 00");
    assert_eq!(refused(5, &[2, 0, 0, 0, 0, 0, 0, 0]), "01 07 00 00");
    assert_eq!(refused(6, &[words(&[0x4040, 0x1000, 1, 3, 0, 1000]), vec![0; 16]].concat()), "01 07 00 00 00 00 00 00");
    assert_eq!(refused(7, &words(&[1])), "14 07 00 00");
}

#[test]
fn the_other_upload_groups_and_device_data() {
    let s = tc3();
    let read = |ig: u32, io: u32, len: u32| data_of(&s, &request(PLC, 2, 1, &words(&[ig, io, len])));
    // 0xF00C: nSymbols, nSymSize. 0xF008: symbol version 1. 0xF00E: no data types.
    assert_eq!(read(0xF00C, 0, 8), "00 00 00 00 08 00 00 00 71 00 00 00 e4 22 00 00");
    assert_eq!(read(0xF008, 0, 1), "00 00 00 00 01 00 00 00 01");
    assert_eq!(read(0xF00E, 0, 64), "00 00 00 00 00 00 00 00");
    // 0xF100: ADS state RUN at offset 0.
    assert_eq!(read(0xF100, 0, 2), "00 00 00 00 02 00 00 00 05 00");
    assert_eq!(read(0xF100, 4, 2), "03 07 00 00 00 00 00 00");
    // %M as words and as bits: %MW0 = 16#00C3, so %MX0.0, %MX0.1 and %MX0.6 are set.
    assert_eq!(read(0x4021, 0, 8), "00 00 00 00 08 00 00 00 01 01 00 00 00 00 01 01");
    // The system service answers identity, state and 0xF100 only.
    let system = "c0 a8 64 0a 01 01 10 27";
    let name = hex(b"TwinCAT System\0\0");
    assert_eq!(data_of(&s, &request(system, 1, 1, &[])), format!("00 00 00 00 03 01 b8 0f {name}"));
    assert_eq!(data_of(&s, &request(system, 2, 1, &words(&[0xF100, 0, 2]))), "00 00 00 00 02 00 00 00 05 00");
    assert_eq!(data_of(&s, &request(system, 2, 1, &words(&[0x4040, 0x1000, 1]))), "01 07 00 00 00 00 00 00");
}

#[test]
fn the_other_runtimes_and_profiles() {
    // tc3-ipc PLC 2 on port 852: 7 symbols.
    let s = tc3();
    let plc2 = "c0 a8 64 0a 01 01 54 03";
    assert_eq!(data_of(&s, &request(plc2, 2, 1, &words(&[0xF00C, 0, 4]))), "00 00 00 00 04 00 00 00 07 00 00 00");
    assert_eq!(data_of(&s, &request(plc2, 2, 1, &words(&[0x4040, 0x1008, 9]))),
               format!("00 00 00 00 09 00 00 00 {} 00", hex(b"RECIPE-2")));

    // tc3-cx8190: its own NetId, the same table size, 4-byte pointers.
    let cx = Server::new("tc3-cx8190").unwrap();
    let cx8190 = "05 50 c9 e8 01 01 53 03";
    let info = data_of(&cx, &request(cx8190, 2, 1, &words(&[0xF00F, 0, 48])));
    assert_eq!(&info[..47], "00 00 00 00 30 00 00 00 71 00 00 00 e4 22 00 00");
    // GVL_Edge.pInt: 4 bytes at 0x2864.
    assert_eq!(data_of(&cx, &request(cx8190, 2, 1, &words(&[0x4040, 0x2864, 4]))),
               "00 00 00 00 04 00 00 00 78 56 34 12");
    assert_eq!(data_of(&cx, &request(cx8190, 2, 1, &words(&[0x4040, 0x400E, 2]))), "00 00 00 00 02 00 00 00 20 00");
    // tc3-ipc's NetId is not this PLC's: router error 7.
    assert_eq!(feed(&cx, &request(PLC, 2, 1, &words(&[0xF00F, 0, 48])))[0][30], 7);

    // tc2-pc: port 801, 24 bytes of upload info, 88 entries without GUID, pack 1.
    let tc2 = Server::new("tc2-pc").unwrap();
    let pc = "c0 a8 64 14 01 01 21 03";
    let info = data_of(&tc2, &request(pc, 2, 1, &words(&[0xF00F, 0, 48])));
    assert_eq!(unhex(&info).len(), 8 + 24);
    assert_eq!(&info[..35], "00 00 00 00 18 00 00 00 58 00 00 00");
    let size = u32::from_le_bytes(unhex(&info)[12..16].try_into().unwrap());
    let table = data_of(&tc2, &request(pc, 2, 1, &words(&[0xF00B, 0, size])));
    // `.bBoolTrue`: 56 bytes, flags 0, no GUID, no padding.
    let first = format!(
        "38 00 00 00 40 40 00 00 00 10 00 00 01 00 00 00 21 00 00 00 00 00 00 00 0a 00 04 00 09 00 {} 00 {} 00 {} 00",
        hex(b".bBoolTrue"), hex(b"BOOL"), hex(b"bool_true")
    );
    assert_eq!(&table[24..24 + first.len()], first);
    assert_eq!(data_of(&tc2, &request(pc, 2, 1, &words(&[0x4040, 0x1005, 2]))), "00 00 00 00 02 00 00 00 c7 cf");
    assert_eq!(data_of(&tc2, &request(pc, 2, 1, &words(&[0x4040, 0x10CD, 9]))),
               "00 00 00 00 09 00 00 00 01 aa 05 00 00 70 40 4d 31");
}

#[test]
fn a_scan_writes_the_dynamic_block() {
    let s = tc3();
    let mut bank = Bank::new(&BTreeMap::new()).unwrap();
    let (k, t) = (25, 0.25);
    s.image().apply(&Scan { k, t, cycle_ms: 10, wall_ms: 1_718_454_896_250, v: bank.values(k, t) });
    // nScan, fT, fSine (100 at a quarter period), fSquare, nSineInt, bBlink1Hz, GVL_IO.bSensor,
    // GVL_IO.nEncoder and the task's CycleTime and CycleCount, in one sum read.
    let items = [(0x4040, 0x2000, 8), (0x4040, 0x2008, 8), (0x4040, 0x2010, 4), (0x4040, 0x2030, 4),
                 (0x4040, 0x2048, 2), (0x4040, 0x204A, 1), (0xF021, 0, 1), (0xF020, 4, 4), (0x4040, 0x42C4, 4),
                 (0x4040, 0x42CC, 4)];
    let mut data = words(&[0xF080, items.len() as u32, 4 * items.len() as u32 + 40, 12 * items.len() as u32]);
    for (ig, io, len) in items {
        data.extend(words(&[ig, io, len]));
    }
    let want = format!(
        "00 00 00 00 50 00 00 00 {}19 00 00 00 00 00 00 00 00 00 00 00 00 00 d0 3f 00 00 c8 42 00 00 c8 42 10 27 01 01 \
         64 00 00 00 a0 86 01 00 19 00 00 00",
        "00 ".repeat(40)
    );
    assert_eq!(data_of(&s, &request(PLC, 9, 3, &data)), want);
}
