// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

group = "com.amazonaws.sfc"
version = "1.0.0"

// Not sfc.module-conventions: the BuildConfig this used to generate landed in sfc-core's
// com.amazonaws.sfc.config package, had no readers, and collided with three other examples.
plugins {
    id("sfc.kotlin-library-conventions")
    id("sfc.dist-conventions")
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(libs.kotlinx.coroutines.core)
}
