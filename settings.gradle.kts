// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

rootProject.name = "sfc"

pluginManagement {

    // Runs a command and returns its stdout, or null when it cannot be run or fails.
    //
    // This deliberately does NOT throw on stderr output. The previous version did, which made the
    // release version unresolvable in three situations that all matter:
    //
    //   - a shallow clone (CI defaults to depth 1) fetches no tags, so `git describe` writes
    //     "fatal: No names found, cannot describe anything" and the build died during settings
    //     evaluation, before any task could run;
    //   - a source archive with no .git directory at all - which is how the integration test ships
    //     the working tree, uncommitted changes included - has no git metadata to read;
    //   - a checkout owned by another uid makes git emit a "detected dubious ownership" warning on
    //     stderr while still succeeding, which was enough to abort the build.
    //
    // Exit status is the only reliable signal, so that is what is checked.
    fun String.runCommandOrNull(
        workingDir: File = File("."),
        timeoutAmount: Long = 60,
        timeoutUnit: TimeUnit = TimeUnit.SECONDS
    ): String? = try {
        val process = ProcessBuilder(split("\\s(?=(?:[^'\"`]*(['\"`])[^'\"`]*\\1)*[^'\"`]*$)".toRegex()))
            .directory(workingDir)
            .redirectOutput(ProcessBuilder.Redirect.PIPE)
            .redirectError(ProcessBuilder.Redirect.PIPE)
            .start()
        // Read stdout before waiting: a command that fills the pipe buffer would otherwise block
        // forever and only be released by the timeout.
        val output = process.inputStream.bufferedReader().readText().trim()
        process.errorStream.bufferedReader().readText()
        if (!process.waitFor(timeoutAmount, timeoutUnit)) {
            process.destroyForcibly()
            null
        } else if (process.exitValue() != 0 || output.isEmpty()) {
            null
        } else {
            output
        }
    } catch (_: Exception) {
        // git missing from PATH, no execute permission, and anything else environmental.
        null
    }

    // Used when there is no git metadata to derive a version from. Any non-empty string works -
    // it only ends up in artifact names and in BuildConfig - but it should be obviously not a release.
    val fallbackVersion = "0.0.0-dev"

    // Precedence: explicit override, then the nearest git tag, then the fallback.
    //
    // SFC_VERSION exists so a build with no usable git metadata can still be given the right version,
    // and so a CI job can pin one deliberately rather than inherit whatever tag the branch sits on.
    val versionFromGit =
        System.getenv("SFC_VERSION")?.trim()?.takeIf { it.isNotEmpty() }
            ?: "git describe --tags --abbrev=0".runCommandOrNull(workingDir = rootDir)
            ?: fallbackVersion

    // removePrefix rather than replace("v", ""): the original stripped EVERY "v" in the tag, so a
    // tag such as "v1.2.0-preview" became "1.2.0-preiew". Identical for plain vX.Y.Z tags.
    (gradle as ExtensionAware).extensions.extraProperties.set("versionFromGit", versionFromGit.removePrefix("v"))
}

//-----------------//

plugins {
    id("org.gradle.toolchains.foojay-resolver-convention") version "0.7.0"
}

// "ci" holds support code for the end-to-end suite (ci/e2e-support). Those modules use
// sfc.kotlin-library-conventions, not sfc.module-conventions, so they build a plain jar and add
// nothing to build/distribution - the release globs build/distribution/*.tar.gz and the tarball set
// must stay exactly as it is.
listOf("core", "metrics", "adapters", "targets", "examples", "ci").forEach { p ->
    File("$rootDir/$p/").listFiles()?.forEach {
        if (it.isDirectory && File(it, "build.gradle.kts").exists()) {
            include(":${p}:${it.name}")
        }
    }
}


