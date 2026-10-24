package com.ncmp.mobile.data

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import com.ncmp.mobile.AlarmReceiver
import java.util.Calendar

/** 用 AlarmManager 安排每日定时执行。 */
object AlarmScheduler {
    private const val REQ = 2001

    private fun pending(context: Context): PendingIntent {
        val intent = Intent(context, AlarmReceiver::class.java)
        return PendingIntent.getBroadcast(
            context,
            REQ,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    fun schedule(context: Context, hour: Int, minute: Int) {
        val am = context.getSystemService(AlarmManager::class.java) ?: return
        val cal = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, hour)
            set(Calendar.MINUTE, minute)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
            if (timeInMillis <= System.currentTimeMillis()) add(Calendar.DAY_OF_YEAR, 1)
        }
        val exact = Build.VERSION.SDK_INT < Build.VERSION_CODES.S || am.canScheduleExactAlarms()
        if (exact) {
            am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, cal.timeInMillis, pending(context))
        } else {
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, cal.timeInMillis, pending(context))
        }
    }

    fun cancel(context: Context) {
        val am = context.getSystemService(AlarmManager::class.java) ?: return
        am.cancel(pending(context))
    }
}
