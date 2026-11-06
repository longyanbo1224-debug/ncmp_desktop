package com.ncmp.mobile.data

import kotlinx.coroutines.flow.MutableStateFlow

/** 任务状态的中转站：前台服务写入，界面观察。 */
object TaskBus {
    val running = MutableStateFlow(false)
    val logs = MutableStateFlow<List<String>>(emptyList())
    val done = MutableStateFlow(0)
    val total = MutableStateFlow(0)
    /** 全局进度 0~100（和桌面端一样按阶段区间插值，不在两个评分阶段之间归零）。 */
    val percent = MutableStateFlow(0)
    val song = MutableStateFlow("")
    val score = MutableStateFlow("")
    val step = MutableStateFlow("")
    /** 今日曲目表：今天评了哪几首、每首几分、留下了什么批注。 */
    val tracks = MutableStateFlow<List<TrackItem>>(emptyList())
    /** 合伙人积分/等级；没查到就是空 Map（界面"没数据就不显示"）。 */
    val points = MutableStateFlow<Map<String, String>>(emptyMap())
    val resultLabel = MutableStateFlow("")
    val resultHint = MutableStateFlow("")
    val resultSummary = MutableStateFlow("")
    val resultIsError = MutableStateFlow(false)

    /** 歌名 → base/extra。曲目被上限裁掉后仍保留，评分回调才能把它归回额外。 */
    private val knownGroups = mutableMapOf<String, String>()

    fun groupOf(song: String): String = knownGroups[song] ?: ""

    fun reset() {
        logs.value = emptyList()
        done.value = 0
        total.value = 0
        percent.value = 0
        song.value = ""
        score.value = ""
        step.value = ""
        tracks.value = emptyList()
        points.value = emptyMap()
        resultLabel.value = ""
        resultHint.value = ""
        resultSummary.value = ""
        resultIsError.value = false
        knownGroups.clear()
    }

    fun append(line: String) {
        val cur = logs.value
        val safe = redact(line)
        logs.value = (cur + safe).let { if (it.size > 500) it.takeLast(500) else it }
    }

    //: 日志里绝不能出现的东西（LLM key / Cookie / csrf / Bearer）
    private val SECRETS = listOf(
        Regex("sk-[A-Za-z0-9_-]{6,}") to "sk-***",
        Regex("(MUSIC_U=)[^;,\\s\"']+") to "$1***",
        Regex("(__csrf=)[^;,\\s\"']+") to "$1***",
        Regex("(?i)(authorization:\\s*bearer\\s+)\\S+") to "$1***",
    )

    /** 脱敏 + 截断。所有写日志的地方都走这里，不靠"记得别打印"。 */
    fun redact(line: String): String {
        var text = line
        for ((pattern, replacement) in SECRETS) text = text.replace(pattern, replacement)
        return if (text.length > 400) text.take(400) + "…" else text
    }

    // ------------------------------------------------------------------
    // 曲目表
    // ------------------------------------------------------------------

    /** 重建曲目表时先清空；跨天另见 clearDay。 */
    fun clearTracks() {
        tracks.value = emptyList()
    }

    /** 跨天时清掉上一天的状态：曲目、进度、结果和日志都换新的一天。 */
    fun clearDay() {
        tracks.value = emptyList()
        logs.value = emptyList()
        done.value = 0
        total.value = 0
        percent.value = 0
        song.value = ""
        score.value = ""
        step.value = ""
        resultLabel.value = ""
        resultHint.value = ""
        resultSummary.value = ""
        resultIsError.value = false
        knownGroups.clear()
    }

    /** 预置今天的曲目：已评过的直接显示「已提交」并带上服务端分数，没评的显示「待评」。 */
    fun seedQueue(items: List<WorkItem>, extraLimit: Int = 0,
                  baseNames: Set<String> = emptySet()) {
        if (items.isEmpty()) return
        val cur = tracks.value.toMutableList()
        addItems(cur, items)
        val grouped = inferList(cur, baseNames)
        tracks.value = if (extraLimit > 0) capList(grouped, extraLimit) else grouped
    }

    /** 把本机今日记录并进曲目表：服务端待评清单缩水时，评过/跳过的不丢失。 */
    fun seedRecords(records: List<TrackRecord>, extraLimit: Int = 0,
                    baseNames: Set<String> = emptySet()) {
        if (records.isEmpty()) return
        val cur = tracks.value.toMutableList()
        addRecords(cur, records)
        val grouped = inferList(cur, baseNames)
        tracks.value = if (extraLimit > 0) capList(grouped, extraLimit) else grouped
    }

    private fun itemKey(song: String, artist: String): String =
        if (artist.isBlank()) song else "$song|$artist"

    private fun indexOfTrack(
        cur: List<TrackItem>, song: String, artist: String,
    ): Int {
        val wanted = itemKey(song, artist)
        val exact = cur.indexOfFirst { it.trackKey == wanted }
        if (exact >= 0) return exact
        // 旧数据 / 进度回调没有歌手时：退回按歌名匹配尚未确定键的行
        return cur.indexOfFirst { it.song == song && it.key.isBlank() }
    }

