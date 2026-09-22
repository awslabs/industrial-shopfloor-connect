// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import com.github.jengelman.gradle.plugins.shadow.transformers.Log4j2PluginsCacheFileTransformer
import java.time.LocalDate

plugins {
    id("sfc.kotlin-application-conventions")
    alias(libs.plugins.shadow)
}

group = "com.amazonaws.sfc"
version = rootProject.extra.get("sfc_release")!!

val sfcRelease = rootProject.extra.get("sfc_release")!!
val module = "uberjar"
val sfcCoreVersion = sfcRelease
val sfcIpcVersion = sfcRelease

// Modules whose code is bundled into the single executable jar.
//
// Previously this looped over rootProject.project(":examples").childProjects, which is how the
// heaviest example silently pulled tomcat, h2, JWT and a second ktor version into the product.
// The list is explicit so that adding a module to the uberjar is a deliberate, reviewable act.
val uberjarExamples = listOf(
    "custom-config-provider",
    "custom-log-writer",
    "custom-target-formatter",
    "mqtt-config-provider",
    "opcua-auto-discovery",
    "sign-sfc-config",
    "yaml-custom-config-provider",
)

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(project(":core:sfc-main"))
    implementation(project(":core:sfc-ipc"))

    rootProject.project(":adapters").childProjects.values.forEach { implementation(project(it.path)) }
    rootProject.project(":targets").childProjects.values.forEach { implementation(project(it.path)) }
    rootProject.project(":metrics").childProjects.values.forEach { implementation(project(it.path)) }
    uberjarExamples.forEach { implementation(project(":examples:$it")) }

    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)
}

application {
    mainClass.set("com.amazonaws.sfc.MainController")
    applicationName = project.name
}

// The plain jar holds only this module's generated BuildConfig. It is what distTar and
// startScripts consume, so it is given a classifier to leave the documented
// "sfc-uberjar-<version>.jar" filename to the fat jar below
// (docs/sfc-running-core-process.md tells users to run `java -jar sfc-uberjar-1.x.x.jar`).
tasks.jar {
    archiveClassifier.set("thin")
}

// The single executable jar. Shadow resolves from runtimeClasspath, so the uberjar now contains
// exactly the versions each module was compiled against - the previous hand-rolled `mergedJar`
// configuration had no attributes and pooled all modules into one newest-wins resolution.
tasks.shadowJar {
    isZip64 = true

    // Must be INCLUDE: duplicatesStrategy takes precedence over transformers, and the inherited
    // EXCLUDE silently discarded duplicate META-INF/services entries before mergeServiceFiles()
    // ever saw them - which is the original defect reproduced through a different mechanism.
    duplicatesStrategy = DuplicatesStrategy.INCLUDE
    archiveBaseName.set("sfc-uberjar")
    archiveClassifier.set("")

    // Concatenate META-INF/services instead of keeping only the first copy. The old
    // DuplicatesStrategy.EXCLUDE silently dropped all but one provider per service, which cost
    // four of five JDBC drivers, Jackson's YAMLFactory and the real slf4j binding.
    mergeServiceFiles()

    // Log4j2Plugins.dat is a binary index that must be merged, not overwritten.
    transform(Log4j2PluginsCacheFileTransformer::class.java)

    exclude(
        // Signatures are invalid once jars are merged. The old build excluded only *.SF, leaving
        // the .DSA/.RSA files behind.
        "META-INF/*.SF", "META-INF/*.DSA", "META-INF/*.RSA", "META-INF/*.EC",
        "META-INF/SIG-*",
        // A stale index breaks classloading for the jars it claims to describe.
        "META-INF/INDEX.LIST",
        // A root module-info in a non-modular fat jar confuses tooling.
        "module-info.class",
        "META-INF/versions/*/module-info.class",
    )

    // 36 modules each ship a log4j2.xml at the classpath root, so under the old first-wins merge
    // the product's logging config was whichever module happened to be merged first. Drop all of
    // them and install this module's own copy (kept under a different source name so that the
    // exclude below does not also remove it).
    exclude("log4j2.xml")
    from("src/main/resources/uberjar-log4j2.xml") { rename { "log4j2.xml" } }

    manifest {
        attributes(
            "Main-Class" to "com.amazonaws.sfc.MainController",
            // 1500+ META-INF/versions entries were dead weight without this.
            "Multi-Release" to "true",
            "Implementation-Title" to "AWS Shop Floor Connectivity",
            "Implementation-Version" to project.version.toString(),
        )
    }

    // Make the artifact byte-stable for a given input set.
    isPreserveFileTimestamps = false
    isReproducibleFileOrder = true
}

tasks.named("build") {
    dependsOn("shadowJar")
}

// Every other module disables distZip; this one did not, so a ~235 MB zip was built and thrown
// away on every CI run alongside the tar.gz that copyDist actually consumes.
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

