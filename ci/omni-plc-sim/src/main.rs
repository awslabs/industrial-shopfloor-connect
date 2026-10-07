// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! The `omni-plc-sim` binary: serves one or more PLC protocols, each on its own TCP address.

use std::net::{IpAddr, SocketAddr};
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{bail, Context};
use omni_plc_sim::core::config::SimConfig;
use omni_plc_sim::core::engine::{Engine, ScanTarget, Settings};
use omni_plc_sim::core::events::Events;
use omni_plc_sim::protocols::{self, Server};
use serde_json::Value;

const USAGE: &str = "\
usage: omni-plc-sim <proto> [<proto> ...]
       omni-plc-sim --serve <proto>[=<port>|=<ip>|=<host:port>] [--serve ...] [--profile <proto>=<name>]
                    [--config sim.toml] [--cycle-ms 10] [--clock-base <YYYY-MM-DDTHH:MM:SSZ>]
                    [--events events.jsonl]
       omni-plc-sim --print-map <proto> [--profile <proto>=<name>]
       omni-plc-sim --list-profiles
       omni-plc-sim --version

<proto> is s7, ads, pccc, slmp or modbus. Without an address a protocol listens on all interfaces, like
a real PLC, at the SFC adapter's default port: s7 102, ads 48898, pccc 44818, modbus 502; slmp listens on
40000, because SFC's own SLMP default 50000 is where the e2e suite's IPC services start.
On Linux, ports below 1024 need root: use e.g. `--serve s7=10102`.

After binding it prints `omni-plc-sim <proto> listening on <addr> (profile <name>)` for each
listener, then `omni-plc-sim ready`. SIGTERM or SIGINT (Ctrl+C) ends it with exit code 0.";

/// All interfaces, like a real PLC. It is also the only address macOS lets a non-root process bind below
/// port 1024 on.
const DEFAULT_HOST: &str = "0.0.0.0";

#[derive(Debug, Default)]
struct Args {
    serve: Vec<(String, String)>,
    profiles: Vec<(String, String)>,
    config: Option<PathBuf>,
    cycle_ms: Option<u64>,
    clock_base: Option<String>,
    events: Option<PathBuf>,
    print_map: Option<String>,
    list_profiles: bool,
    version: bool,
    help: bool,
}

impl Args {
    fn profile(&self, proto: &str) -> Option<&str> {
        self.profiles.iter().rev().find(|(p, _)| p == proto).map(|(_, name)| name.as_str())
    }
}

fn pair(flag: &str, value: &str) -> anyhow::Result<(String, String)> {
    match value.split_once('=') {
        Some((k, v)) if !k.is_empty() && !v.is_empty() => Ok((k.to_string(), v.to_string())),
        _ => bail!("{flag} expects <proto>=<value>, got {value:?}"),
    }
}

/// `s7`, `s7=10102`, `s7=127.0.0.1` or `s7=127.0.0.1:102` as (protocol, listen address). A missing host is
/// all interfaces and a missing port the protocol's default.
fn serve_spec(value: &str) -> anyhow::Result<(String, String)> {
    let (proto, addr) = match value.split_once('=') {
        Some((p, a)) => (p, Some(a)),
        None => (value, None),
    };
    if proto.is_empty() || addr == Some("") {
        bail!("--serve expects <proto>[=<port>|=<ip>|=<host:port>], got {value:?}");
    }
    let default_port = || {
        protocols::default_port(proto)
            .with_context(|| format!("unknown protocol {proto:?}; known: s7, ads, pccc, slmp, modbus"))
    };
    let addr = match addr {
        Some(a) if a.parse::<IpAddr>().is_ok() => SocketAddr::new(a.parse()?, default_port()?).to_string(),
        Some(a) if a.contains(':') => a.to_string(),
        Some(port) => {
            let port: u16 = port.parse().with_context(|| format!("--serve {value}: {port:?} is not a port"))?;
            format!("{DEFAULT_HOST}:{port}")
        }
        None => format!("{DEFAULT_HOST}:{}", default_port()?),
    };
    Ok((proto.to_string(), addr))
}

fn parse_args(mut argv: impl Iterator<Item = String>) -> anyhow::Result<Args> {
    let mut a = Args::default();
    while let Some(flag) = argv.next() {
        let mut value = |name: &str| argv.next().with_context(|| format!("{name} needs a value"));
        match flag.as_str() {
            "--serve" => a.serve.push(serve_spec(&value("--serve")?)?),
            "--profile" => a.profiles.push(pair("--profile", &value("--profile")?)?),
            "--config" => a.config = Some(PathBuf::from(value("--config")?)),
            "--cycle-ms" => a.cycle_ms = Some(value("--cycle-ms")?.parse().context("--cycle-ms must be a number")?),
            "--clock-base" => a.clock_base = Some(value("--clock-base")?),
            "--events" => a.events = Some(PathBuf::from(value("--events")?)),
            "--print-map" => a.print_map = Some(value("--print-map")?),
            "--list-profiles" => a.list_profiles = true,
            "--version" | "-V" => a.version = true,
            "--help" | "-h" => a.help = true,
            other if other.starts_with('-') => bail!("unknown argument {other:?}\n{USAGE}"),
            // A bare protocol name: that protocol at its default address.
            proto => a.serve.push(serve_spec(proto)?),
        }
    }
    Ok(a)
}

