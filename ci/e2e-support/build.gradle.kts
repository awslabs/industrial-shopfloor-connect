// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Support code for the end-to-end integration suite (ci/e2e). Deliberately a LIBRARY module:
// sfc.kotlin-library-conventions produces a plain jar with no `application` block, no distTar and no
// copyDist, so this module contributes nothing to build/distribution. The release workflow globs
// build/distribution/*.tar.gz, and that set must stay exactly as it is.

group = "com.amazonaws.sfc"
version = "1.0.0"

plugins {
    id("sfc.kotlin-library-conventions")
}

dependencies {
    // MetricsWriter, MetricsData, ConfigReader and Logger all live in sfc-core.
    implementation(project(":core:sfc-core"))
    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)
    implementation(libs.gson)
}
