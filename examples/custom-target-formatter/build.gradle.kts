// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

group = "com.amazonaws.sfc"
version = "1.0.0"

// Not sfc.module-conventions: this example generated a BuildConfig into com.amazonaws.sfc.config -
// a real sfc-core package - that nothing read, and all four such examples generated the same
// class name, so the uberjar shipped four colliding copies of it.
plugins {
    id("sfc.kotlin-library-conventions")
    id("sfc.dist-conventions")
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(libs.kotlinx.coroutines.core)
}

// Deliberately not part of the release: this module is a code sample, so its tarball stays in the
// module's own build directory instead of build/distribution, which the release workflow globs.
tasks.named("copyDist") {
    enabled = false
}
