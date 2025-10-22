plugins {
    id("org.jetbrains.kotlin.jvm")
    id("idea")
    id("java")
}

repositories {
    mavenCentral()
}

val kotlinVersion = "2.2.0"

val jvmTarget = "1.8"
val junitVersion = "5.10.1"

dependencies {
    implementation("org.jetbrains.kotlin:kotlin-stdlib-jdk8:$kotlinVersion")

    testImplementation("org.junit.jupiter:junit-jupiter-api:$junitVersion")
    testImplementation("org.junit.jupiter:junit-jupiter:$junitVersion")

    testRuntimeOnly("org.junit.jupiter:junit-jupiter-engine:$junitVersion")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

kotlin{
    jvmToolchain(8)
}

tasks.compileJava {
    sourceCompatibility = jvmTarget
    targetCompatibility = jvmTarget
}

tasks.compileTestJava {
    sourceCompatibility = jvmTarget
    targetCompatibility = jvmTarget
}

tasks.withType<JavaCompile> {
    options.compilerArgs.addAll(listOf("-source", jvmTarget, "-target",  jvmTarget))
}

tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile> {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_1_8)
        freeCompilerArgs.set(listOf("-opt-in=kotlin.time.ExperimentalTime", "-opt-in=kotlin.ExperimentalUnsignedTypes"))
    }
}
tasks.test {
    useJUnitPlatform()
    testLogging {
        events("passed", "skipped", "failed")
    }
}