fn main() -> anyhow::Result<()> {
    let args = parse_args(std::env::args().skip(1))?;
    if args.help {
        println!("{USAGE}");
        return Ok(());
    }
    if args.version {
        println!("omni-plc-sim {} ({})", env!("CARGO_PKG_VERSION"), protocols::compiled().join(", "));
        return Ok(());
    }
    if args.list_profiles {
        print!("{}", list_profiles()?);
        return Ok(());
    }
    let cfg = match &args.config {
        Some(path) => SimConfig::load(path)?,
        None => SimConfig::default(),
    };
    let settings = Settings::resolve(&cfg, args.cycle_ms, args.clock_base.as_deref())?;
    if let Some(proto) = &args.print_map {
        let server = Server::new(proto, args.profile(proto))?;
        println!("{}", serde_json::to_string_pretty(&server.print_map())?);
        return Ok(());
    }
    if args.serve.is_empty() {
        bail!("nothing to serve: give --serve <proto>=<host:port>\n{USAGE}");
    }
    let runtime = tokio::runtime::Builder::new_multi_thread().enable_all().build()?;
    runtime.block_on(run(args, cfg, settings))?;
    // The runtime's tasks (accept loops, connections, the scan loop) end with the process.
    std::process::exit(0);
}

/// Every profile with all its details, each protocol's default first: a `<proto> <profile>: <device>` line,
/// then the profile's map without its tag lists, which `--print-map` prints.
fn list_profiles() -> anyhow::Result<String> {
    let mut out = String::new();
    for (proto, default, profiles) in protocols::profiles() {
        for profile in std::iter::once(default).chain(profiles.iter().copied().filter(|p| *p != default)) {
            let mut map = Server::new(proto, Some(profile))?.print_map();
            strip_tags(&mut map);
            let marker = if profile == default { " (default)" } else { "" };
            out.push_str(&format!("{proto} {profile}{marker}: {}\n", map["device"].as_str().unwrap_or_default()));
            if let Value::Object(fields) = &map {
                for (key, value) in fields.iter().filter(|(k, _)| !["protocol", "profile", "device"].contains(&k.as_str())) {
                    detail(&mut out, 1, key, value);
                }
            }
            out.push('\n');
        }
    }
    Ok(out)
}

fn strip_tags(value: &mut Value) {
    match value {
        Value::Object(fields) => {
            fields.remove("tags");
            fields.values_mut().for_each(strip_tags);
        }
        Value::Array(items) => items.iter_mut().for_each(strip_tags),
        _ => {}
    }
}

/// `key: value`, indented by `depth`: scalars, and short lists and objects of scalars, on one line; anything
/// else one entry per line below the key.
fn detail(out: &mut String, depth: usize, key: &str, value: &Value) {
    let pad = "  ".repeat(depth);
    let nested = matches!(value, Value::Object(_) | Value::Array(_));
    match inline(value) {
        Some(text) if !nested || text.len() <= 96 => out.push_str(&format!("{pad}{key}: {text}\n")),
        _ => {
            out.push_str(&format!("{pad}{key}:\n"));
            match value {
                Value::Object(fields) => fields.iter().for_each(|(k, v)| detail(out, depth + 1, k, v)),
                Value::Array(items) => {
                    for item in items {
                        match (inline(item), item) {
                            (Some(text), _) => out.push_str(&format!("{pad}  - {text}\n")),
                            (None, Value::Object(fields)) => {
                                out.push_str(&format!("{pad}  -\n"));
                                fields.iter().for_each(|(k, v)| detail(out, depth + 2, k, v));
                            }
                            (None, other) => out.push_str(&format!("{pad}  - {other}\n")),
                        }
                    }
                }
                _ => {}
            }
        }
    }
}

/// A scalar as text, or a list or object of scalars on one line; None for anything deeper. Strings lose their
/// trailing padding, such as the space of a 20-character MLFB; `--print-map` keeps them exact.
fn inline(value: &Value) -> Option<String> {
    let scalar = |v: &Value| match v {
        Value::String(s) => Some(s.trim_end().to_string()),
        Value::Object(_) | Value::Array(_) => None,
        other => Some(other.to_string()),
    };
    match value {
        Value::Object(fields) => {
            fields.iter().map(|(k, v)| scalar(v).map(|t| format!("{k}={t}"))).collect::<Option<Vec<_>>>().map(|p| p.join(", "))
        }
        Value::Array(items) => items.iter().map(scalar).collect::<Option<Vec<_>>>().map(|p| p.join(", ")),
        other => scalar(other),
    }
}

