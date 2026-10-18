buildscript {
    dependencies {
        // Coil 3.5 is compiled with Kotlin 2.4.
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.4.10")
    }
}

plugins {
    id("com.android.application") version "9.2.0" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.4.10" apply false
}
