// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Everything a deployable SFC module (adapter, target, metrics writer, sfc-main, uberjar) shares:
// the Kotlin application setup, the distribution tail and its generated BuildConfig.
plugins {
    id("sfc.kotlin-application-conventions")
    id("sfc.dist-conventions")
}

val sfcModule = extensions.create<SfcModuleExtension>("sfcModule")
sfcModule.versionConstant.convention("VERSION")

val sfcRelease = rootProject.extra.get("sfc_release").toString()

val generateBuildConfig = tasks.register<GenerateBuildConfig>("generateBuildConfig") {
    packageName = sfcModule.buildConfigPackage.map { "com.amazonaws.sfc.$it" }
    versionConstant = sfcModule.versionConstant
    extraVersions = sfcModule.extraVersions
    coreVersion = sfcRelease
    ipcVersion = sfcRelease
    // Lazy: the module scripts assign `version` in their body, which runs after this plugin applies.
    moduleVersion = provider { project.version.toString() }
    moduleLabel = project.name.uppercase()
    outputDir = layout.buildDirectory.dir("generated/sources/buildConfig/kotlin/main")
}

// Registering the task provider, not a bare path, is what gives compileKotlin its dependency on the
// generator. The old scripts hung generateBuildConfig off `build`, far too late for a source file
// that compileKotlin has to read, and got away with it only because the generation actually happened
// during configuration.
kotlin.sourceSets["main"].kotlin.srcDir(generateBuildConfig)
