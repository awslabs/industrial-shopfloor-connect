// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// The tar.gz + copyDist tail that every released module shared. Applying `application` here (rather
// than sfc.kotlin-application-conventions) is what lets the examples/ modules keep java-library.
plugins {
    application
}

// distZip is never released - the release workflow globs build/distribution/*.tar.gz only - and for
// the heavier modules it is a ~100 MB zip built and thrown away on every run.
tasks.distZip {
    enabled = false
}

// applicationName, and with it the archive root directory and the bin/ script name, already default
// to project.name; only the archive file name has to be pinned, so that it carries no version.
tasks.distTar {
    archiveBaseName = project.name
    compression = Compression.GZIP
    archiveExtension = "tar.gz"
    archiveFileName = "${project.name}.tar.gz"
}

val copyDist = tasks.register<Copy>("copyDist") {
    description = "Collects this module's distribution tarball into the release directory"
    // Taking the producing task's output file, rather than scanning build/distributions, is what
    // gives Gradle the producer -> consumer edge. Scanning the directory left copyDist with an
    // undeclared dependency on distTar, so `gradlew distTar copyDist` failed outright and only
    // `build`'s finalizedBy ordering made the normal path work by accident.
    from(tasks.distTar.flatMap { it.archiveFile })
    // Addressed through rootProject instead of the old "../../../build/distribution/", which
    // silently assumed every module sits exactly two directories below the root.
    into(rootProject.layout.buildDirectory.dir("distribution"))
}

tasks.named("build") {
    finalizedBy(copyDist)
}
