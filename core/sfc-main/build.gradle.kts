// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import java.time.LocalDate

group = "com.amazonaws.sfc"
version = rootProject.extra.get("sfc_release")!!

val module = "sfcmain"
val sfcCoreVersion = version
val sfcIpcVersion = version
val kotlinCoroutinesVersion = "1.6.2"
val kotlinVersion = "2.2.0"
val awsMskIamVersion = "1.1.6"
val awsSdkVersion = "2.31.18"
val awsSdkVersion2 = "2.29.30"
var icebergVersion = "1.6.1"

var awsIcebergVersion = "1.9.0"
var parquetVersion = "1.15.1"
var parquetFormatsVersion = "2.11.0"
var hadoopVersion = "3.4.1"
var slf4jVersion = "2.0.17"

plugins {
    id("sfc.kotlin-application-conventions")
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(project(":core:sfc-ipc"))
    implementation("org.jetbrains.kotlin:kotlin-stdlib-jdk8:$kotlinVersion")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:$kotlinCoroutinesVersion")

    // libraries required because of KAFKA class loading logic
    implementation("software.amazon.msk:aws-msk-iam-auth:$awsMskIamVersion")

    // s3 libraries required for s3 libraries dependencies for in process deployment of S3 adapter
    implementation("software.amazon.awssdk:s3:$awsSdkVersion2")

    // s3Tables libraries required for s3Tables libraries dependencies for in process deployment of S3Tables adapter
    implementation("org.apache.iceberg:iceberg-aws:${icebergVersion}")
    implementation("software.amazon.awssdk:s3tables:$awsSdkVersion2")

    implementation("org.slf4j:slf4j-nop:${slf4jVersion}")
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


tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile> {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_1_8)
        freeCompilerArgs.set(listOf("-opt-in=kotlin.time.ExperimentalTime", "-opt-in=kotlin.ExperimentalUnsignedTypes"))
    }
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
