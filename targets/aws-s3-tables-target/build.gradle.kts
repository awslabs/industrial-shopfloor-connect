// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import java.time.LocalDate

group = "com.amazonaws.sfc"
version = "1.0.1"

val sfcRelease = rootProject.extra.get("sfc_release")!!
val module = "awss3tables"
val sfcCoreVersion = sfcRelease
val sfcIpcVersion = sfcRelease
// need this one for S3 Tables version
// pinned deliberately: newer AWS SDK versions exhibited S3 Tables service-API issues
plugins {
    id("sfc.kotlin-application-conventions")
    java
}

repositories {
    mavenCentral()
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(project(":core:sfc-ipc"))

    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)

    implementation(libs.iceberg.core)
    implementation(libs.iceberg.parquet)
    implementation(libs.iceberg.data)
    implementation(libs.iceberg.api)
    implementation(libs.iceberg.aws)
    implementation(libs.iceberg.aws.bundle)

    implementation(libs.awssdk.s3tables)
    implementation(libs.awssdk.sts)
    implementation(libs.awssdk.url.connection.client)

    implementation(libs.parquet.avro)
    implementation(libs.parquet.column)
    implementation(libs.parquet.common)
    implementation(libs.parquet.encoding)

    implementation(libs.parquet.hadoop)
    implementation(libs.parquet.format)

    implementation(libs.hadoop.common)
    implementation(libs.hadoop.client)

    implementation(libs.slf4j.nop)
    
}

application {
    mainClass.set("com.amazonaws.sfc.awss3tables.AwsS3TablesTargetService")
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

