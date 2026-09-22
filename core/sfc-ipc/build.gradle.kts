// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import com.google.protobuf.gradle.*
import org.jetbrains.kotlin.gradle.tasks.KotlinCompile

group = "com.amazonaws.sfc"
version = rootProject.extra.get("sfc_release")!!

val protobufVersion = "3.21.7"
val grpcKotlinVersion = "1.3.0"
val grpcVersion = "1.54.1"
val sfcCoreVersion = version
plugins {
    id("com.google.protobuf") version "0.9.4"
    id("sfc.kotlin-library-conventions")
    idea
    `maven-publish`
}

dependencies {
    implementation(libs.kotlinx.coroutines.core)
    implementation(project(":core:sfc-core"))
    implementation(libs.commons.cli)
    api(libs.protobuf.java)
    api(libs.protobuf.java.util)
    api(libs.grpc.kotlin.stub)
    api(libs.grpc.netty.shaded)
    api(libs.grpc.protobuf)
    api(libs.grpc.stub)
    implementation(libs.kotlin.reflect)
    // Java
    compileOnly(libs.javax.annotation.api)
}

protobuf {
    protoc {
        artifact = "com.google.protobuf:protoc:$protobufVersion"
    }

    plugins {
        // Specify protoc to generate using kotlin protobuf plugin
        id("grpc") {
            artifact = "io.grpc:protoc-gen-grpc-java:$grpcVersion"
        }

        // Specify protoc to generate using our grpc kotlin plugin
        id("grpckt") {
            artifact = "io.grpc:protoc-gen-grpc-kotlin:$grpcKotlinVersion:jdk8@jar"
//            artifact = "io.grpc:protoc-gen-grpc-kotlin:$grpcKotlinVersion"
        }
    }

    generateProtoTasks {
        all().forEach {
            it.plugins {
                // Generate Java gRPC classes
                id("grpc")
                // Generate Kotlin gRPC using the custom plugin from library
                id("grpckt")
            }
        }
    }
}

idea {
    module {
        generatedSourceDirs.addAll(listOf(
            file("build/generated/source/proto/main/grpc"),
            file("build/generated/source/proto/main/java")
        ))
    }
}

publishing {

    publications {
        create<MavenPublication>("maven") {
            from(components["kotlin"])
            groupId = group as String
            artifactId = "sfc-ipc"
            version = version
        }
    }

}

tasks.build {
    finalizedBy(tasks.publish)
}

tasks.processResources {
    dependsOn("extractProto")
}
