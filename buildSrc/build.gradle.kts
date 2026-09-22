plugins {
    // `kotlin-dsl` applies the Kotlin JVM plugin using Gradle's *embedded* Kotlin
    // (2.4.0 on Gradle 9.7.1). Do not also declare `kotlin("jvm") version "..."`
    // here: pinning a different compiler than the embedded one is a known
    // kotlin-dsl/KGP mismatch footgun.
    `kotlin-dsl`
}

repositories {
    mavenCentral()
    gradlePluginPortal()
}

dependencies {
    // This is the Kotlin version used to compile the production modules, and it
    // may legitimately be newer than Gradle's embedded Kotlin.
    implementation("org.jetbrains.kotlin:kotlin-gradle-plugin:2.4.20")
}
