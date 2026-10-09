// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! One module per protocol, each behind its own cargo feature (all on by default), so a module can be
//! built and tested on its own with `--no-default-features --features <name>`.
//!
//! Every module follows the same shape:
//! - `pub const NAME`, `DEFAULT_PROFILE` and `PROFILES`;
//! - `pub struct Server` with `Server::new(profile)`, `profile()`, `image()` (the image the engine
//!   scans), `print_map()` and `async fn serve(self: Arc<Self>, TcpListener, Events)`;
//! - a pure request handler that the golden tests in `tests/golden_<name>.rs` call directly.

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use anyhow::bail;
use serde_json::Value;
use tokio::net::{TcpListener, TcpStream};

use crate::core::engine::ScanTarget;
use crate::core::events::Events;

#[cfg(feature = "ads")]
pub mod ads;
#[cfg(feature = "modbus")]
pub mod modbus;
#[cfg(feature = "pccc")]
pub mod pccc;
#[cfg(feature = "s7")]
pub mod s7;
#[cfg(feature = "slmp")]
pub mod slmp;

/// The port a protocol listens on when none is given: the SFC adapter's own default, so an adapter with
/// default settings reaches the simulator. S7 and Modbus use privileged ports; on Linux, binding them
/// needs root or an explicit `--serve s7=10102`.
pub fn default_port(proto: &str) -> Option<u16> {
    match proto {
        "s7" => Some(102),       // ISO-on-TCP; PLC4X's default (S7Configuration.getDefaultPort)
        "ads" => Some(48898),    // AMS/TCP (AdsDeviceConfiguration.kt:70)
        "pccc" => Some(44818),   // EtherNet/IP (PcccControllerConfiguration.kt:83)
        // SFC's own SLMP default is 50000 (SlmpControllerConfiguration.kt:114), the first port of the e2e
        // suite's IPC services; 40000 stays clear of them. An SFC SLMP controller then sets Port 40000.
        "slmp" => Some(40000),
        "modbus" => Some(502),   // Modbus TCP (ModbusTcpDeviceConfiguration.kt:188)
        _ => None,
    }
}

/// The next connection. A failed accept (a client that aborted its handshake, EMFILE) is logged and retried
/// after 50 ms: it never ends the listener.
#[allow(dead_code)] // unused only in a build without any protocol
async fn accept(listener: &TcpListener, proto: &str) -> (TcpStream, SocketAddr) {
    loop {
        match listener.accept().await {
            Ok(accepted) => return accepted,
            Err(e) => {
                eprintln!("omni-plc-sim {proto}: accept failed: {e}");
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
        }
    }
}

/// The protocols compiled into this binary.
pub fn compiled() -> Vec<&'static str> {
    profiles().into_iter().map(|(name, _, _)| name).collect()
}

/// Every compiled protocol as (name, default profile, all profiles).
pub fn profiles() -> Vec<(&'static str, &'static str, &'static [&'static str])> {
    #[allow(unused_mut)]
    let mut out = Vec::new();
    #[cfg(feature = "s7")]
    out.push((s7::NAME, s7::DEFAULT_PROFILE, s7::PROFILES));
    #[cfg(feature = "ads")]
    out.push((ads::NAME, ads::DEFAULT_PROFILE, ads::PROFILES));
    #[cfg(feature = "pccc")]
    out.push((pccc::NAME, pccc::DEFAULT_PROFILE, pccc::PROFILES));
    #[cfg(feature = "slmp")]
    out.push((slmp::NAME, slmp::DEFAULT_PROFILE, slmp::PROFILES));
    #[cfg(feature = "modbus")]
    out.push((modbus::NAME, modbus::DEFAULT_PROFILE, modbus::PROFILES));
    out
}

/// A protocol server, as the binary runs it.
#[derive(Clone)]
pub enum Server {
    #[cfg(feature = "s7")]
    S7(Arc<s7::Server>),
    #[cfg(feature = "ads")]
    Ads(Arc<ads::Server>),
    #[cfg(feature = "pccc")]
    Pccc(Arc<pccc::Server>),
    #[cfg(feature = "slmp")]
    Slmp(Arc<slmp::Server>),
    #[cfg(feature = "modbus")]
    Modbus(Arc<modbus::Server>),
}

