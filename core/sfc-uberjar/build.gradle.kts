// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import com.github.jengelman.gradle.plugins.shadow.transformers.Log4j2PluginsCacheFileTransformer

plugins {
    id("sfc.module-conventions")
    alias(libs.plugins.shadow)
}

group = "com.amazonaws.sfc"
version = rootProject.extra.get("sfc_release")!!

sfcModule {
    buildConfigPackage = "uberjar"
    // sfc-main and sfc-uberjar name the constant MODULE_VERSION; adapters and targets use VERSION.
    versionConstant = "MODULE_VERSION"
}

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
}

// The plain jar holds only this module's generated BuildConfig and is not released (the shadow
// distribution below is). It still needs a classifier, because without one it would collide with
// the fat jar over the "sfc-uberjar-<version>.jar" name and break startScripts.
tasks.jar {
    archiveClassifier.set("thin")
}

// The single executable jar. Shadow resolves from runtimeClasspath, which carries the normal
// variant-aware attributes the old hand-rolled `mergedJar` configuration lacked - that
// configuration set no attributes at all and so fell back to the legacy `default` variant.
// This does NOT mean each module gets the versions it was compiled against: one flat jar can hold
// only one copy of a class, so newest-wins still applies across modules. It means the resolution is
// now the same one the per-module distributions use, and the repo keeps a single version per
// dependency in gradle/libs.versions.toml so that the two agree.
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

// This module releases the SHADOW distribution, not the main one. The shadow plugin registers a
// second distribution whose lib/ holds just the fat jar; the main distribution would instead ship
// the 3 KB thin jar next to 363 loose dependency jars. That difference is not cosmetic:
//   - it changes the shape of the published artifact (v1.11.0 and earlier shipped the fat jar),
//   - it generates a bin/sfc-uberjar.bat whose single `set CLASSPATH=` line is ~15,300 characters,
//     well past cmd.exe's 8,191-character limit, so the Windows launcher cannot run at all,
//   - and it puts 34 competing root log4j2.xml files on the classpath, so first-on-classpath wins
//     and the single deliberate config installed above is never read.
// So: disable the main distribution, and give the shadow tar the released name.
tasks.distTar {
    enabled = false
}

tasks.named<Zip>("shadowDistZip") {
    enabled = false
}

tasks.named<Tar>("shadowDistTar") {
    archiveBaseName = project.name
    compression = Compression.GZIP
    archiveExtension = "tar.gz"
    archiveFileName = "${project.name}.tar.gz"
}

// Add the shadow tar to the convention plugin's copyDist. from() is additive, but the main distTar
// it already points at is disabled above and so never produces a file, making this the only source.
tasks.named<Copy>("copyDist") {
    from(tasks.named<Tar>("shadowDistTar").flatMap { it.archiveFile })
}

tasks.named("build") {
    dependsOn("shadowDistTar")
}
