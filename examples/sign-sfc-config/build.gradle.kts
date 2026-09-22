// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

group = "com.amazonaws.sfc"
version = "1.0.0"

plugins {
    id("sfc.kotlin-application-conventions")
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(libs.kotlin.stdlib.jdk8)
}

application {
    mainClass.set("com.amazonaws.sfc.SignConfig")
}

// Deliberately not sfc.dist-conventions: this is a local signing helper, so its archive stays an
// uncompressed .tar and is never collected into build/distribution for release.
tasks.getByName<Zip>("distZip").enabled = false
tasks.getByName<Tar>("distTar").archiveFileName.set("${project.name}.tar")