async fn run(args: Args, cfg: SimConfig, settings: Settings) -> anyhow::Result<()> {
    let events = match &args.events {
        Some(path) => Events::to_file(path)?,
        None => Events::disabled(),
    };
    let mut servers = Vec::new();
    for (proto, addr) in &args.serve {
        servers.push((Server::new(proto, args.profile(proto))?, addr.clone()));
    }
    let targets: Vec<Arc<dyn ScanTarget>> = servers.iter().map(|(s, _)| s.image()).collect();
    let mut engine = Engine::new(&cfg, settings, targets)?;
    // Scan 0 before the first bind: no client ever reads an empty image.
    engine.start();

    let mut bound = Vec::new();
    for (server, addr) in servers {
        let listener = match tokio::net::TcpListener::bind(&addr).await {
            Ok(listener) => listener,
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => bail!(
                "binding {addr}: {e}. Ports below 1024 need root; give another port, e.g. --serve {}=1{}",
                server.name(), addr.rsplit(':').next().unwrap_or("0")),
            Err(e) => return Err(e).with_context(|| format!("binding {addr}")),
        };
        println!("omni-plc-sim {} listening on {} (profile {})", server.name(), listener.local_addr()?, server.profile());
        bound.push((server, listener));
    }
    println!("omni-plc-sim ready");

    let mut tasks = tokio::task::JoinSet::new();
    for (server, listener) in bound {
        let events = events.clone();
        tasks.spawn(async move { server.serve(listener, events).await });
    }
    tasks.spawn(async move {
        engine.run().await;
        Ok(())
    });

    tokio::select! {
        stopped = shutdown() => stopped,
        finished = tasks.join_next() => match finished {
            Some(Ok(Err(e))) => Err(e),
            Some(Err(e)) => Err(e.into()),
            _ => Ok(()),
        },
    }
}

/// Resolves on SIGINT or SIGTERM; on Windows, on Ctrl+C.
async fn shutdown() -> anyhow::Result<()> {
    #[cfg(unix)]
    {
        let mut sigterm = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
        tokio::select! {
            stopped = tokio::signal::ctrl_c() => stopped?,
            _ = sigterm.recv() => {}
        }
    }
    #[cfg(not(unix))]
    tokio::signal::ctrl_c().await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(list: &[&str]) -> anyhow::Result<Args> {
        parse_args(list.iter().map(|s| s.to_string()))
    }

    #[test]
    fn parses_the_harness_command_line() {
        let a = args(&["--serve", "s7=127.0.0.1:10102", "--profile", "s7=s7-300", "--events", "events.jsonl"]).unwrap();
        assert_eq!(a.serve, vec![("s7".to_string(), "127.0.0.1:10102".to_string())]);
        assert_eq!(a.profile("s7"), Some("s7-300"));
        assert_eq!(a.profile("ads"), None);
        assert_eq!(a.events, Some(PathBuf::from("events.jsonl")));
        assert!(args(&["--serve"]).is_err());
        assert!(args(&["--serve", "s7="]).is_err());
        assert!(args(&["--serve", "s7=port"]).is_err());
        assert!(args(&["--bogus"]).is_err());
    }

    #[test]
    fn defaults_are_built_in() {
        let a = args(&["s7", "ads"]).unwrap();
        assert_eq!(a.serve, vec![("s7".to_string(), "0.0.0.0:102".to_string()),
                                 ("ads".to_string(), "0.0.0.0:48898".to_string())]);
        let a = args(&["--serve", "modbus", "--serve", "slmp=15000", "--serve", "pccc=127.0.0.1:44818"]).unwrap();
        assert_eq!(a.serve, vec![("modbus".to_string(), "0.0.0.0:502".to_string()),
                                 ("slmp".to_string(), "0.0.0.0:15000".to_string()),
                                 ("pccc".to_string(), "127.0.0.1:44818".to_string())]);
        assert_eq!(args(&["--serve", "ads=127.0.0.1"]).unwrap().serve, vec![("ads".to_string(), "127.0.0.1:48898".to_string())]);
        assert_eq!(args(&["--serve", "s7=::1"]).unwrap().serve, vec![("s7".to_string(), "[::1]:102".to_string())]);
        // Not SFC's 50000: that is where the e2e suite's IPC services start.
        assert_eq!(args(&["slmp"]).unwrap().serve, vec![("slmp".to_string(), "0.0.0.0:40000".to_string())]);
        assert!(args(&["nope"]).is_err());
    }

    #[test]
    fn lists_every_profile_with_its_details() {
        assert!(args(&["--list-profiles"]).unwrap().list_profiles);
        let listing = list_profiles().unwrap();
        let headers: Vec<&str> = listing.lines().filter(|l| !l.is_empty() && !l.starts_with(' ')).collect();
        let all = protocols::profiles();
        assert_eq!(headers.len(), all.iter().map(|(_, _, p)| p.len()).sum::<usize>());
        for (proto, default, profiles) in all {
            let mine: Vec<_> = headers.iter().filter(|h| h.starts_with(&format!("{proto} "))).collect();
            assert_eq!(mine.len(), profiles.len());
            assert!(mine[0].starts_with(&format!("{proto} {default} (default): ")));
            // Every profile names the PLC it simulates.
            assert!(mine.iter().all(|h| !h.split_once(": ").unwrap().1.is_empty()));
        }
        assert!(listing.contains("\n  pdu_max: 960\n"));
        assert!(!listing.lines().any(|l| l.trim_start().starts_with("tags:")));
    }
}
