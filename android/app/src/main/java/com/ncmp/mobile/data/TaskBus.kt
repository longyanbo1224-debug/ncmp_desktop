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
        resultLabel.value = ""
        resultHint.value = ""
        resultSummary.value = ""
        resultIsError.value = false
    }

    fun append(line: String) {
        val cur = logs.value
        logs.value = (cur + line).let { if (it.size > 500) it.takeLast(500) else it }
    }
}
