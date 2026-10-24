package com.ncmp.mobile

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import com.ncmp.mobile.data.NeteaseApi
import com.ncmp.mobile.data.SessionStore
import com.ncmp.mobile.data.TaskBus
import com.ncmp.mobile.data.TaskConfig
import com.ncmp.mobile.data.TaskResult
import com.ncmp.mobile.data.TaskRunner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/** 前台服务：在后台可靠地执行任务（常驻通知 + WakeLock，防止被系统冻结）。 */
class TaskService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var job: Job? = null
    private var runner: TaskRunner? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null

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
        startForeground(NOTIF_ID, buildNotification("正在执行音乐合伙人任务…"))
        acquireLocks()

        val store = SessionStore(applicationContext)
        val cfg = TaskConfig(
            scoreStrategy = intent?.getIntExtra(EXTRA_SCORE, 3) ?: 3,
            waitMinSeconds = intent?.getDoubleExtra(EXTRA_WAIT_MIN, 15.0) ?: 15.0,
            waitMaxSeconds = intent?.getDoubleExtra(EXTRA_WAIT_MAX, 20.0) ?: 20.0,
            fullExtraTasks = intent?.getBooleanExtra(EXTRA_FULL_EXTRA, true) ?: true,
        )
        val api = NeteaseApi().apply {
            musicU = store.musicU
            csrf = store.csrf
            debugLogger = { TaskBus.append(it) }
        }

        job = scope.launch {
            try {
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
                    },
                )
                runner = r
                val result = r.run()
                runner = null
                when (result) {
                    is TaskResult.Success -> { TaskBus.resultLabel.value = "任务完成"; TaskBus.resultIsError.value = false }
                    is TaskResult.Cancelled -> { TaskBus.resultLabel.value = "已取消"; TaskBus.resultIsError.value = false }
                    is TaskResult.Failed -> {
                        TaskBus.resultLabel.value = "失败：${result.kind.label}"
                        TaskBus.resultHint.value = result.hint
                        TaskBus.resultIsError.value = true
                    }
                }
            } finally {
                TaskBus.running.value = false
                releaseLocks()
                val nm = getSystemService(NotificationManager::class.java)
                nm.notify(NOTIF_ID, buildNotification(TaskBus.resultLabel.value.ifEmpty { "任务结束" }))
                stopForeground(STOP_FOREGROUND_DETACH)
                stopSelf()
            }
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

    private fun buildNotification(text: String): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("ncmp 音乐合伙人")
            .setContentText(text)
            .setOngoing(true)
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
