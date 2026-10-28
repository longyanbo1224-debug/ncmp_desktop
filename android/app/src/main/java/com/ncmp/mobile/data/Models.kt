package com.ncmp.mobile.data

/** 待评分作品。id/resourceId 保留接口返回的原始类型（数字/字符串）。 */
data class Work(
    val id: Any,
    val name: String,
    val authorName: String,
    val resourceId: Any,
)

data class WorkItem(val work: Work, val completed: Boolean)

/** 单曲状态（用词见 docs/DESIGN.md §6，不得混用同义词）。 */
object TrackState {
    const val PENDING = "pending"   // 待评
    const val RUNNING = "running"   // 评分中
    const val DONE = "done"         // 已提交
    const val SKIPPED = "skipped"   // 跳过
    const val FAILED = "failed"     // 失败
}

/**
 * 曲目表里的一行：今天评过的某首歌，以及留在它下面的那句批注。
 *
 * 按歌名去重（桌面端曲目表同样按歌名索引）：一天的歌单里不会有两首同名。
 */
data class TrackItem(
    val song: String,
    val artist: String = "",
    val score: String = "",
    val note: String = "",
    val state: String = TrackState.PENDING,
)

data class DailyTasks(
    val id: Any,
    val count: Int,
    val completedCount: Int,
    val items: List<WorkItem>,
) {
    val complete: Boolean get() = count == completedCount
    val pending: List<Work> get() = items.filter { !it.completed }.map { it.work }
}

data class TaskConfig(
    val scoreStrategy: Int = 3,          // 1=1-2分 2=2-3分 3=3-4分 4=固定4分
    val waitMinSeconds: Double = 15.0,
    val waitMaxSeconds: Double = 20.0,
    val fullExtraTasks: Boolean = true,
    // 批注（乐评文案）：随评分一起提交到 comment 字段
    val noteEnabled: Boolean = true,
    /** template（默认）| llm。手机端没有 LLM，传 llm 也按 template 处理。 */
    val noteSource: String = "template",
    val noteVoice: String = Notes.DEFAULT_VOICE, // restrained | warm | brief
    val noteMaxChars: Int = NoteGenerator.DEFAULT_MAX_CHARS,
)

sealed class TaskResult {
    data class Success(
        val base: Int,
        val extra: Int,
        val extraAllDone: Boolean = false,
    ) : TaskResult()
    data class Cancelled(val base: Int, val extra: Int) : TaskResult()
    data class Failed(
        val error: Throwable,
        val kind: FailureKind,
        val hint: String,
        val base: Int,
        val extra: Int,
    ) : TaskResult()
}

enum class FailureKind(val label: String) {
    COOKIE("Cookie 失效"),
    RISK("风控拦截"),
    NETWORK("网络异常"),
    API("接口返回错误"),
    UNKNOWN("未知错误"),
}

data class LoginResult(
    val success: Boolean,
    val code: Int?,
    val message: String,
    val musicU: String? = null,
    val csrf: String? = null,
) {
    companion object {
        fun success(musicU: String?, csrf: String?) =
            LoginResult(true, 200, "登录成功", musicU, csrf)

        fun failure(message: String, code: Int? = null) =
            LoginResult(false, code, message)
    }
}

data class QrStatus(val code: Int, val musicU: String?, val csrf: String?)
