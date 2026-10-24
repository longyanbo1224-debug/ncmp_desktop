package com.ncmp.mobile.data

import kotlinx.coroutines.flow.MutableStateFlow

/** 任务状态的中转站：前台服务写入，界面观察。 */
object TaskBus {
    val running = MutableStateFlow(false)
    val logs = MutableStateFlow<List<String>>(emptyList())
    val done = MutableStateFlow(0)
    val total = MutableStateFlow(0)
    val song = MutableStateFlow("")
    val step = MutableStateFlow("")
    val resultLabel = MutableStateFlow("")
    val resultHint = MutableStateFlow("")
    val resultIsError = MutableStateFlow(false)

    fun reset() {
        logs.value = emptyList()
        done.value = 0
        total.value = 0
        song.value = ""
        step.value = ""
        resultLabel.value = ""
        resultHint.value = ""
        resultIsError.value = false
    }

    fun append(line: String) {
        val cur = logs.value
        logs.value = (cur + line).let { if (it.size > 500) it.takeLast(500) else it }
    }
}
