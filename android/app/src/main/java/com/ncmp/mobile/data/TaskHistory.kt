package com.ncmp.mobile.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale

/**
 * 一次执行。
 * 同一天可能执行多次（手动补跑、定时后重试），明细都留着，
 * 格子图和「执行情况」列表按天合并成一条。
 */
data class HistoryEntry(
    val date: String,     // yyyy-MM-dd
    val time: String,     // HH:mm
    val status: String,   // success / fail / cancel
    val message: String,
    val detail: String = "",
)

/** 一天的执行情况：当天所有执行合并成一条。 */
data class DayRecord(
    val date: String,
    val status: String,
    val runs: List<HistoryEntry>,
)

/** 格子图的一格。status: success / fail / none */
data class DayCell(val date: String, val status: String)

/** 打卡记录：按次保存最近的任务结果。 */
class TaskHistoryStore(context: Context) {
    private val prefs = context.getSharedPreferences("ncmp_history", Context.MODE_PRIVATE)

    fun load(): List<HistoryEntry> {
        val s = prefs.getString(KEY, null) ?: return emptyList()
        return try {
            val arr = JSONArray(s)
            (0 until arr.length()).mapNotNull { i ->
                val o = arr.optJSONObject(i) ?: return@mapNotNull null
                val message = o.optString("message")
                // 旧版把时间写在 message 开头（"09:02  任务完成"），这里兼容读出来
                val time = o.optString("time").ifEmpty {
                    Regex("^(\\d{2}:\\d{2})").find(message)?.groupValues?.get(1) ?: ""
                }
                HistoryEntry(
                    date = o.optString("date"),
                    time = time,
                    status = o.optString("status"),
                    message = message,
                    detail = o.optString("detail"),
                )
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    fun add(entry: HistoryEntry) {
        val list = mutableListOf(entry)
        list.addAll(load())
        val arr = JSONArray()
        list.take(MAX_RUNS).forEach { e ->
            arr.put(JSONObject().apply {
                put("date", e.date)
                put("time", e.time)
                put("status", e.status)
                put("message", e.message)
                put("detail", e.detail)
            })
        }
        prefs.edit().putString(KEY, arr.toString()).apply()
    }

    fun clear() {
        prefs.edit().remove(KEY).apply()
    }

    companion object {
        private const val KEY = "entries"
        // 800 条 ≈ 一年每天跑 + 偶尔补跑，够格子图画满 53 周
        private const val MAX_RUNS = 800
    }
}

// ----------------------------------------------------------------------
// 按天聚合 + 一年格子图
// ----------------------------------------------------------------------

private val DAY_FMT = SimpleDateFormat("yyyy-MM-dd", Locale.US)

/** 一天一条执行情况，新在前。只有取消的那天也算"没跑成"。 */
fun groupDays(runs: List<HistoryEntry>): List<DayRecord> =
    runs.groupBy { it.date }
        .map { (date, list) ->
            DayRecord(
                date = date,
                status = when {
                    list.any { it.status == "success" } -> "success"
                    list.any { it.status == "fail" } -> "fail"
                    else -> "cancel"
                },
                runs = list.sortedByDescending { it.time },
            )
        }
        .sortedByDescending { it.date }

/**
 * 最近 [weeks] 周的格子，周一为列首，最后一格是今天。
 * 未来的日子不返回，和桌面端格子图一样留白。
 */
fun gridDays(runs: List<HistoryEntry>, weeks: Int = 53): List<DayCell> {
    val byDay = runs.groupBy { it.date }.mapValues { (_, list) ->
        when {
            list.any { it.status == "success" } -> "success"
            list.any { it.status == "fail" } -> "fail"
            else -> "none"   // 只有取消 = 没打卡
        }
    }
    val today = Calendar.getInstance().apply {
        set(Calendar.HOUR_OF_DAY, 0)
        set(Calendar.MINUTE, 0)
        set(Calendar.SECOND, 0)
        set(Calendar.MILLISECOND, 0)
    }
    // Calendar: 周日=1 … 周六=7；换算成"距离本周一几天"
    val mondayOffset = (today.get(Calendar.DAY_OF_WEEK) + 5) % 7
    val cursor = (today.clone() as Calendar).apply {
        add(Calendar.DAY_OF_YEAR, -mondayOffset - (weeks - 1) * 7)
    }
    val out = ArrayList<DayCell>()
    while (!cursor.after(today)) {
        val key = DAY_FMT.format(cursor.time)
        out.add(DayCell(key, byDay[key] ?: "none"))
        cursor.add(Calendar.DAY_OF_YEAR, 1)
    }
    return out
}

/** 从今天往回数的连续成功天数（今天还没跑不算断）。 */
fun streakDays(cells: List<DayCell>): Int {
    var i = cells.lastIndex
    if (i >= 0 && cells[i].status != "success") i--
    var n = 0
    while (i >= 0 && cells[i].status == "success") {
        n++
        i--
    }
    return n
}
