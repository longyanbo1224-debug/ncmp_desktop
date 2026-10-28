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
    val resultLabel = MutableStateFlow("")
    val resultHint = MutableStateFlow("")
    val resultSummary = MutableStateFlow("")
    val resultIsError = MutableStateFlow(false)

    fun reset() {
        logs.value = emptyList()
        done.value = 0
        total.value = 0
        percent.value = 0
        song.value = ""
        score.value = ""
        step.value = ""
        tracks.value = emptyList()
        resultLabel.value = ""
        resultHint.value = ""
        resultSummary.value = ""
        resultIsError.value = false
    }

    fun append(line: String) {
        val cur = logs.value
        logs.value = (cur + line).let { if (it.size > 500) it.takeLast(500) else it }
    }

    // ------------------------------------------------------------------
    // 曲目表
    // ------------------------------------------------------------------

    /** 预置今天的待评队列：曲目先出现，状态等评分结果回来再改。 */
    fun seedQueue(works: List<Work>) {
        if (works.isEmpty()) return
        val cur = tracks.value.toMutableList()
        for (work in works) {
            if (work.name.isBlank()) continue
            if (cur.any { it.song == work.name }) continue
            cur.add(TrackItem(song = work.name, artist = work.authorName))
        }
        tracks.value = cur
    }

    /** 记一首已评分的曲目（同一首歌只保留一行，批注后到就补上去）。 */
    fun addTrack(song: String, score: String, note: String = "", artist: String = "") {
        if (song.isBlank()) return
        val cur = tracks.value
        val index = cur.indexOfFirst { it.song == song }
        val item = if (index >= 0) {
            cur[index].copy(
                artist = if (artist.isNotBlank()) artist else cur[index].artist,
                score = score.ifBlank { cur[index].score },
                note = note.ifBlank { cur[index].note },
                state = TrackState.DONE,
            )
        } else {
            TrackItem(song = song, artist = artist, score = score, note = note, state = TrackState.DONE)
        }
        tracks.value = if (index >= 0) {
            cur.toMutableList().also { it[index] = item }
        } else {
            cur + item
        }
    }

    /** 改一首歌的状态（评分中 / 跳过 / 失败）；歌不在列表里就先补一行。 */
    fun setState(work: Work, state: String) {
        if (work.name.isBlank()) return
        val cur = tracks.value
        val index = cur.indexOfFirst { it.song == work.name }
        val item = if (index >= 0) {
            cur[index].copy(
                artist = cur[index].artist.ifBlank { work.authorName },
                state = state,
            )
        } else {
            TrackItem(song = work.name, artist = work.authorName, state = state)
        }
        tracks.value = if (index >= 0) {
            cur.toMutableList().also { it[index] = item }
        } else {
            cur + item
        }
    }

    /** 已提交的批注条数（页头那一行要用）。 */
    fun noteCount(): Int = tracks.value.count { it.note.isNotBlank() }

    /**
     * 一次执行结束时的收尾：把没跑完的行定下来。
     *
     * 之前的问题：今天已经评过歌了，点执行只跑完第一首就结束，但曲目表里
     * 第一首一直显示"评分中"、下面全挂着"待评"——看着像卡死。
     * 规则：正在评的按结果记「失败」或「跳过」；没轮到的记「跳过」。
     */
    fun settleQueue(failed: Boolean) {
        tracks.value = tracks.value.map { item ->
            when (item.state) {
                TrackState.RUNNING ->
                    item.copy(state = if (failed) TrackState.FAILED else TrackState.SKIPPED)
                TrackState.PENDING -> item.copy(state = TrackState.SKIPPED)
                else -> item
            }
        }
    }

    /** 已提交（已评分）的曲目数。 */
    fun doneCount(): Int = tracks.value.count { it.state == TrackState.DONE }
}
