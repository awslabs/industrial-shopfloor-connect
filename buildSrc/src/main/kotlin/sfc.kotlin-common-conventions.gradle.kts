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

// The product targets Java 17 and is built by whatever JDK runs Gradle, 17 or newer. --release and
// -Xjdk-release compile against the Java 17 API, so a newer JDK cannot leak newer API calls into the
// product. No toolchain is requested, so nothing is downloaded.
java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17 // must match Kotlin's jvmTarget
}

tasks.withType<JavaCompile>().configureEach {
    options.release.set(17)
}

tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile> {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        freeCompilerArgs.set(listOf("-Xjdk-release=17",
            "-opt-in=kotlin.time.ExperimentalTime", "-opt-in=kotlin.ExperimentalUnsignedTypes"))
    }
}

tasks.test {
    useJUnitPlatform()
    testLogging {
        events("passed", "skipped", "failed")
    }
}
