// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

//! omni-plc-sim: server-side simulators of the PLC protocols SFC's adapters read (S7, ADS, PCCC,
//! SLMP, Modbus TCP), for the end-to-end suite in `ci/e2e`.
//!
//! `core` holds what every protocol shares: the scan engine and its signals, the clock, the event log
//! and byte helpers. `protocols` holds one module per protocol, each a frame codec, a pure request
//! handler, a default address map and its PLC profiles.

pub mod core;
pub mod protocols;
