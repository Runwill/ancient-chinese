import org.gradle.api.tasks.Sync
import org.gradle.api.GradleException

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val repositoryRoot = rootProject.projectDir.parentFile
val generatedPython = layout.buildDirectory.dir("generated/python")
val generatedAssets = layout.buildDirectory.dir("generated/assets")
val versionSource = repositoryRoot.resolve("app_version.py").readText()
val appVersion = Regex("__version__\\s*=\\s*['\"]([^'\"]+)['\"]")
    .find(versionSource)?.groupValues?.get(1)
    ?: throw GradleException("Unable to read __version__ from app_version.py")
val versionParts = appVersion.split(".").map { it.toInt() }
val appVersionCode = versionParts.getOrElse(0) { 0 } * 10000 +
    versionParts.getOrElse(1) { 0 } * 100 + versionParts.getOrElse(2) { 0 }
val releaseKeystore = System.getenv("HAN_NOCM_KEYSTORE")
val releaseStorePassword = System.getenv("HAN_NOCM_STORE_PASSWORD")
val releaseKeyAlias = System.getenv("HAN_NOCM_KEY_ALIAS")
val releaseKeyPassword = System.getenv("HAN_NOCM_KEY_PASSWORD")
val releaseRequested = gradle.startParameter.taskNames.any {
    it.contains("release", ignoreCase = true)
}
if (releaseRequested && listOf(
        releaseKeystore, releaseStorePassword, releaseKeyAlias, releaseKeyPassword
    ).any { it.isNullOrBlank() }) {
    throw GradleException(
        "Release signing is not configured. Set HAN_NOCM_KEYSTORE, " +
            "HAN_NOCM_STORE_PASSWORD, HAN_NOCM_KEY_ALIAS and HAN_NOCM_KEY_PASSWORD."
    )
}

val pythonModules = listOf(
    "android_bridge.py",
    "app_version.py",
    "atomic_io.py",
    "backup_manager.py",
    "constants.py",
    "data_loader.py",
    "draft_io.py",
    "editor_buffer.py",
    "folder_manager.py",
    "library_import.py",
    "nocm_phonology.py",
    "nocm_transcriber.py",
    "runtime_log.py",
    "update_manager.py",
    "web_api.py",
)

val syncPython by tasks.registering(Sync::class) {
    from(repositoryRoot) { include(pythonModules) }
    into(generatedPython)
}

val syncAndroidAssets by tasks.registering(Sync::class) {
    inputs.property("assetNamingVersion", 2)
    into(generatedAssets)
    from(repositoryRoot.resolve("web")) { into("web") }
    from(repositoryRoot) {
        include("base.json.gz", "extra.json.gz")
        rename { "$it.bin" }
        into("bootstrap")
    }
}

android {
    namespace = "com.runwill.hantonom"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.runwill.hantonom"
        minSdk = 24
        targetSdk = 35
        versionCode = appVersionCode
        versionName = appVersion

        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    sourceSets.getByName("main") {
        assets.srcDir(generatedAssets)
    }

    signingConfigs {
        if (!releaseKeystore.isNullOrBlank()) {
            create("release") {
                storeFile = file(releaseKeystore)
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    androidResources { noCompress += "bin" }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

chaquopy {
    defaultConfig { version = "3.11" }
    sourceSets.getByName("main").srcDir(generatedPython)
}

tasks.named("preBuild") {
    dependsOn(syncPython, syncAndroidAssets)
}

tasks.matching { it.name.startsWith("merge") && it.name.endsWith("PythonSources") }
    .configureEach { dependsOn(syncPython) }
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("Assets") }
    .configureEach { dependsOn(syncAndroidAssets) }

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
}
