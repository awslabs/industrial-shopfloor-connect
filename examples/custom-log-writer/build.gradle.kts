/*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.SPDX-License-Identifier: Apache-2.0
 */

group = "com.amazonaws.sfc"
version = "1.0.0"

plugins {
    id("sfc.kotlin-library-conventions")
    `maven-publish`
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(libs.kotlinx.coroutines.core)
}
