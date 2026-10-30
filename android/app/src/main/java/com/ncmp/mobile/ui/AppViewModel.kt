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
import com.ncmp.mobile.data.Notes
import com.ncmp.mobile.data.SessionStore
import com.ncmp.mobile.data.TaskBus
import com.ncmp.mobile.data.TaskHistoryStore
import com.ncmp.mobile.data.TrackItem
import kotlinx.coroutines.launch

class AppViewModel(app: Application) : AndroidViewModel(app) {

    private val store = SessionStore(app)
    private val historyStore = TaskHistoryStore(app)
    private val trackLog = com.ncmp.mobile.data.TrackLogStore(app)
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

    /** 全局进度 0~100，跨「基础 / 额外」两个阶段连续推进。 */
    var percent by mutableStateOf(0)
    var currentSong by mutableStateOf("")
    var currentScore by mutableStateOf("")
    var currentStep by mutableStateOf("")
    val logLines = mutableStateListOf<String>()
    var resultLabel by mutableStateOf("")
    var resultHint by mutableStateOf("")
    var resultSummary by mutableStateOf("")
    var resultIsError by mutableStateOf(false)

    // ---------- 配置（界面态） ----------
    var scoreStrategy by mutableStateOf(store.scoreStrategy)
    var waitMin by mutableStateOf(formatNum(store.waitMin))
    var waitMax by mutableStateOf(formatNum(store.waitMax))
    var fullExtra by mutableStateOf(store.fullExtra)

    // 批注（乐评文案）
    var noteEnabled by mutableStateOf(store.noteEnabled)
    var noteVoice by mutableStateOf(store.noteVoice)
    var noteMaxChars by mutableStateOf(store.noteMaxChars)

    /** 今日曲目表：今天评了哪几首、每首几分、留下了什么批注。 */
    var tracks by mutableStateOf<List<TrackItem>>(emptyList())
        private set

    var scheduleEnabled by mutableStateOf(store.scheduleEnabled)
    var scheduleTimeText by mutableStateOf("%02d:%02d".format(store.scheduleHour, store.scheduleMinute))

    val history = mutableStateListOf<HistoryEntry>()

    /** 记录页的汇总与最近曲目（来自按曲目的本地记录）。 */
    var trackStats by mutableStateOf(com.ncmp.mobile.data.TrackStats())
        private set
    var recentTracks by mutableStateOf<List<com.ncmp.mobile.data.TrackRecord>>(emptyList())
        private set
    /** 合伙人积分/等级；没查到就是空 Map（界面不显示）。 */
    var points by mutableStateOf<Map<String, String>>(emptyMap())
        private set

    init {
        loadSession()
        observeTaskBus()
        refreshHistory()
        // 启动时恢复定时闹钟（被系统清理/强杀后重新安排）
        if (store.scheduleEnabled) {
            AlarmScheduler.schedule(app, store.scheduleHour, store.scheduleMinute)
        }
    }

    fun refreshHistory() {
        history.clear()
        history.addAll(historyStore.load())
        trackStats = trackLog.stats()
        recentTracks = trackLog.recent(20)
        if (points.isEmpty()) points = readPoints()
    }

    /** 手动刷新合伙人积分/等级（记录页的「刷新」）。拿不到就保持原值。 */
    fun refreshPoints() {
        viewModelScope.launch {
            val fresh = runCatching { api.getPartnerPoints() }.getOrNull()
            if (!fresh.isNullOrEmpty()) {
                points = fresh
                store.partnerPoints = org.json.JSONObject(fresh).toString()
            }
        }
    }

    /** 从本地缓存恢复上次查到的积分/等级（JSON → Map）。 */
    private fun readPoints(): Map<String, String> = try {
        val raw = store.partnerPoints
        if (raw.isBlank()) emptyMap() else {
            val obj = org.json.JSONObject(raw)
            val keys = obj.keys()
            val result = mutableMapOf<String, String>()
            while (keys.hasNext()) {
                val key = keys.next()
                result[key] = obj.optString(key)
            }
            result
        }
    } catch (_: Exception) {
        emptyMap()
    }

    private fun observeTaskBus() {
        viewModelScope.launch {
            TaskBus.running.collect {
                running = it
                // 服务端先落记录再置 false，所以这时读到的就是本次结果
                if (!it) refreshHistory()
            }
        }
        viewModelScope.launch {
            TaskBus.logs.collect { lines ->
                logLines.clear()
                logLines.addAll(lines)
            }
        }
        viewModelScope.launch { TaskBus.done.collect { progressDone = it } }
        viewModelScope.launch { TaskBus.total.collect { progressTotal = it } }
        viewModelScope.launch { TaskBus.percent.collect { percent = it } }
        viewModelScope.launch { TaskBus.song.collect { currentSong = it } }
        viewModelScope.launch { TaskBus.score.collect { currentScore = it } }
        viewModelScope.launch { TaskBus.step.collect { currentStep = it } }
        viewModelScope.launch { TaskBus.resultLabel.collect { resultLabel = it } }
        viewModelScope.launch { TaskBus.resultHint.collect { resultHint = it } }
        viewModelScope.launch { TaskBus.resultSummary.collect { resultSummary = it } }
        viewModelScope.launch { TaskBus.resultIsError.collect { resultIsError = it } }
        viewModelScope.launch { TaskBus.tracks.collect { tracks = it } }
        viewModelScope.launch {
            TaskBus.points.collect { if (it.isNotEmpty()) points = it }
        }
    }

    private fun loadSession() {
        val musicU = store.musicU
        val csrf = store.csrf
        if (!musicU.isNullOrEmpty() && !csrf.isNullOrEmpty()) {
            // 登录态来自存储时也要把值填进「Cookie」页的输入框，
            // 否则直接退出登录后去看那一页会是空的（只有网页登录流程才会填）。
            cookieMusicU = musicU
            cookieCsrf = csrf
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
        // 退出前先把当前登录态写回输入框：用户退出后常去「Cookie」页核对上次的值，
        // 这时候界面必须还看得见 MUSIC_U / __csrf（否则一片空白）。
        val lastMusicU = api.musicU ?: store.musicU
        val lastCsrf = api.csrf ?: store.csrf
        if (!lastMusicU.isNullOrEmpty()) cookieMusicU = lastMusicU
        if (!lastCsrf.isNullOrEmpty()) cookieCsrf = lastCsrf
        store.clearAuth()
        api.musicU = null
        api.csrf = null
        loggedIn = false
        nickname = ""
        resultLabel = ""
        resultHint = ""
        resultIsError = false
        // cookieMusicU / cookieCsrf 刻意保留，方便在「Cookie」页查看上次获取的值
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
        store.noteEnabled = noteEnabled
        store.noteVoice = Notes.normalizeVoice(noteVoice)
        store.noteMaxChars = noteMaxChars.coerceIn(10, 200)
        noteVoice = Notes.normalizeVoice(noteVoice)
        noteMaxChars = noteMaxChars.coerceIn(10, 200)
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
        // 批注设置即时生效：开始评分前落盘，保证前台服务读到的是界面上看到的值
        // （note_source 不在这里改：手机端没有 LLM，生成器自己按 template 处理）
        store.noteEnabled = noteEnabled
        store.noteVoice = Notes.normalizeVoice(noteVoice)
        store.noteMaxChars = noteMaxChars.coerceIn(10, 200)
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
