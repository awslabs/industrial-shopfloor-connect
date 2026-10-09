// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

group = "com.amazonaws.sfc"
version = rootProject.extra.get("sfc_release")!!

plugins {
    id("sfc.module-conventions")
}

sfcModule {
    buildConfigPackage = "cloudwatch"
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(project(":core:sfc-ipc"))
    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)
    implementation(libs.awssdk.cloudwatch)
}

application {
    mainClass.set("com.amazonaws.sfc.cloudwatch.AwsCloudWatchMetricsWriterService")
}