    private fun addItems(cur: MutableList<TrackItem>, items: List<WorkItem>) {
        for (item in items) {
            val work = item.work
            if (work.name.isBlank()) continue
            // 基础任务即使也被额外清单列出来，也不能被改成 extra：
            // 否则会被算进额外 15 首上限，曲目表从 20 行被裁成 15 行
            val incomingGroup = item.group
            val knownGroup = knownGroups[work.name]
            if (incomingGroup.isNotBlank() &&
                !(knownGroup == "base" && incomingGroup == "extra")
            ) {
                knownGroups[work.name] = incomingGroup
            }
            val index = indexOfTrack(cur, work.name, work.authorName)
            val trackKey = itemKey(work.name, work.authorName)
            if (index < 0) {
                cur.add(
                    TrackItem(
                        song = work.name,
                        artist = work.authorName,
                        score = item.score,
                        state = if (item.completed) TrackState.DONE else TrackState.PENDING,
                        group = incomingGroup,
                        key = trackKey,
                    ),
                )
            } else if (item.completed) {
                // 已有行（可能是上一轮摆的"待评"）升级成"已提交"
                val old = cur[index]
                val group = when {
                    old.group == "base" -> "base"
                    incomingGroup.isNotBlank() -> incomingGroup
                    else -> old.group
                }
                cur[index] = old.copy(
                    state = TrackState.DONE,
                    score = old.score.ifBlank { item.score },
                    artist = old.artist.ifBlank { work.authorName },
                    group = group,
                    key = old.trackKey,
                )
            }
        }
    }

    private fun addRecords(cur: MutableList<TrackItem>, records: List<TrackRecord>) {
        for (record in records) {
            if (record.song.isBlank()) continue
            if (record.group.isNotBlank() &&
                !(knownGroups[record.song] == "base" && record.group == "extra")
            ) {
                knownGroups[record.song] = record.group
            }
            val state = when (record.state) {
                STATE_SUBMITTED -> TrackState.DONE
                STATE_SKIPPED -> TrackState.SKIPPED
                STATE_FAILED -> TrackState.FAILED
                else -> TrackState.PENDING
            }
            val index = indexOfTrack(cur, record.song, record.artist)
            val trackKey = itemKey(record.song, record.artist)
            if (index < 0) {
                cur.add(
                    TrackItem(
                        song = record.song,
                        artist = record.artist,
                        score = record.score,
                        note = record.note,
                        state = state,
                        group = record.group,
                        key = trackKey,
                    ),
                )
            } else if (record.state == STATE_SUBMITTED) {
                // 本机记录为 submitted 就按「已提交」展示（1.2.4 的历史口径）：
                // 旧版本 / 额度用完时可能没有分数，但历史已经确认这天评过。
                // 只有 skipped / failed 且服务端没标完成时才降级。
                val old = cur[index]
                val recordScore = normalizeScore(record.score)
                if (old.state == TrackState.PENDING) {
                    val group = when {
                        old.group == "base" -> "base"
                        record.group.isNotBlank() -> record.group
                        else -> old.group
                    }
                    cur[index] = old.copy(
                        state = TrackState.DONE,
                        score = old.score.ifBlank { recordScore },
                        note = old.note.ifBlank { record.note },
                        artist = old.artist.ifBlank { record.artist },
                        group = group,
                    )
                }
            } else if (record.state == STATE_SKIPPED || record.state == STATE_FAILED) {
                // 本机明确记过「跳过 / 失败」的，服务端若仍标待评，按本机状态显示。
                // 之前这里只处理 submitted，导致跑完后一刷新又回到「待评」，
                // 和桌面端的「跳过」对不上。
                val old = cur[index]
                if (old.state == TrackState.PENDING) {
                    val group = when {
                        old.group == "base" -> "base"
                        record.group.isNotBlank() -> record.group
                        else -> old.group
                    }
                    cur[index] = old.copy(
                        state = state,
                        artist = old.artist.ifBlank { record.artist },
                        group = group,
                    )
                }
            }
        }
    }

    /** 旧记录没有 group 时，按服务端基础清单补上：不在清单里的算额外。 */
    private fun inferList(cur: List<TrackItem>,
                          baseNames: Set<String>): List<TrackItem> =
        cur.map { item ->
            val group = when {
                // 清单里明确属于基础任务的，始终留在 base 组
                item.song in baseNames -> "base"
                item.group.isNotBlank() -> item.group
                else -> "extra"
            }
            knownGroups[item.song] = group
            if (group == item.group) item else item.copy(group = group)
        }

    /**
     * 按每日上限裁剪额外行（基础全留，额外最多 [extraLimit] 条）。
     * 优先保留已提交的，避免旧批次/旧运行的行把 20/20 撑成 20/41。
     */
    fun capTracks(extraLimit: Int) {
        if (extraLimit <= 0) return
        tracks.value = capList(tracks.value, extraLimit)
    }

