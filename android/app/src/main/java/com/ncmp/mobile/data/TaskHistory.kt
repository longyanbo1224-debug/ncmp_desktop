package com.ncmp.mobile.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

data class HistoryEntry(
    val date: String,     // yyyy-MM-dd
    val status: String,   // success / fail / cancel / quota
    val message: String,
)

/** 打卡记录：按次保存最近的任务结果。 */
class TaskHistoryStore(context: Context) {
    private val prefs = context.getSharedPreferences("ncmp_history", Context.MODE_PRIVATE)

    fun load(): List<HistoryEntry> {
        val s = prefs.getString(KEY, null) ?: return emptyList()
        return try {
            val arr = JSONArray(s)
            (0 until arr.length()).map { i ->
                val o = arr.getJSONObject(i)
                HistoryEntry(o.optString("date"), o.optString("status"), o.optString("message"))
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    fun add(entry: HistoryEntry) {
        val list = mutableListOf(entry)
        list.addAll(load())
        val arr = JSONArray()
        list.take(60).forEach { e ->
            arr.put(JSONObject().apply {
                put("date", e.date)
                put("status", e.status)
                put("message", e.message)
            })
        }
        prefs.edit().putString(KEY, arr.toString()).apply()
    }

    fun clear() {
        prefs.edit().remove(KEY).apply()
    }

    companion object {
        private const val KEY = "entries"
    }
}
