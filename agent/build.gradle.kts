// AGP 9.2.1 + Kotlin 2.2.10。gradle.properties 已设 android.builtInKotlin=false
// 禁用 AGP 内置 Kotlin,改用传统 org.jetbrains.kotlin.android plugin。
plugins {
    id("com.android.application") version "9.2.1" apply false
    id("org.jetbrains.kotlin.android") version "2.2.10" apply false
}
