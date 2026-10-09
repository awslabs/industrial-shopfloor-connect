// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

group = "com.amazonaws.sfc"
version = "1.0.0"

plugins {
    id("sfc.module-conventions")
}

sfcModule {
    buildConfigPackage = "sql"
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(project(":core:sfc-ipc"))
    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)
    implementation(libs.kotlin.reflect)
    implementation(libs.postgresql)
    implementation(libs.mariadb.java.client)
    implementation(libs.ojdbc8)
    implementation(libs.mssql.jdbc)
    implementation(libs.mysql.connector.j) {
        // Only needed for the X DevAPI, which SFC does not use. Left in, it drags
        // protobuf 4.x in and conflicts with the protobuf that gRPC is built against.
        exclude(group = "com.google.protobuf", module = "protobuf-java")
    }
    implementation(libs.gson)
}

application {
    mainClass.set("com.amazonaws.sfc.sql.SqlProtocolService")
}
