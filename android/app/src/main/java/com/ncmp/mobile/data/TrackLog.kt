package com.ncmp.mobile.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 一条曲目记录：哪天、哪首歌、几分、留下什么话。
 *
 * 桌面端有 `track_log.json` 存这个，手机端以前只存"每次执行的结果"，
 * 所以"我今年给几分的多""上周三评了哪首"这类问题答不了。
 */
data class TrackRecord(
    val day: String,          // yyyy-MM-dd
    val song: String,
    val artist: String = "",
    val score: String = "",
    val note: String = "",
    //: submitted / skipped / failed（与桌面端 track_log 同构）
    val state: String = STATE_SUBMITTED,
    //: base / extra：按每日上限裁剪时用
    val group: String = "",
)

/** 与桌面端 app/track_log.py 的状态值一致。 */
const val STATE_SUBMITTED = "submitted"
const val STATE_SKIPPED = "skipped"
const val STATE_FAILED = "failed"

/**
 * 归一化服务端 / 本机记录里的分数：空串、JSON `null` 被读成的 `"null"`、
 * 数字 0 都代表「还没有分数」，统一成 `""`；有效档位（1–5）保留原样。
 *
 * 不能只判断 `isNotBlank()`：Android 的 `optString` 会把 `"score": null`
 * 读成字符串 `"null"`，把它当成「已评过」会让整天一首都不评。
 */
fun normalizeScore(raw: String?): String {
    val text = raw?.trim().orEmpty()
    if (text.isEmpty() || text.equals("null", ignoreCase = true)) return ""
    val value = text.toIntOrNull() ?: return ""
    return if (value in 1..5) value.toString() else ""
}

/** 记录页顶部的三个数 + 口味曲线要的档位分布。 */
data class TrackStats(
    val total: Int = 0,
    val notes: Int = 0,
    val tiers: Map<String, Int> = emptyMap(),  // "5" -> 3
    /**
     * 已提交、但没有分数记录的曲目数。
     *
     * 服务端对已完成的作品偶尔只给 `completed` 而不返回 `score`（比如在另一台设备
     * 上评过、或换过接口批次），这类记录无法归进任何档位——必须单独说明，
     * 否则用户会看到「累计 20 首，曲线只有 10 首」却不知道另外 10 首去哪了。
     */
    val unscored: Int = 0,
) {
    /** 某一档占多少（0~100），给曲线条用。 */
    fun share(tier: String): Int {
        val scored = tiers.values.sum()
        if (scored <= 0) return 0
        return ((tiers[tier] ?: 0) * 100) / scored
    }

    fun maxTierCount(): Int = tiers.values.maxOrNull() ?: 0
}

/**
 * 按曲目保存的记录（与桌面端 `track_log.json` 同构，落地在 SharedPreferences）。
 * 同一天同一首歌**覆盖**：重跑不该让账上出现两遍。
 */
class TrackLogStore(context: Context) {

    private val prefs = context.getSharedPreferences("ncmp_tracks", Context.MODE_PRIVATE)

    fun record(
        song: String,
        artist: String = "",
        score: String = "",
        note: String = "",
        day: String = today(),
        state: String = STATE_SUBMITTED,
        group: String = "",
    ) {
        if (song.isBlank()) return
        val list = load().toMutableList()
        val index = list.indexOfFirst { it.day == day && it.song == song }
        val old = if (index >= 0) list[index] else null
        val merged = TrackRecord(
            day = day,
            song = song,
            artist = artist.ifBlank { old?.artist ?: "" },
            // 只有有效档位才算分数：旧版本可能把服务端的 null 写成 "null"
            score = normalizeScore(score).ifBlank { normalizeScore(old?.score) },
            // 后一次没写批注，不等于要抹掉前一次写的
            note = note.ifBlank { old?.note ?: "" },
            // 已经提交过的，不能被后来的「跳过」覆盖
            state = if (old?.state == STATE_SUBMITTED) STATE_SUBMITTED else state,
            group = group.ifBlank { old?.group ?: "" },
        )
        if (index >= 0) list[index] = merged else list.add(merged)
        save(list)
    }

    fun load(): List<TrackRecord> {
        val raw = prefs.getString(KEY, null) ?: return emptyList()
        return try {
            val array = JSONArray(raw)
            (0 until array.length()).mapNotNull { i ->
                val obj = array.optJSONObject(i) ?: return@mapNotNull null
                val song = obj.optString("song")
                if (song.isEmpty()) return@mapNotNull null
                TrackRecord(
                    day = obj.optString("day", today()),
                    song = song,
                    artist = obj.optString("artist"),
                    score = normalizeScore(obj.optString("score")),
                    note = obj.optString("note"),
                    state = obj.optString("state", STATE_SUBMITTED),
                    group = obj.optString("group"),
                )
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    /** 最近的曲目，新的在前。只含提交成功的：跳过的不算「评过」。 */
    fun recent(limit: Int = 30): List<TrackRecord> =
        load()
            .filter { it.state == STATE_SUBMITTED }
            .sortedWith(compareByDescending<TrackRecord> { it.day })
            .take(limit)

    fun stats(): TrackStats {
        val all = load().filter { it.state == STATE_SUBMITTED }
        if (all.isEmpty()) return TrackStats()
        val tiers = mutableMapOf<String, Int>()
        var notes = 0
        for (item in all) {
            if (item.note.isNotBlank()) notes++
            val value = item.score.trim().toIntOrNull()?.takeIf { it in 1..5 } ?: continue
            val key = value.toString()
            tiers[key] = (tiers[key] ?: 0) + 1
        }
        return TrackStats(
            total = all.size,
            notes = notes,
            tiers = tiers,
            unscored = (all.size - tiers.values.sum()).coerceAtLeast(0),
        )
    }

    private fun save(list: List<TrackRecord>) {
        val trimmed = list.takeLast(MAX_RECORDS)
        val array = JSONArray()
        for (item in trimmed) {
            array.put(
                JSONObject().apply {
                    put("day", item.day)
                    put("song", item.song)
                    put("artist", item.artist)
                    put("score", item.score)
                    put("note", item.note)
                    put("state", item.state)
                    put("group", item.group)
                },
            )
        }
        prefs.edit().putString(KEY, array.toString()).apply()
    }

    companion object {
        private const val KEY = "tracks"
        private const val MAX_RECORDS = 2000

        fun today(): String =
            SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
    }
}
