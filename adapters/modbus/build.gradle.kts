// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

group = "com.amazonaws.sfc"
version = "1.0.0"

plugins {
    id("sfc.kotlin-library-conventions")
    `maven-publish`
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)
}

publishing {
    publications {
        create<MavenPublication>("maven") {
            from(components["kotlin"])
            groupId = group as String
            artifactId = "modbus"
            version = project.version.toString()
        }
    }
}

tasks.build {
    finalizedBy(tasks.publishToMavenLocal)
}
