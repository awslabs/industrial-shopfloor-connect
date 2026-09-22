group = "com.amazonaws.sfc"

version = "1.0.0"
plugins {

    java

    id("sfc.kotlin-library-conventions")
}

dependencies {

    implementation(project(":core:sfc-core"))
    implementation(libs.kotlinx.coroutines.core)

}

