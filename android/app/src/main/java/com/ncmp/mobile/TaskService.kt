package com.ncmp.mobile

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import com.ncmp.mobile.data.HistoryEntry
import com.ncmp.mobile.data.NeteaseApi
import com.ncmp.mobile.data.SessionStore
import com.ncmp.mobile.data.TaskBus
import com.ncmp.mobile.data.TaskConfig
import com.ncmp.mobile.data.TaskHistoryStore
import com.ncmp.mobile.data.TaskResult
import com.ncmp.mobile.data.TaskRunner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 前台服务：在后台可靠地执行任务（常驻通知 + WakeLock，防止被系统冻结）。 */
class TaskService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var job: Job? = null
    private var runner: TaskRunner? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var historyMessage = ""
    private var historyDetail = ""
    //: 本次执行是否已确认今日额外额度用完（用于收尾时把未轮到的额外行算今日完成）
    private var lastExtraAllDone = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_CANCEL -> {
                runner?.cancelled = true
                TaskBus.append("已请求取消任务…")
            }
            else -> startTask(intent)
        }
        return START_NOT_STICKY
    }

    private fun startTask(intent: Intent?) {
        if (job?.isActive == true) return
        TaskBus.reset()
        TaskBus.running.value = true
        historyMessage = ""
        historyDetail = ""
        lastExtraAllDone = false
        startForeground(NOTIF_ID, buildNotification("正在执行音乐合伙人任务…"))
        acquireLocks()

        val store = SessionStore(applicationContext)
        // 按曲目记账（哪首/几分/写了什么），记录页的口味曲线和最近曲目都读它
        val trackLog = com.ncmp.mobile.data.TrackLogStore(applicationContext)
        // 本地评分账本：同一任务重跑时不再提交已评过的歌（双端同构）
        val ledger = com.ncmp.mobile.data.RatingLedgerStore(applicationContext)
        // 曲目表等 onQueue 拿到服务端清单后再一起摆：先摆本地记录会出现 35/35 的闪烁
        val cfg = TaskConfig(
            scoreStrategy = intent?.getIntExtra(EXTRA_SCORE, 3) ?: 3,
            waitMinSeconds = intent?.getDoubleExtra(EXTRA_WAIT_MIN, 15.0) ?: 15.0,
            waitMaxSeconds = intent?.getDoubleExtra(EXTRA_WAIT_MAX, 20.0) ?: 20.0,
            fullExtraTasks = intent?.getBooleanExtra(EXTRA_FULL_EXTRA, true) ?: true,
            noteEnabled = store.noteEnabled,
            noteSource = store.noteSource,
            noteVoice = store.noteVoice,
            noteLength = store.noteLength,
            noteMaxChars = store.noteMaxChars,
        )
        val api = NeteaseApi().apply {
            musicU = store.musicU
            csrf = store.csrf
            debugLogger = { TaskBus.append(it) }
        }

        job = scope.launch {
            try {
                // 先读本地历史：今天已经提交的曲目数；达到基础 + 额外上限时
                // TaskRunner 会直接跳过额外阶段，不再请求服务端。
                val localSubmittedCount = trackLog.load().count {
                    it.day == com.ncmp.mobile.data.TrackLogStore.today() &&
                        it.state == com.ncmp.mobile.data.STATE_SUBMITTED
                }
                val r = TaskRunner(
                    api = api,
                    config = cfg,
                    log = { TaskBus.append(it) },
                    onStep = { name, _ -> TaskBus.step.value = name },
                    onProgress = { done, total, song, sc ->
                        TaskBus.done.value = done
                        TaskBus.total.value = total
                        TaskBus.song.value = song
                        TaskBus.score.value = sc
                        val group = TaskBus.groupOf(song)
                        TaskBus.addTrack(
                            song, sc, group = group,
                            extraLimit = if (cfg.fullExtraTasks) 15 else 7,
                        )
                        if (song.isNotBlank() && sc.isNotBlank()) {
                            trackLog.record(song, score = sc, group = group)
                        }
                    },
                    onPercent = { TaskBus.percent.value = it },
                    onNote = { song, sc, note ->
                        val group = TaskBus.groupOf(song)
                        TaskBus.addTrack(
                            song, sc, note, group = group,
                            extraLimit = if (cfg.fullExtraTasks) 15 else 7,
                        )
                        if (song.isNotBlank()) {
                            trackLog.record(song, score = sc, note = note, group = group)
                        }
                    },
                    onPoints = { points ->
                        TaskBus.points.value = points
                        // 存一份：记录页离线也能显示上次查到的数字
                        store.partnerPoints = org.json.JSONObject(points).toString()
                    },
                    onQueue = { items ->
                        val limit = if (cfg.fullExtraTasks) 15 else 7
                        // 额外阶段再次摆清单时 items 只有额外曲目：把曲目表里
                        // 已有的基础行也算进来，避免旧记录（没有 group）被误归为额外
                        val baseNames = buildSet {
                            items.filter { it.group != "extra" }
                                .forEach { add(it.work.name) }
                            TaskBus.tracks.value.filter { it.group == "base" }
                                .forEach { add(it.song) }
                        }
                        // 服务端清单 + 本机记录一次摆好，再统一裁到每日上限，
                        // 避免先出现 35/35 再跳回 20/20。
                        // 跳过 / 失败的记录只在服务端仍列出这首歌时才采用，
                        // 已经不在清单里的旧跳过行不再补回来。
                        TaskBus.seedQueue(items, limit, baseNames)
                        val serverNames = items.map { it.work.name }.toSet()
                        TaskBus.seedRecords(
                            trackLog.load().filter {
                                it.day == com.ncmp.mobile.data.TrackLogStore.today() &&
                                    (it.state == com.ncmp.mobile.data.STATE_SUBMITTED ||
                                        it.song in serverNames)
                            },
                            limit,
                            baseNames,
                        )
                        // 服务端说"已评过"的，补记进本机账本：今天在电脑端评的歌，
                        // 手机端「记录」页也能看到。同一天同一首会覆盖，不会重复。
                        items.filter { it.completed }.forEach { item ->
                            trackLog.record(
                                item.work.name,
                                artist = item.work.authorName,
                                score = item.score,
                                group = item.group,
                            )
                        }
                    },
                    onTrack = { work, state ->
                        TaskBus.setState(work, state)
                        // 跳过的歌也记下来：下次即使不在服务端待评清单里，
                        // 曲目表仍能看到它们的状态
                        if (state == com.ncmp.mobile.data.TrackState.SKIPPED ||
                            state == com.ncmp.mobile.data.TrackState.FAILED
                        ) {
                            val group = TaskBus.groupOf(work.name)
                            trackLog.record(
                                work.name,
                                artist = work.authorName,
                                state = state,
                                group = group,
                            )
                        }
                    },
                    ledger = ledger,
                    quotaStore = store,
                    localSubmittedCount = localSubmittedCount,
                )
                runner = r
                val result = r.run()
                runner = null
                when (result) {
                    is TaskResult.Success -> {
                        TaskBus.resultLabel.value = "任务完成"
                        TaskBus.resultIsError.value = false
                        lastExtraAllDone = result.extraAllDone
                        // 用曲目表的实际行数：本机补回来的额外任务也算进去
                        val doneCount = TaskBus.tracks.value.count {
                            it.state == com.ncmp.mobile.data.TrackState.DONE
                        }
                        val skippedCount = TaskBus.tracks.value.count {
                            it.state == com.ncmp.mobile.data.TrackState.SKIPPED
                        }
                        val base = result.base.coerceIn(0, doneCount)
                        val extra = (doneCount - base).coerceAtLeast(0)
                        // 和桌面端同一句摘要：成功，今日已完成 N 首（基础 X、额外 Y），
                        // 跳过 S 首，留下 M 条批注
                        val noteCount = TaskBus.noteCount()
                        historyMessage = if (doneCount > 0) {
                            "成功，今日已完成 $doneCount 首（基础 $base 首、额外 $extra 首）"
                        } else {
                            "成功，今日已完成 0 首"
                        }
                        if (skippedCount > 0) {
                            historyMessage += "，跳过 $skippedCount 首"
                        }
                        if (noteCount > 0) {
                            historyMessage += "，留下 $noteCount 条批注"
                        }
                        if (result.extraAllDone) {
                            historyMessage += "，今日额外额度已用完"
                        }
                    }
                    is TaskResult.Cancelled -> {
                        TaskBus.resultLabel.value = "已取消"
                        TaskBus.resultIsError.value = false
                        val doneCount = TaskBus.tracks.value.count {
                            it.state == com.ncmp.mobile.data.TrackState.DONE
                        }
                        historyMessage = "已取消，今日已完成 $doneCount 首"
                    }
                    is TaskResult.Failed -> {
                        TaskBus.resultLabel.value = "失败：${result.kind.label}"
                        TaskBus.resultHint.value = result.hint
                        TaskBus.resultIsError.value = true
                        historyMessage = "失败：${result.kind.label}"
                        historyDetail = result.hint
                    }
                }
                TaskBus.resultSummary.value = historyMessage
            } finally {
                // 先落历史再置 running=false：界面观察到结束时记录已经写好了
                recordHistory()
                // 收尾曲目表：本次没评到的「待评/评分中」不能一直挂着
                // （今天已经评过时，第一首会卡在"评分中"，下面全是"待评"）。
                // 只有成功跑完才把未轮到的额外曲目按「已评过」算；取消 / 失败时
                // 一律记「跳过」，否则第 5 首及以后会谎报成「已提交」。
                val outcome = when {
                    TaskBus.resultIsError.value -> "failed"
                    TaskBus.resultLabel.value == "已取消" -> "cancelled"
                    TaskBus.resultLabel.value == "任务完成" -> "success"
                    else -> "failed"
                }
                TaskBus.settleQueue(outcome, lastExtraAllDone)
                // 成功跑完后把结果落进今日账本：服务端待评清单缩水后，
                // 下次打开仍能补回曲目表，不会只剩基础那几首
                if (TaskBus.resultLabel.value == "任务完成") {
                    // 服务端标成已提交、但没给分数的额外曲目：记下来，
                    // 下次打开仍按「已提交」显示（没有分数，不参与口味曲线）
                    TaskBus.tracks.value
                        .filter {
                            it.state == com.ncmp.mobile.data.TrackState.DONE &&
                                it.group == "extra" && it.score.isBlank()
                        }
                        .forEach {
                            trackLog.record(
                                it.song,
                                artist = it.artist,
                                note = it.note,
                                group = "extra",
                            )
                        }
                    // 跳过就是跳过：落成 skipped，下次打开两端都显示「跳过」，
                    // 不能写成 submitted 冒充已评过
                    TaskBus.tracks.value
                        .filter { it.state == com.ncmp.mobile.data.TrackState.SKIPPED }
                        .forEach {
                            trackLog.record(
                                it.song,
                                artist = it.artist,
                                score = it.score,
                                note = it.note,
                                state = com.ncmp.mobile.data.STATE_SKIPPED,
                                group = it.group,
                            )
                        }
                }
                TaskBus.running.value = false
                releaseLocks()
                val nm = getSystemService(NotificationManager::class.java)
                // 结果通知：点一下回到 App；不再是常驻通知，可被划掉
                nm.notify(
                    NOTIF_ID,
                    buildNotification(
                        TaskBus.resultLabel.value.ifEmpty { "任务结束" },
                        ongoing = false,
                    ),
                )
                stopForeground(STOP_FOREGROUND_DETACH)
                stopSelf()
            }
        }
    }

    private fun recordHistory() {
        // 服务被系统杀掉时没有结果可记，别把一次中断写成成功
        if (TaskBus.resultLabel.value.isEmpty()) return
        try {
            val status = when {
                TaskBus.resultIsError.value -> "fail"
                TaskBus.resultLabel.value == "已取消" -> "cancel"
                else -> "success"
            }
            val now = Date()
            val date = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(now)
            val time = SimpleDateFormat("HH:mm", Locale.getDefault()).format(now)
            TaskHistoryStore(applicationContext).add(
                HistoryEntry(
                    date = date,
                    time = time,
                    status = status,
                    message = historyMessage.ifEmpty { TaskBus.resultLabel.value.ifEmpty { "任务结束" } },
                    detail = historyDetail,
                ),
            )
        } catch (_: Exception) {
        }
    }

    private fun acquireLocks() {
        try {
            val pm = getSystemService(PowerManager::class.java)
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ncmp:task").apply {
                setReferenceCounted(false)
                acquire(30 * 60 * 1000L) // 最长 30 分钟
            }
        } catch (_: Exception) {
        }
        try {
            val wm = applicationContext.getSystemService(WifiManager::class.java)
            wifiLock = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "ncmp:wifi").apply {
                setReferenceCounted(false)
                acquire()
            }
        } catch (_: Exception) {
        }
    }

    private fun releaseLocks() {
        try { wakeLock?.takeIf { it.isHeld }?.release() } catch (_: Exception) {}
        try { wifiLock?.takeIf { it.isHeld }?.release() } catch (_: Exception) {}
        wakeLock = null
        wifiLock = null
    }

    override fun onDestroy() {
        releaseLocks()
        scope.cancel()
        super.onDestroy()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(CHANNEL_ID, "任务执行", NotificationManager.IMPORTANCE_LOW)
            ch.description = "音乐合伙人任务执行状态"
            getSystemService(NotificationManager::class.java).createNotificationChannel(ch)
        }
    }

    /** 点击通知回到 App 的入口。没设置它时，点通知什么都不会发生。 */
    private fun openAppIntent(): PendingIntent {
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or
                Intent.FLAG_ACTIVITY_CLEAR_TOP or
                Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                PendingIntent.FLAG_IMMUTABLE
            } else {
                0
            }
        return PendingIntent.getActivity(this, 0, intent, flags)
    }

    private fun buildNotification(text: String, ongoing: Boolean = true): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("ncmp 音乐合伙人")
            .setContentText(text)
            .setContentIntent(openAppIntent())
            .setOngoing(ongoing)
            .setAutoCancel(!ongoing)
            .setOnlyAlertOnce(true)
            .build()

    companion object {
        const val ACTION_CANCEL = "com.ncmp.mobile.action.CANCEL"
        const val EXTRA_SCORE = "score"
        const val EXTRA_WAIT_MIN = "waitMin"
        const val EXTRA_WAIT_MAX = "waitMax"
        const val EXTRA_FULL_EXTRA = "fullExtra"
        private const val CHANNEL_ID = "ncmp_task"
        private const val NOTIF_ID = 1001
    }
}
