package com.ncmp.mobile

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.ncmp.mobile.data.AlarmScheduler
import com.ncmp.mobile.data.SessionStore

/** 定时闹钟触发：启动任务前台服务，并安排下一次。 */
class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val store = SessionStore(context)
        if (!store.scheduleEnabled) return

        // 重启后重新安排每日定时
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            AlarmScheduler.schedule(context, store.scheduleHour, store.scheduleMinute)
            return
        }

        val svc = Intent(context, TaskService::class.java).apply {
            putExtra(TaskService.EXTRA_SCORE, store.scoreStrategy)
            putExtra(TaskService.EXTRA_WAIT_MIN, store.waitMin.toDouble())
            putExtra(TaskService.EXTRA_WAIT_MAX, store.waitMax.toDouble())
            putExtra(TaskService.EXTRA_FULL_EXTRA, store.fullExtra)
        }
        try {
            ContextCompat.startForegroundService(context, svc)
        } catch (_: Exception) {
            // Android 14+ 后台启动受限时，用普通通知提示用户手动点
            notifyFallback(context)
        }
        // 安排下一次（明天同一时间）
        AlarmScheduler.schedule(context, store.scheduleHour, store.scheduleMinute)
    }

    private fun notifyFallback(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java) ?: return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(
                NotificationChannel("ncmp_alarm", "定时提醒", NotificationManager.IMPORTANCE_HIGH),
            )
        }
        val pi = PendingIntent.getActivity(
            context,
            0,
            Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val n: Notification = NotificationCompat.Builder(context, "ncmp_alarm")
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("ncmp 音乐合伙人")
            .setContentText("到点了，打开 App 执行今日任务")
            .setContentIntent(pi)
            .setAutoCancel(true)
            .build()
        nm.notify(3001, n)
    }
}
