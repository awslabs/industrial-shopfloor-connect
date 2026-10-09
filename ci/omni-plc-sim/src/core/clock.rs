// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! Calendar arithmetic for the simulated PLC clocks (no chrono dependency).
//!
//! The PLC wall clock is `clock_base + k · cycle_ms`, in Unix milliseconds, UTC. Protocols turn it
//! into their own clock registers with [`civil`].

use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{bail, Context};

/// A UTC calendar time.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Civil {
    pub year: i32,
    pub month: u32,
    pub day: u32,
    pub hour: u32,
    pub minute: u32,
    pub second: u32,
    pub millis: u32,
    /// 0 = Sunday … 6 = Saturday.
    pub weekday: u32,
}

/// Days since 1970-01-01 of a proleptic Gregorian date (Howard Hinnant's algorithm).
pub fn days_from_civil(year: i32, month: u32, day: u32) -> i64 {
    let y = if month <= 2 { year as i64 - 1 } else { year as i64 };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let m = month as i64;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + day as i64 - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

/// The date of a day number since 1970-01-01.
pub fn civil_from_days(z: i64) -> (i32, u32, u32) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    ((if m <= 2 { y + 1 } else { y }) as i32, m, d)
}

/// The UTC calendar time of Unix milliseconds.
pub fn civil(unix_ms: i64) -> Civil {
    let days = unix_ms.div_euclid(86_400_000);
    let ms_of_day = unix_ms.rem_euclid(86_400_000) as u32;
    let (year, month, day) = civil_from_days(days);
    Civil {
        year,
        month,
        day,
        hour: ms_of_day / 3_600_000,
        minute: ms_of_day / 60_000 % 60,
        second: ms_of_day / 1000 % 60,
        millis: ms_of_day % 1000,
        weekday: (days + 4).rem_euclid(7) as u32, // 1970-01-01 was a Thursday
    }
}

/// Unix milliseconds of a UTC calendar time.
pub fn unix_ms(year: i32, month: u32, day: u32, hour: u32, minute: u32, second: u32, millis: u32) -> i64 {
    days_from_civil(year, month, day) * 86_400_000
        + hour as i64 * 3_600_000
        + minute as i64 * 60_000
        + second as i64 * 1000
        + millis as i64
}

/// The host's UTC wall clock, in Unix milliseconds.
pub fn now_ms() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
}

/// Parses `YYYY-MM-DDTHH:MM:SS[.fff]Z` (or `+00:00`): UTC only, which is all a test clock needs.
pub fn parse_rfc3339_utc(s: &str) -> anyhow::Result<i64> {
    let bad = || format!("clock base {s:?} is not YYYY-MM-DDTHH:MM:SS[.fff]Z");
    let b = s.as_bytes();
    if b.len() < 20 || b[4] != b'-' || b[7] != b'-' || !(b[10] == b'T' || b[10] == b't') || b[13] != b':' || b[16] != b':' {
        bail!(bad());
    }
    let num = |r: std::ops::Range<usize>| -> anyhow::Result<u32> {
        s.get(r).and_then(|t| t.parse::<u32>().ok()).with_context(bad)
    };
    let (year, month, day) = (num(0..4)? as i32, num(5..7)?, num(8..10)?);
    let (hour, minute, second) = (num(11..13)?, num(14..16)?, num(17..19)?);
    let mut rest = &s[19..];
    let mut millis = 0u32;
    if let Some(frac) = rest.strip_prefix('.') {
        let digits: String = frac.chars().take_while(|c| c.is_ascii_digit()).collect();
        if digits.is_empty() {
            bail!(bad());
        }
        let ms3: String = format!("{digits:0<3}").chars().take(3).collect();
        millis = ms3.parse().with_context(bad)?;
        rest = &frac[digits.len()..];
    }
    if !(rest == "Z" || rest == "z" || rest == "+00:00") {
        bail!("clock base {s:?} must be UTC (Z)");
    }
    if !(1..=12).contains(&month) || !(1..=31).contains(&day) || hour > 23 || minute > 59 || second > 59 {
        bail!(bad());
    }
    Ok(unix_ms(year, month, day, hour, minute, second, millis))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips() {
        assert_eq!(days_from_civil(1970, 1, 1), 0);
        assert_eq!(days_from_civil(2024, 2, 29), 19782);
        assert_eq!(civil_from_days(19782), (2024, 2, 29));
        let ms = unix_ms(2024, 6, 15, 12, 34, 56, 789);
        assert_eq!(ms, 1_718_454_896_789);
        let c = civil(ms);
        assert_eq!((c.year, c.month, c.day, c.hour, c.minute, c.second, c.millis), (2024, 6, 15, 12, 34, 56, 789));
        assert_eq!(c.weekday, 6); // a Saturday
        assert_eq!(civil(-1).year, 1969);
    }

    #[test]
    fn parses_utc_only() {
        assert_eq!(parse_rfc3339_utc("2024-06-15T12:34:56Z").unwrap(), 1_718_454_896_000);
        assert_eq!(parse_rfc3339_utc("2024-06-15T12:34:56.789Z").unwrap(), 1_718_454_896_789);
        assert_eq!(parse_rfc3339_utc("2024-06-15T12:34:56.7+00:00").unwrap(), 1_718_454_896_700);
        assert!(parse_rfc3339_utc("2024-06-15T12:34:56+02:00").is_err());
        assert!(parse_rfc3339_utc("2024-13-15T12:34:56Z").is_err());
        assert!(parse_rfc3339_utc("yesterday").is_err());
    }
}
