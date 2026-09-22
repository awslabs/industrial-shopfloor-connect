// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

group = "com.amazonaws.sfc"
version = "1.0.1"

plugins {
    id("sfc.module-conventions")
}

sfcModule {
    buildConfigPackage = "awsmsk"
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(project(":core:sfc-ipc"))
    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)
    implementation(libs.kafka.clients)
    implementation(libs.aws.sdk.v1.core)
    implementation(libs.awssdk.crt)
    implementation(libs.awssdk.auth)
    implementation(libs.msk.iam.auth)
    implementation(libs.gson)
}

application {
    mainClass.set("com.amazonaws.sfc.awsmsk.AwsMskTargetService")
}
