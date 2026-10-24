package com.ncmp.mobile.ui

import android.app.Application
import android.webkit.CookieManager
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.ncmp.mobile.data.NeteaseApi
import com.ncmp.mobile.data.SessionStore
import com.ncmp.mobile.data.TaskConfig
import com.ncmp.mobile.data.TaskResult
import com.ncmp.mobile.data.TaskRunner
import kotlinx.coroutines.launch

class AppViewModel(app: Application) : AndroidViewModel(app) {

    private val store = SessionStore(app)
    private val api = NeteaseApi()

    // ---------- 登录态 ----------
    var loggedIn by mutableStateOf(false)
        private set
    var nickname by mutableStateOf("")
        private set

    // ---------- Cookie 登录（粘贴） ----------
    var cookieMusicU by mutableStateOf("")
    var cookieCsrf by mutableStateOf("")
    var cookieError by mutableStateOf("")

    // ---------- 网页登录（WebView，官方登录弹窗） ----------
    var webError by mutableStateOf("")

    // ---------- 任务 ----------
    var running by mutableStateOf(false)
        private set
    var progressDone by mutableStateOf(0)
    var progressTotal by mutableStateOf(0)
    var currentSong by mutableStateOf("")
    var currentStep by mutableStateOf("")
    val logLines = mutableStateListOf<String>()
    var resultLabel by mutableStateOf("")
    var resultHint by mutableStateOf("")
    var resultIsError by mutableStateOf(false)
    private var runner: TaskRunner? = null

    // ---------- 配置（界面态） ----------
    var scoreStrategy by mutableStateOf(store.scoreStrategy)
    var waitMin by mutableStateOf(formatNum(store.waitMin))
    var waitMax by mutableStateOf(formatNum(store.waitMax))
    var fullExtra by mutableStateOf(store.fullExtra)

    init {
        loadSession()
    }

    private fun loadSession() {
        val musicU = store.musicU
        val csrf = store.csrf
        if (!musicU.isNullOrEmpty() && !csrf.isNullOrEmpty()) {
            api.musicU = musicU
            api.csrf = csrf
            loggedIn = true
            nickname = store.nickname ?: ""
        }
    }

    // ================= 登录 =================

    fun cookieLogin() {
        val musicU = cookieMusicU.trim()
        val csrf = cookieCsrf.trim()
        if (musicU.isEmpty() || csrf.isEmpty()) {
            cookieError = "请同时填写 MUSIC_U 和 __csrf"
            return
        }
        cookieError = ""
        onLoginSuccess(musicU, csrf, "网易云用户")
    }

    /** 从 WebView 的 CookieManager 提取 MUSIC_U / __csrf。 */
    fun extractCookieFromWebView() {
        val cm = CookieManager.getInstance()
        val urls = listOf(
            "https://music.163.com",
            "https://music.163.com/",
            "https://interface.music.163.com",
        )
        var musicU = ""
        var csrf = ""
        for (u in urls) {
            val cookieStr = cm.getCookie(u) ?: ""
            android.util.Log.e("ncmp", "getCookie($u) = [$cookieStr]")
            for (part in cookieStr.split(";")) {
                val idx = part.indexOf('=')
                if (idx > 0) {
                    val name = part.substring(0, idx).trim()
                    val value = part.substring(idx + 1).trim()
                    when (name) {
                        "MUSIC_U" -> if (musicU.isEmpty()) musicU = value
                        "__csrf" -> if (csrf.isEmpty()) csrf = value
                    }
                }
            }
        }
        if (musicU.isEmpty() || csrf.isEmpty()) {
            webError = "还没检测到登录态，请先在网页里完成登录"
            return
        }
        // 回填到「Cookie」标签的输入框，方便查看/复制
        cookieMusicU = musicU
        cookieCsrf = csrf
        // 验证 Cookie 是否真的有效，无效则不让进入
        webError = "正在验证登录态..."
        api.musicU = musicU
        api.csrf = csrf
        viewModelScope.launch {
            try {
                val nick = api.verifyUser()
                webError = ""
                onLoginSuccess(musicU, csrf, nick)
            } catch (e: Exception) {
                android.util.Log.e("ncmp", "verifyUser failed", e)
                webError = "Cookie 验证失败：${e.message}（请确认已在网页里登录）"
            }
        }
    }

    private fun onLoginSuccess(musicU: String, csrf: String, nick: String) {
        api.musicU = musicU
        api.csrf = csrf
        store.musicU = musicU
        store.csrf = csrf
        nickname = nick
        store.nickname = nick
        loggedIn = true
    }

    fun logout() {
        runner?.cancelled = true
        store.clear()
        api.musicU = null
        api.csrf = null
        loggedIn = false
        nickname = ""
        resultLabel = ""
        resultHint = ""
        resultIsError = false
        // 保留 cookieMusicU / cookieCsrf，方便在「Cookie」页查看上次获取的值
    }

    // ================= 配置 =================

    fun saveConfig() {
        val min = (waitMin.toFloatOrNull() ?: 15f).coerceAtLeast(0f)
        val max = (waitMax.toFloatOrNull() ?: 20f).coerceAtLeast(0f)
        store.scoreStrategy = scoreStrategy
        store.waitMin = min
        store.waitMax = max
        store.fullExtra = fullExtra
        waitMin = formatNum(min)
        waitMax = formatNum(max)
        appendLog("设置已保存")
    }

    // ================= 任务 =================

    fun runTask() {
        if (running) return
        val min = (waitMin.toDoubleOrNull() ?: 15.0).coerceAtLeast(0.0)
        val max = (waitMax.toDoubleOrNull() ?: 20.0).coerceAtLeast(0.0)
        if (max < min) {
            appendLog("等待上限不能小于下限，请检查设置")
            return
        }
        val cfg = TaskConfig(
            scoreStrategy = scoreStrategy,
            waitMinSeconds = min,
            waitMaxSeconds = max,
            fullExtraTasks = fullExtra,
        )

        running = true
        resultLabel = ""
        resultHint = ""
        resultIsError = false
        progressDone = 0
        progressTotal = 0
        currentSong = ""
        currentStep = ""
        logLines.clear()

        val r = TaskRunner(
            api = api,
            config = cfg,
            log = { appendLog(it) },
            onStep = { name, _ -> currentStep = name },
            onProgress = { done, total, song, _ ->
                progressDone = done
                progressTotal = total
                currentSong = song
            },
        )
        runner = r

        viewModelScope.launch {
            val result = r.run()
            running = false
            runner = null
            when (result) {
                is TaskResult.Success -> {
                    resultLabel = "任务完成"
                    resultIsError = false
                }
                is TaskResult.Cancelled -> {
                    resultLabel = "已取消"
                    resultIsError = false
                }
                is TaskResult.Failed -> {
                    resultLabel = "失败：${result.kind.label}"
                    resultHint = result.hint
                    resultIsError = true
                }
            }
        }
    }

    fun cancelTask() {
        runner?.cancelled = true
    }

    fun clearLog() {
        logLines.clear()
    }

    private fun appendLog(line: String) {
        logLines.add(line)
        while (logLines.size > 500) logLines.removeAt(0)
    }

    private fun formatNum(f: Float): String =
        if (f == f.toLong().toFloat()) f.toLong().toString() else f.toString()
}
