
group = "com.amazonaws.sfc"
version = "1.0.0"

val sfcRelease = rootProject.extra.get("sfc_release")!!
val sfcCoreVersion = sfcRelease
plugins {
    java
    id("sfc.kotlin-library-conventions")
    `maven-publish`
}

repositories {
    mavenCentral()
}

dependencies {
    implementation(project(":core:sfc-core"))
    implementation(libs.kotlin.stdlib.jdk8)
    implementation(libs.kotlinx.coroutines.core)
    implementation(libs.jna)
    implementation(libs.jnaerator.runtime)
}

publishing {
    publications {
        create<MavenPublication>("maven") {
            from(components["kotlin"])
            groupId = group as String
            artifactId = "canbus"
            version = version
        }
    }

}

tasks.build {
    finalizedBy(tasks.publishToMavenLocal)
}

//
//tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile> {
//    compilerOptions {
//        jvmTarget = "18"
//        freeCompilerArgs += listOf(
////            "-Xuse-ir",
//            "-Xskip-prerelease-check",
//            "-Xno-param-assertions",
//            "-Xno-call-assertions"
//        )
//    }
//}
//tasks.test {
//    useJUnitPlatform()
//}
//kotlin {
//
//    jvmToolchain(18)
//
//}
//java{
//    sourceCompatibility = JavaVersion.VERSION_18
//    targetCompatibility = JavaVersion.VERSION_18
//}