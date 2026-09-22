// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

group = "com.amazonaws.sfc"
version = "1.0.1"

plugins {
    id("sfc.module-conventions")
}

sfcModule {
    buildConfigPackage = "awss3tables"
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
    // iceberg-aws reflectively loads ApacheHttpClient$Builder (HttpClientProperties), so the
    // HttpClient 4 based client must be present at runtime even though SFC's own code uses
    // apache5-client. Without it: NoClassDefFoundError when S3FileIO creates an output file.
    runtimeOnly(libs.awssdk.apache.client)
    // iceberg-aws-bundle deliberately omitted: it is a 61 MB fat jar shipping ~19,800
    // UNRELOCATED software.amazon.awssdk classes for environments that lack the AWS SDK.
    // SFC declares the SDK explicitly, so the bundle only duplicated it at iceberg's pinned
    // version - 8,891 colliding class paths in the uberjar.

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

    // slf4j-nop deliberately removed: it registers an SLF4JServiceProvider that competes with
    // log4j-slf4j2-impl. In the uberjar the NOP provider used to win, silently discarding every
    // log line from the AWS SDK, netty, hadoop, kafka, milo and plc4x. Noisy third-party logging
    // is now controlled by log4j2 levels instead.
    
}

application {
    mainClass.set("com.amazonaws.sfc.awss3tables.AwsS3TablesTargetService")
}
