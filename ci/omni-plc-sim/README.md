# omni-plc-sim

`omni-plc-sim` is a simulated PLC for the SFC end-to-end suite (`ci/e2e`). It serves the protocols of
SFC's PLC adapters, so a case can run the real adapter against something that answers like a PLC:

| Protocol | Adapter | Profiles (default first) |
|---|---|---|
| `s7` | `adapters/s7` (Apache PLC4X 0.9.1) | `s7-1500`, `s7-1200`, `s7-400`, `s7-300` |
| `ads` | `adapters/ads` | `tc3-ipc`, `tc3-cx8190`, `tc2-pc` |
| `pccc` | `adapters/pccc` | `micrologix1400`, `micrologix1100`, `slc505`, `plc5` |
| `slmp` | `adapters/slmp` | `iq-r`, `q`, `l`, `iq-f` |
| `modbus` | `adapters/modbus-tcp` | `generic`, `s7-1200`, `modicon-m340` |

## Quick start

```
omni-plc-sim s7 ads
```

This starts a Siemens S7-1500 and a Beckhoff TwinCAT 3 PLC, each with its full default map and live
signals. No configuration is needed: every default is built into the binary.

- **Ports:** each protocol listens on all interfaces, on the SFC adapter's default port, so an SFC adapter
  with default settings reaches it.

  | Protocol | s7 | ads | pccc | slmp | modbus |
  |---|---|---|---|---|---|
  | Port | 102 | 48898 | 44818 | 40000 | 502 |

- **SLMP is the exception:** it listens on 40000, not on SFC's default 50000, which is where the e2e
  suite's IPC services start. An SFC SLMP controller therefore sets `"Port": 40000`.
- **Linux:** ports below 1024 need root. Give another port instead, for example
  `omni-plc-sim --serve s7=10102 ads`.
- **ADS:** the target AMS NetId and every symbol name are printed by `omni-plc-sim --print-map ads`.
- **Other PLC types:** `omni-plc-sim --list-profiles` prints every profile with all its details: the PLC
  it simulates, its identity, limits, areas and ports.

## What a simulated PLC holds

Every protocol has the same three kinds of tags, in its own address space and encoding:

- **Static tags:** one exact value per data type, for example `int` −12345, `real` 12345.5,
  `lreal` −98765.4375 and `string` "SFC-SIM". All of them are exactly representable, so a case can
  compare them for equality.
- **Dynamic tags:** signals recomputed every scan (10 ms by default) from the scan time `t`, with
  `x = 2π·f·t + φ` and `p = frac(f·t + φ/2π)`:

  | Signal | Value | Default f |
  |---|---|---|
  | sine, cosine | c + A·sin x, c + A·cos x | 1 Hz |
  | tangent, cotangent | c + A·clamp(tan x, ±L), c + A·clamp(cot x, ±L) | 0.25 Hz |
  | exp | c + A·e^(3(p−1)) | 0.5 Hz |
  | quadratic | c + A·(2p−1)² | 0.5 Hz |
  | sawtooth, triangle | c + A·(2p−1), c + A·(1 − 4·\|p − ½\|) | 2 Hz |
  | square | c ± A | 1 Hz |
  | damped | c + A·e^(−4p)·sin(2π·5p) | 0.5 Hz |
  | noise, randomwalk | seeded and deterministic per scan | — |
  | blink_1hz, blink_5hz | p < ½ | 1 Hz, 5 Hz |

  The defaults are A = 100, c = 0, φ = 0, L = 10. Every value stays finite.
- **PLC flavour:** the clocks, timers, counters and system areas a real controller has. Examples are the
  S7 identification records, the TwinCAT system symbols, the SLC `S:4` free-running clock, MELSEC
  `SM400`/`SM412` and `SD210`, and a Modbus RTC block.

A request always reads one consistent scan: the scan counter, `t` and every signal come from the same
scan. To see a protocol's full map, with the addresses in the syntax the SFC adapter accepts, run:

```
omni-plc-sim --print-map <protocol> [--profile <protocol>=<name>]
```

## Fine-grained options

Every option is optional. The quick start above is the same as giving none of them.

```
omni-plc-sim --serve <proto>[=<port>|=<ip>|=<host:port>] [--serve ...] [--profile <proto>=<name>]
             [--config sim.toml] [--cycle-ms 10] [--clock-base 2024-06-15T12:34:56Z]
             [--events events.jsonl]
```

- **`--serve`** chooses the address: `s7=10102` keeps all interfaces, `s7=127.0.0.1` binds only loopback
  at the default port, and `s7=127.0.0.1:10102` binds only loopback at another port. Bare names and
  `--serve` can be mixed.
- **`--profile`** selects another PLC type, for example `--profile s7=s7-300`. `--list-profiles` shows them
  all.
- **Start-up:** the first scan is applied before any port is bound. Then it prints
  `omni-plc-sim <proto> listening on <addr> (profile <name>)` for each listener, followed by
  `omni-plc-sim ready`. SIGTERM or Ctrl+C ends it with exit code 0.
- **`--events`** writes one JSON line per connection event and per request:
  `{"ts", "proto", "conn", "op", "detail", "status"}`, with the details in wire units.
- **`--clock-base`** fixes the PLC clock. By default the clock starts at the host's UTC time.
- **`sim.toml`** overrides the scan cycle, the clock base and the signal parameters. Unknown keys are
  rejected:

  ```toml
  cycle_ms = 10
  [signals.sine]
  amplitude = 50.0
  frequency_hz = 5.0
  ```

## In the e2e suite

A case declares the simulator as a counterpart of kind `plc-sim`:

```json
"services": [{"name": "plc", "kind": "plc-sim", "args": {"protocol": "s7", "profile": "s7-1500"}}]
```

- The harness exports the simulator's port as `SFC_E2E_PLC_PORT`.
- It keeps `services/plc/events.jsonl` as evidence. A case can read that file through a `jsonl` sink.
- Every protocol has a pilot case: `ADP-<PROTO>-PILOT` in `ci/e2e/cases/adapters/<proto>.json`.

## How it is built

- **In CodeBuild, the full build:** the project `sfc-integration-test-plc-sim` runs the `Dockerfile` here.
  - It uses `rust:1.98-alpine`.
  - It runs `cargo build --release --locked` and then `cargo test`, which includes the golden frames of
    every protocol.
  - It produces a static musl binary and stores it in `s3://<ArtifactsBucket>/plc-sim/<hash>/`.
  - `ci/start-build.sh` hashes this directory. It starts that build only when no binary exists for the
    hash, in parallel with the image build. The test build downloads exactly that binary.
- **Locally, for development only:**
  ```
  cargo test --offline
  cargo test --offline --no-default-features --features s7
  ```
  - The second form builds one protocol on its own.
  - `Cargo.lock` is committed, and the cloud build uses it with `--locked`.

## Design

- **Server code:** every protocol is hand-written on `tokio`, with no protocol crates.
  - The crates named in `ci/protocol-sim-proposal.md` are clients, or they would hide the bytes that
    must be exact.
  - SFC's clients frame strictly and never resynchronise.
- **Module layout:** each module in `src/protocols` has a pure request handler, and the golden tests in
  `tests/` call it directly.
- **Memory images:** the images sit behind a `RwLock`, which the scan engine writes once per scan. The
  proposal had an mpsc actor in this place.
- **Scope:** everything SFC's adapters send, plus the identity and status reads of a real controller.
  Writes, notifications and fault injection are not simulated.
