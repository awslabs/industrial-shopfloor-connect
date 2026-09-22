plugins {
    id("org.jetbrains.kotlin.jvm")
    id("idea")
    id("java")
}

repositories {
    mavenCentral()
}

val kotlinVersion = "2.4.20"

val junitVersion = "5.10.1"

dependencies {
    implementation("org.jetbrains.kotlin:kotlin-stdlib-jdk8:$kotlinVersion")

    testImplementation("org.junit.jupiter:junit-jupiter-api:$junitVersion")
    testImplementation("org.junit.jupiter:junit-jupiter:$junitVersion")

    testRuntimeOnly("org.junit.jupiter:junit-jupiter-engine:$junitVersion")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

// Milo 1.1.7 is compiled for Java 17 (bytecode major 61), so the whole
// product targets 17. The toolchain drives both the Java and Kotlin
// compilers; do not also set source/target compatibility or -source/-target
// compiler args, which would double-specify it.
kotlin {
    jvmToolchain(17)
}

tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile> {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        freeCompilerArgs.set(listOf("-opt-in=kotlin.time.ExperimentalTime", "-opt-in=kotlin.ExperimentalUnsignedTypes"))
    }
}

tasks.test {
    useJUnitPlatform()
    testLogging {
        events("passed", "skipped", "failed")
    }
}
