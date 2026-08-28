package com.runwill.hantonom

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.core.content.FileProvider
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class MainActivity : Activity() {
    companion object { private const val FILE_CHOOSER_REQUEST = 4102 }

    private lateinit var webView: WebView
    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private val backendReady = CountDownLatch(1)
    @Volatile private var backendError: String? = null

    @SuppressLint("SetJavaScriptEnabled", "JavascriptInterface")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val darkTheme = prefersDarkTheme()
        val startupBackground = if (darkTheme) Color.rgb(29, 34, 38) else Color.rgb(244, 246, 248)
        window.navigationBarColor = startupBackground
        hideSystemStatusBar()

        webView = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = true
            settings.allowContentAccess = false
            settings.setSupportZoom(false)
            webViewClient = WebViewClient()
            webChromeClient = object : WebChromeClient() {
                override fun onShowFileChooser(
                    webView: WebView,
                    filePathCallback: ValueCallback<Array<Uri>>,
                    fileChooserParams: FileChooserParams,
                ): Boolean {
                    this@MainActivity.filePathCallback?.onReceiveValue(null)
                    this@MainActivity.filePathCallback = filePathCallback
                    val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                        addCategory(Intent.CATEGORY_OPENABLE)
                        type = "application/json"
                    }
                    startActivityForResult(intent, FILE_CHOOSER_REQUEST)
                    return true
                }
            }
            addJavascriptInterface(AndroidApi(this@MainActivity), "AndroidApi")
            setBackgroundColor(startupBackground)
        }
        setContentView(webView)
        webView.loadUrl("file:///android_asset/web/index.html?theme=${if (darkTheme) "dark" else "light"}")

        Thread {
            try {
                copyBootstrapData("base.json.gz")
                copyBootstrapData("extra.json.gz")
                if (!Python.isStarted()) Python.start(AndroidPlatform(this))
                Python.getInstance().getModule("android_bridge")
                    .callAttr("initialize", filesDir.absolutePath)
            } catch (error: Throwable) {
                backendError = error.stackTraceToString()
            } finally {
                backendReady.countDown()
            }
        }.start()
    }

    private fun prefersDarkTheme(): Boolean {
        val saved = runCatching {
            File(filesDir, ".theme_pref").takeIf { it.isFile }
                ?.readText(Charsets.UTF_8)?.trim()
        }.getOrNull()
        if (saved == "dark") return true
        if (saved == "light") return false
        return resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK ==
            Configuration.UI_MODE_NIGHT_YES
    }

    override fun onResume() {
        super.onResume()
        hideSystemStatusBar()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemStatusBar()
    }

    @Suppress("DEPRECATION")
    private fun hideSystemStatusBar() {
        runCatching {
            window.addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN)
            window.clearFlags(WindowManager.LayoutParams.FLAG_FORCE_NOT_FULLSCREEN)
            window.decorView.systemUiVisibility =
                View.SYSTEM_UI_FLAG_FULLSCREEN or
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
        }
    }

    private fun copyBootstrapData(filename: String) {
        val target = File(filesDir, filename)
        if (target.isFile && target.length() > 0L) return
        val temporary = File(filesDir, "$filename.tmp")
        assets.open("bootstrap/$filename.bin").use { input ->
            temporary.outputStream().use { output -> input.copyTo(output) }
        }
        if (!temporary.renameTo(target)) {
            temporary.copyTo(target, overwrite = true)
            temporary.delete()
        }
    }

    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        webView.evaluateJavascript(
            "Boolean(window.handleAndroidBack && window.handleAndroidBack())"
        ) { handled ->
            if (handled != "true") super.onBackPressed()
        }
    }

    @Deprecated("Used for the WebView file chooser on API 24+")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == FILE_CHOOSER_REQUEST) {
            val result = if (resultCode == RESULT_OK) {
                WebChromeClient.FileChooserParams.parseResult(resultCode, data)
            } else {
                null
            }
            filePathCallback?.onReceiveValue(result)
            filePathCallback = null
            return
        }
        super.onActivityResult(requestCode, resultCode, data)
    }

    override fun onDestroy() {
        filePathCallback?.onReceiveValue(null)
        filePathCallback = null
        webView.removeJavascriptInterface("AndroidApi")
        webView.destroy()
        super.onDestroy()
    }

    private inner class AndroidApi(private val activity: Activity) {
        private val allowedSourceUrls = setOf(
            "https://zhuanlan.zhihu.com/p/12987993957",
            "https://github.com/qwert-ly/xtext",
            "https://space.bilibili.com/129368153",
            "https://space.bilibili.com/87432837",
        )

        @JavascriptInterface
        fun invokeAsync(requestId: String, method: String, argumentsJson: String) {
            Thread {
                val response = invoke(method, argumentsJson)
                activity.runOnUiThread {
                    webView.evaluateJavascript(
                        "window.__resolveAndroidApi(" +
                            JSONObject.quote(requestId) + "," +
                            JSONObject.quote(response) + ")",
                        null,
                    )
                }
            }.start()
        }

        @JavascriptInterface
        fun invoke(method: String, argumentsJson: String): String {
            if (method == "get_backend_readiness") {
                return success(JSONObject()
                    .put("ready", backendReady.count == 0L && backendError == null)
                    .put("error", backendError ?: JSONObject.NULL))
            }
            if (!backendReady.await(40, TimeUnit.SECONDS)) {
                return failure("Android 后端启动超时")
            }
            backendError?.let { return failure("Android 后端启动失败", it) }
            return try {
                when (method) {
                    "restart_app" -> {
                        activity.runOnUiThread { recreate() }
                        success(JSONObject.NULL)
                    }
                    "open_releases_page" -> {
                        openUrl("https://github.com/Runwill/ancient-chinese/releases")
                        success(JSONObject().put("ok", true))
                    }
                    "open_source_url" -> {
                        val url = JSONArray(argumentsJson).optString(0)
                        if (url !in allowedSourceUrls) throw IllegalArgumentException("未知的数据源地址")
                        openUrl(url)
                        success(JSONObject().put("ok", true))
                    }
                    "install_downloaded_update" -> installDownloadedUpdate(argumentsJson)
                    "open_location" -> failure("Android 不支持直接打开应用内部目录，请使用备份导出")
                    else -> Python.getInstance().getModule("android_bridge")
                        .callAttr("invoke", method, argumentsJson).toString()
                }
            } catch (error: Throwable) {
                failure(error.message ?: error.javaClass.simpleName, error.stackTraceToString())
            }
        }

        private fun openUrl(url: String) {
            activity.runOnUiThread {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            }
        }

        private fun installDownloadedUpdate(argumentsJson: String): String {
            val validated = Python.getInstance().getModule("android_bridge")
                .callAttr("invoke", "install_downloaded_update", argumentsJson).toString()
            val envelope = JSONObject(validated)
            if (!envelope.optBoolean("ok")) return validated
            val value = envelope.optJSONObject("value")
                ?: throw IllegalStateException("更新校验结果无效")
            val path = value.optString("path")
            val apk = File(path).canonicalFile
            val updates = File(activity.filesDir, "updates").canonicalFile
            if (!apk.isFile || apk.parentFile != updates || apk.extension.lowercase() != "apk") {
                throw IllegalArgumentException("更新包路径无效")
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
                !activity.packageManager.canRequestPackageInstalls()) {
                activity.runOnUiThread {
                    startActivity(Intent(
                        Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:${activity.packageName}"),
                    ))
                }
                value.put("permission_required", true)
                return success(value)
            }
            val uri = FileProvider.getUriForFile(
                activity, "${activity.packageName}.updates", apk)
            activity.runOnUiThread {
                startActivity(Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(uri, "application/vnd.android.package-archive")
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                })
            }
            value.put("installer_opened", true)
            return success(value)
        }

        private fun success(value: Any): String = JSONObject()
            .put("ok", true)
            .put("value", value)
            .toString()

        private fun failure(message: String, details: String = ""): String = JSONObject()
            .put("ok", false)
            .put("error", message)
            .put("details", details)
            .toString()
    }
}
