package com.ncmp.mobile.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * 本地评分账本（与桌面端 `core/rating_ledger.py` 同构）。
 *
 * 服务端的 `completed` 仍是"评过没有"的主依据；这里只补一个漏：任务列表偶尔
 * 仍把刚评过的歌标成未完成。命中账本只跳过重复提交，绝不反过来判定"没评过"。
 *
 * 按 (账号, taskId) 分组：换天、换账号后 taskId 不同，旧记录自然不命中。
 */
class RatingLedgerStore(context: Context) {

    private val prefs = context.getSharedPreferences("ncmp_rated_works", Context.MODE_PRIVATE)

    private data class Entry(
        val account: String,
        val taskId: String,
        val workId: String,
        val score: String,
        val ts: Long,
    )

    /** 本任务里这首是否已评过；评过返回当时的分数。 */
    fun score(account: String, taskId: Any, workId: Any): String? {
        val key = workId.toString()
        // 作品 id 缺失时所有歌都会撞到同一个空 key，绝不能拿它去判定「已评过」
        if (key.isBlank() || key.equals("null", ignoreCase = true)) return null
        return load().firstOrNull {
            it.account == account && it.taskId == taskId.toString() && it.workId == key
        }?.score?.let(::normalizeScore)?.takeIf { it.isNotBlank() }
    }

    /** 本任务里已经由服务端确认收下的作品数（用于判断今天是否已评满）。 */
    fun count(account: String, taskId: Any): Int =
        load().count { it.account == account && it.taskId == taskId.toString() }

    /** 记一次服务端确认收下的评分。 */
    fun mark(account: String, taskId: Any, workId: Any, score: String) {
        val taskKey = taskId.toString()
        val workKey = workId.toString()
        if (workKey.isBlank() || workKey.equals("null", ignoreCase = true)) return
        // 旧版本把 JSON null 读成 "null" 记了进来：这种条目不能用来跳过评分，
        // 否则修好解析后仍然会整轮「本任务已评过」
        val cleanScore = normalizeScore(score)
        if (cleanScore.isBlank()) return
        val now = System.currentTimeMillis()
        val entries = load().toMutableList()
        entries.removeAll {
            it.account == account && it.taskId == taskKey && it.workId == workKey
        }
        entries.add(Entry(account, taskKey, workKey, cleanScore, now))
        save(entries.filter { now - it.ts <= MAX_AGE_MS }.takeLast(MAX_RECORDS))
    }

    private fun load(): List<Entry> {
        val raw = prefs.getString(KEY, null) ?: return emptyList()
        return try {
            val array = JSONArray(raw)
            (0 until array.length()).mapNotNull { i ->
                val obj = array.optJSONObject(i) ?: return@mapNotNull null
                val workId = obj.optString("workId")
                if (workId.isEmpty() || workId.equals("null", ignoreCase = true)) {
                    return@mapNotNull null
                }
                Entry(
                    account = obj.optString("account"),
                    taskId = obj.optString("taskId"),
                    workId = workId,
                    // 无效分数（"null" / 0 / 空）等于没评过，读取时直接丢弃
                    score = normalizeScore(obj.optString("score")),
                    ts = obj.optLong("ts", 0L),
                )
            }.filter { it.score.isNotBlank() }
        } catch (_: Exception) {
            emptyList()
        }
    }

    private fun save(entries: List<Entry>) {
        val array = JSONArray()
        for (entry in entries) {
            array.put(
                JSONObject().apply {
                    put("account", entry.account)
                    put("taskId", entry.taskId)
                    put("workId", entry.workId)
                    put("score", entry.score)
                    put("ts", entry.ts)
                },
            )
        }
        prefs.edit().putString(KEY, array.toString()).apply()
    }

    private companion object {
        const val KEY = "entries"
        const val MAX_AGE_MS = 48L * 60 * 60 * 1000
        const val MAX_RECORDS = 500
    }
}
