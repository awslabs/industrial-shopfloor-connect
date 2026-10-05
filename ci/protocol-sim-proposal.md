## Architecture Proposal: OmniPLC Sim (Universal Shopfloor Edition)

A modular, high-performance, and asynchronous industrial protocol simulator written in Rust, expanding upon the full suite of shop floor adapters outlined in the AWS Industrial Shopfloor Connect framework.


## 1. Updated Core Architecture & Design Patterns
To simulate all fourteen distinct industrial, automotive, and IT edge-messaging protocols concurrently within a single lightweight engine, the application employs an asynchronous, decoupled, event-driven architecture.


```sh
                                +------------------------+
                                |   Virtual Memory PLC   |
                                |   (Global Data Store)  |
                                +------------+-----------+
                                             |
      +------------------------+-------------+-------------+-----------------------+
      |                        |                           |                       |
+-----+------+           +-----+------+              +-----+-----+           +-----+------+
| Polled Bus |           | Stream Sync|              | Relational|           | Native RPC |
| Adapters   |           | Adapters   |              | Adapters  |           | Adapters   |
+-----+------+           +-----+------+              +-----+-----+           +-----+------+
      |                        |                           |                       |
 [J1939 / Modbus]        [MQTT / NATS]                 [SQL Server]         [REST / OPC UA]
 ```

## Key Design Patterns

* Adapter / Protocol Translation Pattern: Every incoming protocol package or stream is decoded into a unified, protocol-agnostic instruction command (e.g., ReadRequest { space: MemorySpace, offset: usize, len: usize }).
* Actor Pattern (via Tokio Channels): The virtual memory array behaves as the single source of truth managed by a central supervisor state. Individual protocol engines handle network connections independently, forwarding requests and receiving data slices using asynchronous multi-producer, single-consumer (mpsc) queues to prevent race conditions.
* Publisher/Subscriber Mapping: For broker abstractions (MQTT, NATS), the engine acts as an embedded broker or localized client loop. Changing a virtual register inside the core pipeline instantly triggers an outgoing notification event published to the respective topic hierarchy.
* Virtual Data-to-Wire Format Transformation: For protocols serving structured records (REST, SQL), the memory store dynamically maps flat array bytes into JSON payloads or database-wire data packets on demand.


## 2. Universal Protocol Crates Selection
The universal simulator balances performance and scalability by leveraging standard ecosystem frameworks for systems-level tasks alongside domain-specific communication crates:

## Foundational Systems Layer

