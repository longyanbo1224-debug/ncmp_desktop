package com.ncmp.mobile.data

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import org.json.JSONObject
import java.io.IOException
import kotlin.math.roundToInt
import kotlin.random.Random

/**
 * 音乐合伙人任务编排（从 core/bot.py + core/signer.py + core/tasks 目录逐行移植）。
 *
 * 流程：验证用户 -> 每日签到 -> 拉取每日任务 -> 评分基础任务 -> 额外评分任务。
 */
class TaskRunner(
    private val api: NeteaseApi,
    private val config: TaskConfig,
    private val log: (String) -> Unit,
    private val onStep: (String, String) -> Unit,
    private val onProgress: (Int, Int, String, String) -> Unit,
) {
    @Volatile var cancelled = false
    private var currentStep = ""

    suspend fun run(): TaskResult {
        try {
            checkCancel()
            step("验证用户信息", "running")
            val nickname = api.verifyUser()
            step("验证用户信息", "success")
            log("用户名: $nickname")

            checkCancel()
            step("拉取每日任务", "running")
            val daily = api.getDailyTasks()
            log("今日任务：${if (daily.complete) "已完成" else "未完成"}[${daily.completedCount}/${daily.count}]")
            step("拉取每日任务", "success")

            if (!daily.complete) {
                checkCancel()
                step("评分基础任务", "running")
                rateWorks(daily.id, daily.pending)
                step("评分基础任务", "success")
            }

            checkCancel()
            step("额外评分任务", "running")
            processExtra(daily.id)
            step("额外评分任务", "success")

            return TaskResult.Success
        } catch (e: CancellationException) {
            step(currentStep, "cancelled")
            log("任务已取消")
            return TaskResult.Cancelled
        } catch (e: Exception) {
            log("执行失败: ${e.message}")
            step(currentStep, "failed")
            val (kind, hint) = classify(e)
            return TaskResult.Failed(e, kind, hint)
        }
    }

    private fun step(name: String, status: String) {
        currentStep = name
        onStep(name, status)
    }

    private suspend fun checkCancel() {
        currentCoroutineContext().ensureActive()
        if (cancelled) throw CancellationException("用户取消任务")
    }

    private suspend fun sleepCancellable(seconds: Double) {
        var remaining = (seconds * 1000).roundToInt()
        while (remaining > 0) {
            checkCancel()
            val slice = minOf(remaining, 1000)
            delay(slice.toLong())
            remaining -= slice
        }
    }

    private fun randomWait(): Double {
        val min = config.waitMinSeconds.coerceAtLeast(0.0)
        val max = config.waitMaxSeconds.coerceAtLeast(min)
        return if (max == min) min else Random.nextDouble(min, max)
    }

    private suspend fun rateWorks(taskId: Any, pending: List<Work>) {
        if (pending.isEmpty()) {
            log("没有待评分作品")
            return
        }
        log("开始评分...")
        var done = 0
        val total = pending.size
        onProgress(0, total, "", "")
        for (work in pending) {
            checkCancel()
            sign(work, taskId, isExtra = false) { w, score ->
                done++
                onProgress(done, total, w.name, score)
            }
        }
    }

    private suspend fun sign(work: Work, taskId: Any, isExtra: Boolean, onScored: (Work, String) -> Unit) {
        checkCancel()
        val delaySec = randomWait()
        log("等待 %.1f 秒后继续...".format(delaySec))
        sleepCancellable(delaySec)

        val score = scoreFor(work)
        val tag = "$score-A-1"
        val data = JSONObject().apply {
            put("taskId", taskId)
            put("workId", work.id)
            put("score", score)
            put("tags", tag)
            put("customTags", "%5B%5D")
            put("comment", "")
            put("syncYunCircle", "true")
            if (isExtra) put("extraResource", "true")
        }

        var attempt = 0
        while (true) {
            attempt++
            val resp = api.weapiPost(NeteaseApi.SCORE_URL, data)
            val code = resp.optInt("code", -1)
            if (code == 200) {
                log("${work.name}「${work.authorName}」评分完成：${score}分")
                onScored(work, score)
                return
            }
            val msg = resp.optString("message", resp.optString("msg", "未知错误"))
            when {
                msg.contains("频繁") && attempt < 3 -> {
                    val retry = randomWait()
                    log("遇到频率限制，等待 %.1f 秒后重试（第 $attempt 次）...".format(retry))
                    sleepCancellable(retry)
                }
                code == 405 && msg.contains("资源状态异常") -> {
                    log("歌曲「${work.name}」资源状态异常，跳过")
                    return
                }
                else -> throw RuntimeException("评分失败: $msg (响应码: $code)")
            }
        }
    }

    private fun scoreFor(work: Work): String {
        val hasEnglish = Regex("[a-zA-Z]").containsMatchIn(work.name + work.authorName)
        return when (config.scoreStrategy) {
            1 -> if (hasEnglish) "2" else "1"
            2 -> if (hasEnglish) "3" else "2"
            3 -> if (hasEnglish) "4" else "3"
            else -> "4"
        }
    }

    private suspend fun processExtra(taskId: Any) {
        val (uncompleted, completedCount) = api.getExtraTasks()
        val totalTasks = if (!config.fullExtraTasks) 7 else uncompleted.size + completedCount

        if (completedCount >= totalTasks) {
            log("今日已完成 $completedCount 个额外评分任务，已达到每日上限")
            return
        }
        if (uncompleted.isEmpty()) {
            log("额外评定完成数: $completedCount")
            return
        }
        log("发现 ${uncompleted.size} 个待额外评定任务")

        val remaining = totalTasks - completedCount
        var success = 0
        onProgress(0, remaining, "", "")
        for (item in uncompleted) {
            if (success >= remaining) break
            checkCancel()
            val work = item.work
            try {
                api.reportListen(work)
                log("歌曲 ${work.name} 听歌记录上报成功")
                sign(work, taskId, isExtra = true) { w, score ->
                    success++
                    onProgress(success, remaining, w.name, score)
                }
                log("成功完成第 $success/$remaining 个额外评分任务")
                if (success < remaining) {
                    val delaySec = randomWait()
                    log("等待 %.1f 秒后继续...".format(delaySec))
                    sleepCancellable(delaySec)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                log("处理歌曲 ${work.name} 失败，尝试下一个: ${e.message}")
            }
        }
        log("额外评分任务处理完成，成功评分 $success 首")
    }
}

// ----------------------------------------------------------------------
// 失败原因分类（从 core/utils/errors.py 移植）
// ----------------------------------------------------------------------

private val CODE_RE = Regex("响应码[:：]\\s*(-?\\d+)")

private val NETWORK_KEYWORDS = listOf(
    "timeout", "timed out", "connection", "max retries", "unreachable",
    "name resolution", "proxy", "ssl", "network", "网络", "超时", "连接",
    "failed to connect", "connectexception", "socketexception",
)
private val RISK_KEYWORDS = listOf(
    "风控", "频繁", "操作过于", "限制", "异常流量", "安全验证", "验证码", "cheat", "risk",
)
private val COOKIE_KEYWORDS = listOf(
    "需要登录", "未登录", "登录已过期", "登录失效", "登录状态",
    "cookie", "获取用户信息失败", "认证", "鉴权",
)
private val RISK_CODES = setOf("-460", "-461", "-462", "8821")
private val COOKIE_CODES = setOf("301", "-2", "-10", "250")

fun classify(e: Throwable): Pair<FailureKind, String> {
    val text = throwableChainText(e).lowercase()
    val codes = CODE_RE.findAll(text).map { it.groupValues[1] }.toSet()

    return when {
        // 1. 网络类优先：包装过的消息里可能同时含"验证用户信息"和网络错误原文
        NETWORK_KEYWORDS.any { it in text } ->
            FailureKind.NETWORK to "网络不通或超时。检查网络后重试；如果开着代理或 VPN，关掉再试一次。"
        codes.any { it in RISK_CODES } || RISK_KEYWORDS.any { it in text } ->
            FailureKind.RISK to "网易限制了请求频率。别马上重试——把「等待时间」调大一点，或者换个时间再跑。"
        codes.any { it in COOKIE_CODES } || COOKIE_KEYWORDS.any { it in text } ->
            FailureKind.COOKIE to "Cookie 已失效，回到登录页重新扫码 / 密码登录即可恢复。"
        codes.isNotEmpty() ->
            FailureKind.API to "网易接口返回了非预期结果。稍后重试；如果反复出现，把下方日志附上反馈。"
        else ->
            FailureKind.UNKNOWN to "查看下方日志，里面有具体的报错原文。"
    }
}

private fun throwableChainText(e: Throwable): String {
    val parts = mutableListOf<String>()
    var cur: Throwable? = e
    while (cur != null) {
        parts.add(cur.message ?: cur.toString())
        cur = cur.cause
    }
    return parts.joinToString(" ")
}
