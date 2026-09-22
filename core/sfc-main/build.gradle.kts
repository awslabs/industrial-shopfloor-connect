// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import java.time.LocalDate

group = "com.amazonaws.sfc"
version = rootProject.extra.get("sfc_release")!!

val module = "sfcmain"
val sfcCoreVersion = version
val sfcIpcVersion = version
plugins {
    id("sfc.kotlin-application-conventions")
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(project(":core:sfc-ipc"))
    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)

    // libraries required because of KAFKA class loading logic
    implementation(libs.msk.iam.auth)

    // s3 libraries required for s3 libraries dependencies for in process deployment of S3 adapter
    implementation(libs.awssdk.s3)

    // s3Tables libraries required for s3Tables libraries dependencies for in process deployment of S3Tables adapter
    implementation(libs.iceberg.aws)
    implementation(libs.awssdk.s3tables)

    // slf4j-nop deliberately removed: it registers an SLF4JServiceProvider that competes with
    // log4j-slf4j2-impl. In the uberjar the NOP provider used to win, silently discarding every
    // log line from the AWS SDK, netty, hadoop, kafka, milo and plc4x. Noisy third-party logging
    // is now controlled by log4j2 levels instead.
}

application {
    // Define the main class for the application.
    mainClass.set("com.amazonaws.sfc.MainController")
    applicationName = project.name
}

tasks.getByName<Zip>("distZip").enabled = false

tasks.distTar {
	project.version = ""
	archiveBaseName = "${project.name}"
	compression = Compression.GZIP
	archiveExtension = "tar.gz"
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
          |  const val MODULE_VERSION = "$version"
          |    override fun toString() = "SFC_MODULE ${project.name.uppercase()}: VERSION=${'$'}MODULE_VERSION, SFC_CORE_VERSION=${'$'}CORE_VERSION, SFC_IPC_VERSION=${'$'}IPC_VERSION, BUILD_DATE=${LocalDate.now()}"
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
