// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

plugins {
    id("sfc.kotlin-library-conventions")
    `maven-publish`
    jacoco
}

group = "com.amazonaws.sfc"
version = rootProject.extra.get("sfc_release")!!
dependencies {
    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)
    api(libs.gson)
    implementation(libs.kotlin.reflect)
    api(libs.commons.cli)
    implementation(libs.commons.codec)
    implementation(libs.commons.io)
    implementation(libs.commons.math3)

    implementation(libs.aws.encryption.sdk)
    implementation(libs.awssdk.crt)
    implementation(libs.awssdk.apache5.client)
    implementation(libs.awssdk.auth)
    implementation(libs.awssdk.aws.core)
    api(libs.awssdk.secretsmanager)

    implementation(libs.bcpkix)
    implementation(libs.bcprov)
    implementation(libs.ktor.client.core)
    implementation(libs.ktor.client.cio)
    api(libs.jmespath.core)
    api(libs.velocity.engine.core)
    implementation(libs.velocity.tools.generic)
    api(libs.jackson.dataformat.yaml)
    api(libs.paho.mqttv3)
    api(libs.log4j.api)
    api(libs.log4j.core)
    api(libs.log4j.slf4j2.impl)
    testImplementation(libs.mockk)
}

publishing {
    publications {
        create<MavenPublication>("maven") {
            from(components["kotlin"])
            groupId = group as String
            artifactId = "sfc-core"
            version = project.version.toString()
        }
    }
}

tasks.build {
    finalizedBy(tasks.publish)
}

tasks {
    //    jacocoTestCoverageVerification {
    //        violationRules {
    //            rule {
    //                limit {
    //                    counter = "LINE"
    //                    minimum = BigDecimal.valueOf(0.8)
    //                }
    //                limit {
    //                    counter = "BRANCH"
    //                    minimum = BigDecimal.valueOf(0.6)
    //                }
    //            }
    //        }
    //    }
    //    check {
    //        dependsOn(jacocoTestCoverageVerification)
    //    }

    withType<JacocoReport> {
        afterEvaluate {
            classDirectories.setFrom(
                files(
                    classDirectories.files.map {
                        fileTree(it).apply {
                            exclude(
                                "**/Generated*.class",

                                )
                        }
                    }
                )
            )
        }
    }
}