    private fun capList(all: List<TrackItem>, extraLimit: Int): List<TrackItem> {
        val extras = all.filter { it.group == "extra" }
        if (extras.size <= extraLimit) return all
        val keep = extras
            .sortedBy { if (it.state == TrackState.DONE) 0 else 1 }
            .take(extraLimit)
            .map { it.trackKey }
            .toSet()
        return all.filter { it.group != "extra" || it.trackKey in keep }
    }

    /** 记一首已评分的曲目（同一首歌只保留一行，批注后到就补上去）。 */
    fun addTrack(song: String, score: String, note: String = "",
                 artist: String = "", group: String = "",
                 extraLimit: Int = 0) {
        if (song.isBlank()) return
        val cur = tracks.value
        // 进度 / 批注回调只带歌名：同名多作品按「先待评 / 先无批注」匹配
        val index = if (note.isNotBlank()) {
            cur.indexOfFirst { it.song == song && it.note.isBlank() }
                .takeIf { it >= 0 }
                ?: cur.indexOfFirst { it.song == song }
        } else {
            cur.indexOfFirst { it.song == song && it.state != TrackState.DONE }
                .takeIf { it >= 0 }
                ?: cur.indexOfFirst { it.song == song }
        }
        val resolvedGroup = group.ifBlank {
            knownGroups[song] ?: (if (index >= 0) cur[index].group else "")
        }
        val item = if (index >= 0) {
            cur[index].copy(
                artist = if (artist.isNotBlank()) artist else cur[index].artist,
                score = score.ifBlank { cur[index].score },
                note = note.ifBlank { cur[index].note },
                state = TrackState.DONE,
                group = resolvedGroup,
                key = cur[index].trackKey,
            )
        } else {
            TrackItem(song = song, artist = artist, score = score, note = note,
                state = TrackState.DONE, group = resolvedGroup,
                key = itemKey(song, artist))
        }
        val next = if (index >= 0) {
            cur.toMutableList().also { it[index] = item }
        } else {
            cur + item
        }
        tracks.value = if (extraLimit > 0) capList(next, extraLimit) else next
    }

    /** 改一首歌的状态（评分中 / 跳过 / 失败）。歌不在今日列表里就忽略。 */
    fun setState(work: Work, state: String) {
        if (work.name.isBlank()) return
        val cur = tracks.value
        val wanted = itemKey(work.name, work.authorName)
        val index = cur.indexOfFirst { it.trackKey == wanted }
            .takeIf { it >= 0 }
            ?: cur.indexOfFirst { it.song == work.name && it.state == TrackState.PENDING }
            ?: cur.indexOfFirst { it.song == work.name }
        // 已被每日上限裁掉的行不再补回来，否则会出现 35/35、45/45 的闪烁
        if (index < 0) return
        val item = cur[index].copy(
            artist = cur[index].artist.ifBlank { work.authorName },
            state = state,
        )
        tracks.value = cur.toMutableList().also { it[index] = item }
    }

    /** 已提交的批注条数（页头那一行要用）。 */
    fun noteCount(): Int = tracks.value.count { it.note.isNotBlank() }

    /**
     * 今日额外额度已用完（本地缓存命中）：把仍挂着「待评」的额外行显示为已完成。
     *
     * 只用于「服务端明确说过今日没有更多」或本地已缓存该结论的场景；
     * 普通取消 / 单首失败留下的「跳过」不会被算成完成。
     */
    fun markExtraPendingDone() {
        tracks.value = tracks.value.map { item ->
            if (item.group == "extra" &&
                (item.state == TrackState.PENDING || item.state == TrackState.SKIPPED)
            ) {
                item.copy(state = TrackState.DONE)
            } else {
                item
            }
        }
    }

    /**
     * 一次执行结束时的收尾：把没跑完的行定下来。
     *
     * 规则：
     * - 服务端确认今日额外额度用完（[extraAllDone]）：没轮到的额外行按今日完成计，
     *   和 1.2.4 的记录展示一致；摘要会注明「今日额外额度已用完」。
     * - 普通成功 / 取消 / 失败：没轮到的行记「跳过」，绝不冒充「已提交」。
     * - 评分中没走完的行：失败 → 失败；其余 → 跳过。
     *
     * @param outcome "success" / "cancelled" / "failed"
     * @param extraAllDone 服务端是否明确返回过「今日没有更多」或本地额度缓存命中
     */
    fun settleQueue(outcome: String, extraAllDone: Boolean = false) {
        val failed = outcome == "failed"
        tracks.value = tracks.value.map { item ->
            val quotaDone = extraAllDone && item.group == "extra"
            when (item.state) {
                TrackState.RUNNING -> item.copy(state = when {
                    quotaDone -> TrackState.DONE
                    failed -> TrackState.FAILED
                    else -> TrackState.SKIPPED
                })
                TrackState.PENDING, TrackState.SKIPPED ->
                    item.copy(state = if (quotaDone) TrackState.DONE else TrackState.SKIPPED)
                else -> item
            }
        }
    }

    /** 已提交（已评分）的曲目数。 */
    fun doneCount(): Int = tracks.value.count { it.state == TrackState.DONE }
}
