// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! Bounds-checked byte reading and the hex helpers the golden tests use.

/// A cursor over a request. Every read returns `None` past the end, so a short frame becomes an
/// error reply or a closed connection, never a panic.
#[derive(Debug, Clone)]
pub struct Reader<'a> {
    buf: &'a [u8],
    pos: usize,
}

impl<'a> Reader<'a> {
    pub fn new(buf: &'a [u8]) -> Reader<'a> {
        Reader { buf, pos: 0 }
    }

    pub fn pos(&self) -> usize {
        self.pos
    }

    pub fn remaining(&self) -> usize {
        self.buf.len() - self.pos
    }

    pub fn rest(&self) -> &'a [u8] {
        &self.buf[self.pos..]
    }

    pub fn bytes(&mut self, n: usize) -> Option<&'a [u8]> {
        let end = self.pos.checked_add(n)?;
        let out = self.buf.get(self.pos..end)?;
        self.pos = end;
        Some(out)
    }

    pub fn skip(&mut self, n: usize) -> Option<()> {
        self.bytes(n).map(|_| ())
    }

    pub fn u8(&mut self) -> Option<u8> {
        self.bytes(1).map(|b| b[0])
    }

    pub fn be_u16(&mut self) -> Option<u16> {
        self.bytes(2).map(|b| u16::from_be_bytes([b[0], b[1]]))
    }

    pub fn le_u16(&mut self) -> Option<u16> {
        self.bytes(2).map(|b| u16::from_le_bytes([b[0], b[1]]))
    }

    pub fn be_u32(&mut self) -> Option<u32> {
        self.bytes(4).map(|b| u32::from_be_bytes([b[0], b[1], b[2], b[3]]))
    }

    pub fn le_u32(&mut self) -> Option<u32> {
        self.bytes(4).map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
    }
}

/// Lower-case hex with a space between bytes, as the events log and test failures print frames.
pub fn hex(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 3);
    for (i, b) in bytes.iter().enumerate() {
        if i > 0 {
            out.push(' ');
        }
        out.push_str(&format!("{b:02x}"));
    }
    out
}

/// Parses hex, ignoring whitespace, `|` separators and newlines, the way the specs write frames.
/// Panics on bad input: it is for test vectors only.
pub fn unhex(s: &str) -> Vec<u8> {
    let digits: Vec<u8> = s.bytes().filter(|c| c.is_ascii_hexdigit()).collect();
    assert!(digits.len() % 2 == 0, "odd number of hex digits in {s:?}");
    digits
        .chunks(2)
        .map(|p| u8::from_str_radix(std::str::from_utf8(p).unwrap(), 16).unwrap())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reader_stops_at_the_end() {
        let mut r = Reader::new(&[1, 2, 3]);
        assert_eq!(r.be_u16(), Some(0x0102));
        assert_eq!(r.le_u16(), None);
        assert_eq!(r.u8(), Some(3));
        assert_eq!(r.u8(), None);
        assert_eq!(r.remaining(), 0);
    }

    #[test]
    fn hex_round_trip() {
        assert_eq!(unhex("03 00 | 00 16\n11"), vec![3, 0, 0, 0x16, 0x11]);
        assert_eq!(hex(&[0xD0, 0, 0xFF]), "d0 00 ff");
    }
}
