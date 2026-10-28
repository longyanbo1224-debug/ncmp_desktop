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
)

/** 记录页顶部的三个数 + 口味曲线要的档位分布。 */
data class TrackStats(
    val total: Int = 0,
    val notes: Int = 0,
    val tiers: Map<String, Int> = emptyMap(),  // "5" -> 3
) {
    /** 某一档占多少（0~100），给曲线条用。 */
    fun share(tier: String): Int {
        if (total <= 0) return 0
        return ((tiers[tier] ?: 0) * 100) / total
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
    ) {
        if (song.isBlank()) return
        val list = load().toMutableList()
        val index = list.indexOfFirst { it.day == day && it.song == song }
        val old = if (index >= 0) list[index] else null
        val merged = TrackRecord(
            day = day,
            song = song,
            artist = artist.ifBlank { old?.artist ?: "" },
            score = score.ifBlank { old?.score ?: "" },
            // 后一次没写批注，不等于要抹掉前一次写的
            note = note.ifBlank { old?.note ?: "" },
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
                    score = obj.optString("score"),
                    note = obj.optString("note"),
                )
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    /** 最近的曲目，新的在前。 */
    fun recent(limit: Int = 30): List<TrackRecord> =
        load().sortedWith(compareByDescending<TrackRecord> { it.day }).take(limit)

    fun stats(): TrackStats {
        val all = load()
        if (all.isEmpty()) return TrackStats()
        val tiers = mutableMapOf<String, Int>()
        var notes = 0
        for (item in all) {
            if (item.note.isNotBlank()) notes++
            val value = item.score.trim().toIntOrNull() ?: continue
            val key = value.toString()
            tiers[key] = (tiers[key] ?: 0) + 1
        }
        return TrackStats(total = all.size, notes = notes, tiers = tiers)
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
