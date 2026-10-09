// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

group = "com.amazonaws.sfc"
version = "1.0.1"

plugins {
    id("sfc.module-conventions")
}

sfcModule {
    buildConfigPackage = "router"
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(project(":core:sfc-ipc"))
    implementation(libs.gson)
    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)
}

application {
    mainClass.set("com.amazonaws.sfc.router.AwsRouterTargetService")
}
