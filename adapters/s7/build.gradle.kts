// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import java.time.LocalDate

group = "com.amazonaws.sfc"
version = "1.0.1"

val sfcRelease = rootProject.extra.get("sfc_release")!!
val module = "s7"
val sfcCoreVersion = sfcRelease
val sfcIpcVersion = sfcRelease
plugins {
    id("sfc.kotlin-application-conventions")
    java
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(project(":core:sfc-ipc"))
    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)
    implementation(libs.kotlin.reflect)
    implementation(libs.commons.collections)
    implementation(libs.jackson.databind)
    implementation(libs.netty.codec)
    implementation(libs.plc4j.driver.s7)
    implementation(libs.slf4j.api)
    implementation(libs.slf4j.nop)
}

application {
    mainClass.set("com.amazonaws.sfc.s7.S7ProtocolService")
    applicationName = project.name
}

tasks.getByName<Zip>("distZip").enabled = false
tasks.distTar {
    project.version = version
    archiveBaseName = "${project.name}"
    compression = Compression.GZIP
    archiveExtension = "tar.gz"
    archiveFileName = "${project.name}.tar.gz"
}

tasks.register<Copy>("copyDist") {
    from(layout.buildDirectory.dir("distributions"))
    include("*.tar.gz")
    into(layout.buildDirectory.dir("../../../build/distribution/"))
}

tasks.register("generateBuildConfig") {
    val version = project.version.toString()

    val versionSource = resources.text.fromString(
        """
          |package com.amazonaws.sfc.$module
          |
          |object BuildConfig {
          |  const val CORE_VERSION = "$sfcCoreVersion" 
          |  const val IPC_VERSION = "$sfcIpcVersion"
          |  const val VERSION = "$version"
          |    override fun toString() = "SFC_MODULE ${project.name.uppercase()}: VERSION=${'$'}VERSION, SFC_CORE_VERSION=${'$'}CORE_VERSION, SFC_IPC_VERSION=${'$'}IPC_VERSION, BUILD_DATE=${LocalDate.now()}"
          |}
          |
        """.trimMargin()
    )

    copy {
        from(versionSource)
        into("src/main/kotlin/com/amazonaws/sfc/$module")
        rename { "BuildConfig.kt" }
    }
}

tasks.named("build") {
    dependsOn("generateBuildConfig")
    finalizedBy("copyDist")
}
