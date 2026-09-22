// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

group = "com.amazonaws.sfc"
// Do not clear this to shorten the release archive name: sfc.dist-conventions pins
// archiveFileName, so sfc-main.tar.gz no longer depends on the version being empty. Emptying it
// leaked into every other task in the project and made this module's own jar name
// (sfc-main.jar vs sfc-main-1.11.0.jar) depend on task realization order.
version = rootProject.extra.get("sfc_release")!!

plugins {
    id("sfc.module-conventions")
}

sfcModule {
    buildConfigPackage = "sfcmain"
    // sfc-main and sfc-uberjar name the constant MODULE_VERSION; adapters and targets use VERSION.
    versionConstant = "MODULE_VERSION"
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
    // iceberg-aws reflectively loads ApacheHttpClient$Builder (HttpClientProperties), so the
    // HttpClient 4 based client must be on the runtime classpath even though nothing references
    // it at compile time. Without it: NoClassDefFoundError when S3FileIO creates an output file.
    runtimeOnly(libs.awssdk.apache.client)
    implementation(libs.awssdk.s3tables)

    // slf4j-nop deliberately removed: it registers an SLF4JServiceProvider that competes with
    // log4j-slf4j2-impl. In the uberjar the NOP provider used to win, silently discarding every
    // log line from the AWS SDK, netty, hadoop, kafka, milo and plc4x. Noisy third-party logging
    // is now controlled by log4j2 levels instead.
}

application {
    // Define the main class for the application.
    mainClass.set("com.amazonaws.sfc.MainController")
}
