// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

group = "com.amazonaws.sfc"
version = "1.0.0"

plugins {
    id("sfc.module-conventions")
}

sfcModule {
    buildConfigPackage = "modbus.tcp"
    // The Modbus wire-protocol library in adapters/modbus is versioned independently of this
    // adapter, so its version is reported as a second field in the start-up log line.
    extraVersions.put("MODBUS_VERSION", "1.0.0")
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(project(":core:sfc-ipc"))
    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)
    api(project(":adapters:modbus"))
}

application {
    mainClass.set("com.amazonaws.sfc.modbus.tcp.ModbusTcpProtocolService")
}