impl Server {
    /// The server for `proto` with `profile`, or the protocol's default profile.
    pub fn new(proto: &str, profile: Option<&str>) -> anyhow::Result<Server> {
        let _ = &profile;
        match proto {
            #[cfg(feature = "s7")]
            "s7" => Ok(Server::S7(Arc::new(s7::Server::new(profile.unwrap_or(s7::DEFAULT_PROFILE))?))),
            #[cfg(feature = "ads")]
            "ads" => Ok(Server::Ads(Arc::new(ads::Server::new(profile.unwrap_or(ads::DEFAULT_PROFILE))?))),
            #[cfg(feature = "pccc")]
            "pccc" => Ok(Server::Pccc(Arc::new(pccc::Server::new(profile.unwrap_or(pccc::DEFAULT_PROFILE))?))),
            #[cfg(feature = "slmp")]
            "slmp" => Ok(Server::Slmp(Arc::new(slmp::Server::new(profile.unwrap_or(slmp::DEFAULT_PROFILE))?))),
            #[cfg(feature = "modbus")]
            "modbus" => Ok(Server::Modbus(Arc::new(modbus::Server::new(profile.unwrap_or(modbus::DEFAULT_PROFILE))?))),
            other => bail!("unknown protocol {other:?}; compiled in: {}", compiled().join(", ")),
        }
    }

    pub fn name(&self) -> &'static str {
        match self {
            #[cfg(feature = "s7")]
            Server::S7(_) => s7::NAME,
            #[cfg(feature = "ads")]
            Server::Ads(_) => ads::NAME,
            #[cfg(feature = "pccc")]
            Server::Pccc(_) => pccc::NAME,
            #[cfg(feature = "slmp")]
            Server::Slmp(_) => slmp::NAME,
            #[cfg(feature = "modbus")]
            Server::Modbus(_) => modbus::NAME,
            #[cfg(not(any(feature = "s7", feature = "ads", feature = "pccc", feature = "slmp", feature = "modbus")))]
            _ => unreachable!(),
        }
    }

    pub fn profile(&self) -> String {
        match self {
            #[cfg(feature = "s7")]
            Server::S7(s) => s.profile().to_string(),
            #[cfg(feature = "ads")]
            Server::Ads(s) => s.profile().to_string(),
            #[cfg(feature = "pccc")]
            Server::Pccc(s) => s.profile().to_string(),
            #[cfg(feature = "slmp")]
            Server::Slmp(s) => s.profile().to_string(),
            #[cfg(feature = "modbus")]
            Server::Modbus(s) => s.profile().to_string(),
            #[cfg(not(any(feature = "s7", feature = "ads", feature = "pccc", feature = "slmp", feature = "modbus")))]
            _ => unreachable!(),
        }
    }

    /// The memory image the engine scans.
    pub fn image(&self) -> Arc<dyn ScanTarget> {
        match self {
            #[cfg(feature = "s7")]
            Server::S7(s) => s.image(),
            #[cfg(feature = "ads")]
            Server::Ads(s) => s.image(),
            #[cfg(feature = "pccc")]
            Server::Pccc(s) => s.image(),
            #[cfg(feature = "slmp")]
            Server::Slmp(s) => s.image(),
            #[cfg(feature = "modbus")]
            Server::Modbus(s) => s.image(),
            #[cfg(not(any(feature = "s7", feature = "ads", feature = "pccc", feature = "slmp", feature = "modbus")))]
            _ => unreachable!(),
        }
    }

    /// The default address map with its static values and signal names, for `--print-map`.
    pub fn print_map(&self) -> Value {
        match self {
            #[cfg(feature = "s7")]
            Server::S7(s) => s.print_map(),
            #[cfg(feature = "ads")]
            Server::Ads(s) => s.print_map(),
            #[cfg(feature = "pccc")]
            Server::Pccc(s) => s.print_map(),
            #[cfg(feature = "slmp")]
            Server::Slmp(s) => s.print_map(),
            #[cfg(feature = "modbus")]
            Server::Modbus(s) => s.print_map(),
            #[cfg(not(any(feature = "s7", feature = "ads", feature = "pccc", feature = "slmp", feature = "modbus")))]
            _ => unreachable!(),
        }
    }

    /// Accepts connections until the process ends.
    pub async fn serve(self, listener: TcpListener, events: Events) -> anyhow::Result<()> {
        let _ = (&listener, &events);
        match self {
            #[cfg(feature = "s7")]
            Server::S7(s) => s.serve(listener, events).await,
            #[cfg(feature = "ads")]
            Server::Ads(s) => s.serve(listener, events).await,
            #[cfg(feature = "pccc")]
            Server::Pccc(s) => s.serve(listener, events).await,
            #[cfg(feature = "slmp")]
            Server::Slmp(s) => s.serve(listener, events).await,
            #[cfg(feature = "modbus")]
            Server::Modbus(s) => s.serve(listener, events).await,
            #[cfg(not(any(feature = "s7", feature = "ads", feature = "pccc", feature = "slmp", feature = "modbus")))]
            _ => unreachable!(),
        }
    }
}
