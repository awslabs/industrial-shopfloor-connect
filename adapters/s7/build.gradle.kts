// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

group = "com.amazonaws.sfc"
version = "1.0.1"

plugins {
    id("sfc.module-conventions")
}

sfcModule {
    buildConfigPackage = "s7"
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(project(":core:sfc-ipc"))
    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)
    implementation(libs.kotlin.reflect)
    implementation(libs.commons.collections)
    implementation(libs.jackson.databind)
    implementation(libs.netty.codec)
    implementation(libs.plc4j.driver.s7)
    implementation(libs.slf4j.api)
    // slf4j-nop deliberately removed: it registers an SLF4JServiceProvider that competes with
    // log4j-slf4j2-impl. In the uberjar the NOP provider used to win, silently discarding every
    // log line from the AWS SDK, netty, hadoop, kafka, milo and plc4x. Noisy third-party logging
    // is now controlled by log4j2 levels instead.
}

application {
    mainClass.set("com.amazonaws.sfc.s7.S7ProtocolService")
}
