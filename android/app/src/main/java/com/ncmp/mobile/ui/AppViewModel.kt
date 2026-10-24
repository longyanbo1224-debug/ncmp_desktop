package com.ncmp.mobile.ui

import android.app.Application
import android.content.Intent
import android.webkit.CookieManager
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.ncmp.mobile.TaskService
import com.ncmp.mobile.data.AlarmScheduler
import com.ncmp.mobile.data.HistoryEntry
import com.ncmp.mobile.data.NeteaseApi
import com.ncmp.mobile.data.SessionStore
import com.ncmp.mobile.data.TaskBus
import com.ncmp.mobile.data.TaskHistoryStore
import kotlinx.coroutines.launch

class AppViewModel(app: Application) : AndroidViewModel(app) {

    private val store = SessionStore(app)
    private val historyStore = TaskHistoryStore(app)
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

    // ---------- 任务（镜像自 TaskBus） ----------
    var running by mutableStateOf(false)
        private set
    var progressDone by mutableStateOf(0)
    var progressTotal by mutableStateOf(0)
    var currentSong by mutableStateOf("")
    var currentScore by mutableStateOf("")
    var currentStep by mutableStateOf("")
    val logLines = mutableStateListOf<String>()
    var resultLabel by mutableStateOf("")
    var resultHint by mutableStateOf("")
    var resultIsError by mutableStateOf(false)

    // ---------- 配置（界面态） ----------
    var scoreStrategy by mutableStateOf(store.scoreStrategy)
    var waitMin by mutableStateOf(formatNum(store.waitMin))
    var waitMax by mutableStateOf(formatNum(store.waitMax))
    var fullExtra by mutableStateOf(store.fullExtra)

    var scheduleEnabled by mutableStateOf(store.scheduleEnabled)
    var scheduleTimeText by mutableStateOf("%02d:%02d".format(store.scheduleHour, store.scheduleMinute))

    val history = mutableStateListOf<HistoryEntry>()

    init {
        loadSession()
        observeTaskBus()
        refreshHistory()
    }

    fun refreshHistory() {
        history.clear()
        history.addAll(historyStore.load())
    }

    private fun observeTaskBus() {
        viewModelScope.launch { TaskBus.running.collect { running = it } }
        viewModelScope.launch {
            TaskBus.logs.collect { lines ->
                logLines.clear()
                logLines.addAll(lines)
            }
        }
        viewModelScope.launch { TaskBus.done.collect { progressDone = it } }
        viewModelScope.launch { TaskBus.total.collect { progressTotal = it } }
        viewModelScope.launch { TaskBus.song.collect { currentSong = it } }
        viewModelScope.launch { TaskBus.score.collect { currentScore = it } }
        viewModelScope.launch { TaskBus.step.collect { currentStep = it } }
        viewModelScope.launch { TaskBus.resultLabel.collect { resultLabel = it } }
        viewModelScope.launch { TaskBus.resultHint.collect { resultHint = it } }
        viewModelScope.launch { TaskBus.resultIsError.collect { resultIsError = it } }
    }

    private fun loadSession() {
        val musicU = store.musicU
        val csrf = store.csrf
        if (!musicU.isNullOrEmpty() && !csrf.isNullOrEmpty()) {
            api.musicU = musicU
            api.csrf = csrf
            loggedIn = true
            nickname = store.nickname ?: ""
            // 后台刷新昵称：存储里的可能是占位（旧版 cookieLogin 写的「网易云用户」）
            viewModelScope.launch {
                try {
                    val nick = api.verifyUser()
                    if (nick.isNotEmpty()) {
                        nickname = nick
                        store.nickname = nick
                    }
                } catch (_: Exception) {
                }
            }
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
        cookieError = "正在验证登录态..."
        api.musicU = musicU
        api.csrf = csrf
        viewModelScope.launch {
            try {
                // 用真实昵称，而不是「网易云用户」占位
                val nick = api.verifyUser()
                cookieError = ""
                onLoginSuccess(musicU, csrf, nick)
            } catch (e: Exception) {
                cookieError = "Cookie 验证失败：${e.message}"
            }
        }
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
        cookieMusicU = musicU
        cookieCsrf = csrf
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
        val (h, m) = parseTime(scheduleTimeText) ?: (9 to 0)
        store.fullExtra = fullExtra
        store.scheduleEnabled = scheduleEnabled
        store.scheduleHour = h
        store.scheduleMinute = m
        val app = getApplication<Application>()
        if (scheduleEnabled) {
            AlarmScheduler.schedule(app, h, m)
        } else {
            AlarmScheduler.cancel(app)
        }
        waitMin = formatNum(min)
        waitMax = formatNum(max)
        scheduleTimeText = "%02d:%02d".format(h, m)
        TaskBus.append(
            if (scheduleEnabled) "设置已保存，定时：%02d:%02d".format(h, m)
            else "设置已保存",
        )
    }

    // ================= 任务（交给前台服务在后台跑） =================

    fun runTask() {
        if (running) return
        val min = (waitMin.toDoubleOrNull() ?: 15.0).coerceAtLeast(0.0)
        val max = (waitMax.toDoubleOrNull() ?: 20.0).coerceAtLeast(0.0)
        if (max < min) {
            TaskBus.append("等待上限不能小于下限，请检查设置")
            return
        }
        val app = getApplication<Application>()
        val intent = Intent(app, TaskService::class.java).apply {
            putExtra(TaskService.EXTRA_SCORE, scoreStrategy)
            putExtra(TaskService.EXTRA_WAIT_MIN, min)
            putExtra(TaskService.EXTRA_WAIT_MAX, max)
            putExtra(TaskService.EXTRA_FULL_EXTRA, fullExtra)
        }
        ContextCompat.startForegroundService(app, intent)
    }

    fun cancelTask() {
        val app = getApplication<Application>()
        val intent = Intent(app, TaskService::class.java).apply {
            action = TaskService.ACTION_CANCEL
        }
        try {
            app.startService(intent)
        } catch (_: Exception) {
        }
    }

    fun clearLog() {
        TaskBus.logs.value = emptyList()
    }

    private fun formatNum(f: Float): String =
        if (f == f.toLong().toFloat()) f.toLong().toString() else f.toString()

    private fun parseTime(s: String): Pair<Int, Int>? {
        val parts = s.trim().split(":")
        if (parts.size != 2) return null
        val h = parts[0].trim().toIntOrNull() ?: return null
        val m = parts[1].trim().toIntOrNull() ?: return null
        if (h !in 0..23 || m !in 0..59) return null
        return h to m
    }
}
