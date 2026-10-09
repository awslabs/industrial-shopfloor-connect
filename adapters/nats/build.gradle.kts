// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

group = "com.amazonaws.sfc"
version = "2.0.0"

plugins {
    id("sfc.module-conventions")
}

sfcModule {
    buildConfigPackage = "nats"
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(project(":core:sfc-ipc"))
    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)
    implementation(libs.kotlin.reflect)
    implementation(libs.jnats) {
        // jnats pulls bcprov-lts8on, which ships the same org.bouncycastle packages under a
        // different artifactId - so Gradle cannot deduplicate it against bcprov-jdk18on and the
        // uberjar ends up with two copies of the crypto provider. sfc-core already provides
        // bcprov-jdk18on 1.85, which supersedes the LTS 2.73.x line.
        exclude(group = "org.bouncycastle", module = "bcprov-lts8on")
    }
    implementation(libs.gson)
    implementation(libs.jmespath.core)
}

application {
    mainClass.set("com.amazonaws.sfc.nats.NatsProtocolService")
}