* [tokio](https://crates.io/crates/tokio): The multi-threaded, asynchronous runtime engine controlling all background tasks, network sockets, and loop loops.
* [bytes](https://crates.io/crates/bytes): High-speed, zero-copy memory abstractions optimized for heavy raw binary packet streaming.
* [parking_lot](https://crates.io/crates/parking_lot): Fast, low-latency concurrency primitives (Mutex, RwLock) ensuring thread-safe access across protocol workers.
* nom: A highly flexible parser-combinator framework used to safely unpack complex, structured byte patterns.
* [serde](https://crates.io/crates/serde): For loading baseline hardware map files, address offsets, and register layouts via local JSON or TOML configurations.
* [tracing](https://crates.io/crates/tracing): A structured, asynchronous telemetry engine critical for tracking down complex industrial network timing issues.

## Deep-Level Industrial Protocol Drivers

* Siemens S7 Comm: rs-snap7 handles direct S7 block layout mappings, using [snap7-cli](https://lib.rs/crates/snap7-cli) for testing binary loops.
* Beckhoff ADS: [ads-proto](https://crates.io/crates/ads) handles deep-level serialization of complex AMS router structures, while ads provides client reference mappings.
* Mitsubishi SLMP: Inspired by the framework of [melsec_mc_mock](https://crates.io/crates/melsec_mc) or implementing manual 3E/4E frame wrappers via [plc-comm-slmp](https://github.com/fa-yoshinobu/plc-comm-slmp-rust).
* Rockwell EtherNet/IP & PCCC: [ethernetip-core](https://crates.io/crates/ethernetip-core) provides processing for explicit encapsulation framing and Common Packet Format (CPF) tags. Logix interactions can be mirrored after [rseip](https://crates.io/crates/slmp).
* Modbus TCP: [tokio-modbus](https://crates.io/crates/tokio-modbus) scales down effortlessly into an embedded slave instance, allowing you to quickly spin up listening sockets on default Port 502 for holding registers and coil fields.
* OPC UA: [opcua](https://crates.io/crates/opcua) exposes a fully compliant, secure local server instance (opcua-server) to publish customized address nodes across standard automation discovery networks.
* OPC DA (Legacy Windows): Interfacing with old legacy OLE architectures uses custom bindings powered by com-rs or the direct ecosystem [windows](https://crates.io/crates/windows) metadata API. Note: Compiles solely when targeting Windows OS (#[cfg(target_os = "windows")]).

## Automotive, Cloud Edge & Broker Abstractions

* J1939 (Heavy Vehicle CAN Bus): [socketcan](https://crates.io/crates/socketcan) provides a straight bridge to Linux SocketCAN networking, pushing real-time Parameter Group Numbers (PGNs) over a virtual test channel (vcan0).
* MQTT: [rumqttd](https://crates.io/crates/rumqttd) strips out the need to manage standalone external broker software by running a high-speed, lightweight MQTT broker directly inside your Rust process space.
* NATS: [async-nats](https://crates.io/crates/async-nats) establishes direct hookups to cloud-native distributed edge pipelines using async worker models.

## IT Application Layers & Storage Providers

* REST HTTP Service: [axum](https://crates.io/crates/axum) acts as the local web presentation engine, translating memory variables directly into unified JSON response endpoints.
* SNMP (Network Infrastructure): [rasn-snmp](https://crates.io/crates/rasn-snmp) handles the underlying ASN.1 schema logic needed to simulate router or hardware appliance status tracking loops over UDP Port 161.
* SQL Server Database Mock: Built using the pure Rust driver foundation of [sqlite](https://crates.io/crates/sqlite) for lightweight relational databases, or pg_wire to mock a full database engine over the standard PostgreSQL protocol.

## 3. High-Level Modular Directory Layout

```sh
omni_plc_sim/
├── Cargo.toml
├── src/
│   ├── main.rs                 # Application entry point, spins up Tokio runtimes
│   ├── core/                   # Unified internal logic
│   │   ├── mod.rs
│   │   ├── memory.rs           # Holds everything from global coils to SQL tables
│   │   └── engine.rs           # Internal message routing actor
│   └── protocols/              # Individual server engines
│       ├── mod.rs
│       ├── s7comm.rs           # Port 102: Handles ISO-on-TCP & S7 framing
│       ├── ads.rs              # Port 48898: Handles AMS/ADS routing structures
│       ├── slmp.rs             # Port 5002: Handles MC 3E/4E binary patterns
│       ├── ethernetip.rs       # Port 44818: Handles CIP explicit routing and PCCC commands
│       ├── modbus.rs           # Port 502: Handles Modbus coil & register fields
│       ├── opcua.rs            # Port 4840: Handles standard secure OPC UA node maps
│       ├── opcda.rs            # Windows-only DCOM native wrapper component
│       ├── j1939.rs            # Linux vcan0 CAN network integration wrapper
│       ├── mqtt.rs             # Port 1883: Features the embedded rumqttd broker
│       ├── nats.rs             # Port 4222: NATS stream broker connectivity loops
│       ├── rest.rs             # Port 8080: Web API mapping layer
│       ├── snmp.rs             # UDP Port 161: Network instrumentation response engine
│       └── sql.rs              # Port 5432: Dynamic PostgreSQL database wire simulator
```



To bridge the gap between static memory arrays and a realistic shop floor environment, the simulator needs a dynamic Signal Generation Engine and a flexible Tag/Symbol Map Schema.
Below is the architectural draft for how omni_plc_sim manages these two domains programmatically in Rust.

---

## Data Engine & Simulation Specification: OmniPLC Sim## 1. Unified Tag & Symbol Map Schema

To decouple raw memory address offsets (like S7's DB100.DBD4 or Modbus Holding Register 40001) from high-level IT strings (like JSON fields or OPC UA Nodes), we use a structured Symbol Configuration Schema.
This mapping is parsed at runtime via serde from a unified config.toml file:

# config.toml - System Definition Map

```toml
[[tags]]
name = "Zone1.Conveyor.Speed"
description = "Current line speed in meters per minute"
datatype = "Float32"
simulation_profile = "SineWave"
min_value = 0.0
max_value = 60.0
frequency_hz = 0.2
# Address Cross-References for Industrial Engines
[tags.mappings]
s7comm = { db = 100, offset = 0 }          # Read via DB100.DBD0
modbus = { register_type = "Holding", address = 0 } # Read via HR 40001
ethernetip = { tag_name = "Z1_Conv_Speed" } # Raw CIP Explicit String tag
ads = { symbol = "MAIN.fConveyorSpeed" }   # TwinCAT ADS symbol handle

[[tags]]
name = "Zone1.Conveyor.Fault"
description = "Boolean trip wire alarm indicator"
datatype = "Boolean"
simulation_profile = "RandomWalk"
change_probability = 0.02 # 2% chance to flip every iteration

[tags.mappings]
s7comm = { db = 100, offset = 4 }          # Read via DB100.DBX4.0
modbus = { register_type = "Coil", address = 5 } # Read via Coil 00006
ethernetip = { tag_name = "Z1_Conv_Fault" }
ads = { symbol = "MAIN.bConveyorFault" }
```

In Rust, this schema translates into strongly-typed structures:

```rust
// src/core/config.rsuse serde::{Deserialize, Serialize};use std::collections::HashMap;

#[derive(Debug, Serialize, Deserialize, Clone)]pub enum DataType {
    Boolean,
    Int32,
    Float32,
}

#[derive(Debug, Serialize, Deserialize, Clone)]pub enum SimProfile {
    Constant(f64),
    SineWave,
    RandomWalk,
    Noise,
}

#[derive(Debug, Serialize, Deserialize, Clone)]pub struct TagConfig {
    pub name: String,
    pub datatype: DataType,
    pub simulation_profile: SimProfile,
    pub min_value: f64,
    pub max_value: f64,
    pub frequency_hz: Option<f64>,
    pub change_probability: Option<f64>,
    pub mappings: HashMap<String, serde_json::Value>,
}
```

## 2. Numeric Simulation Algorithms Engine
Instead of raw randomized values, the engine uses deterministic and time-stepped calculations to closely match physical realities (like temperature variations, motor spin-ups, or noise profiles).

```rust
// src/core/simulation.rsuse std::f64::consts::PI;use std::time::Instant;use rand::Rng;
pub struct SignalGenerator {
    start_time: Instant,
    last_walk_value: f64,
}
impl SignalGenerator {
    pub fn new(initial_value: f64) -> Self {
        Self {
            start_time: Instant::now(),
            last_walk_value: initial_value,
        }
    }

    /// Generates a perfectly fluid Sine Wave over elapsed time
    pub fn sine_wave(&self, frequency_hz: f64, min: f64, max: f64) -> f64 {
        let elapsed = self.start_time.elapsed().as_secs_f64();
        let amplitude = (max - min) / 2.0;
        let midpoint = min + amplitude;
        
        // y = A * sin(2 * pi * f * t) + vertical_shift
        midpoint + amplitude * (2.0 * PI * frequency_hz * elapsed).sin()
    }

    /// Simulates drifting telemetry or machine thermal expansion (Brownian Noise pattern)
    pub fn random_walk(&mut self, change_probability: f64, min: f64, max: f64) -> f64 {
        let mut rng = rand::rng();
        
        if rng.random_bool(change_probability) {
            // Random small offset step (-1% to +1% of total range)
            let step_size = (max - min) * 0.01;
            let step = rng.random_range(-step_size..step_size);
            
            self.last_walk_value = (self.last_walk_value + step).clamp(min, max);
        }
        
        self.last_walk_value
    }

    /// Generates stable signals layered with standard instrumentation measurement errors
    pub fn noise(&self, base_value: f64, noise_variance: f64) -> f64 {
        let mut rng = rand::rng();
        let error = rng.random_range(-noise_variance..noise_variance);
        base_value + error
    }
}
```


## 3. High-Performance Memory Mapping Structure
To make this data available globally across the individual protocol threads (S7, Modbus, OPC UA) without causing application deadlocks, the core architecture applies an memory-aligned VirtualBackplane using explicit Atomic types or read-write locks (RwLock).

```rust
// src/core/memory.rsuse std::sync::Arc;use parking_lot::RwLock;use bytes::{BytesMut, BufMut};

#[derive(Clone)]pub struct VirtualBackplane {
    // A thread-safe, continuous raw byte array mimicking physical memory
    pub s7_data_blocks: Arc<RwLock<Vec<Vec<u8>>>>,
    pub modbus_registers: Arc<RwLock<Vec<u16>>>,
}
impl VirtualBackplane {
    pub fn new() -> Self {
        Self {
            s7_data_blocks: Arc::new(RwLock::new(vec![vec![0u8; 1024]; 200])), // 200 DBs, each 1KB
            modbus_registers: Arc::new(RwLock::new(vec![0u16; 10000])),        // 10k Holding registers
        }
    }

    /// Thread-safe update of a multi-byte Float value mapped across multiple targets
    pub fn write_float32_to_s7(&self, db: usize, offset: usize, value: f32) {
        let bytes = value.to_be_bytes(); // Siemens uses Big-Endian byte orders
        let mut db_guard = self.s7_data_blocks.write();
        if let Some(block) = db_guard.get_mut(db) {
            if offset + 4 <= block.len() {
                block[offset..offset+4].copy_from_slice(&bytes);
            }
        }
    }

    pub fn write_float32_to_modbus(&self, start_address: usize, value: f32) {
        let bits = value.to_bits();
        let reg1 = (bits >> 16) as u16;
        let reg2 = (bits & 0xFFFF) as u16;
        
        let mut reg_guard = self.modbus_registers.write();
        if start_address + 1 < reg_guard.len() {
            reg_guard[start_address] = reg1;
            reg_guard[start_address + 1] = reg2;
        }
    }
}
```

## 4. The Main Simulation Execution Loop
The orchestration brings everything together in an async loop task that updates the VirtualBackplane metrics precisely at a configured cycle rate (e.g., every 50ms):

```rust
// src/main.rsmod core;use crate::core::{memory::VirtualBackplane, simulation::SignalGenerator};use std::time::Duration;

#[tokio::main]async fn main() {
    let backplane = VirtualBackplane::new();
    let mut speed_gen = SignalGenerator::new(0.0);
    
    let backplane_clone = backplane.clone();
    
    // Spawn the structural generation loop task
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_millis(50));
        
        loop {
            interval.tick().await;
            
            // Calculate new telemetry data point
            let current_speed = speed_gen.sine_wave(0.2, 0.0, 60.0) as f32;
            
            // Mirror single data point instantly across distinct physical layers
            backplane_clone.write_float32_to_s7(100, 0, current_speed);      // Maps to S7
            backplane_clone.write_float32_to_modbus(0, current_speed);     // Maps to Modbus
        }
    });

    // Spin up all individual async network engines here...
    // e.g., protocols::s7comm::start_server(backplane.clone()).await;
    
    println!("OmniPLC Simulator operational. Channels active.");
    tokio::signal::ctrl_c().await.unwrap();
}
```
