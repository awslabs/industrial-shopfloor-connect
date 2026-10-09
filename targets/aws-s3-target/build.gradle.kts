// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

group = "com.amazonaws.sfc"
version = "1.0.1"

plugins {
    id("sfc.module-conventions")
}

sfcModule {
    buildConfigPackage = "awss3"
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(project(":core:sfc-ipc"))
    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)

    implementation(libs.awssdk.s3)

}

application {
    mainClass.set("com.amazonaws.sfc.awss3.AwsS3TargetService")
}
