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
/** 服务端 405「今日没有更多可评定歌曲」：当天已没有可评的歌，不是额度异常。 */
class NoMoreWorksException(message: String) : RuntimeException(message)

/** 每天额外任务的固定上限（基础 5 + 额外 15 = 20 首）。 */
private const val EXTRA_DAILY_MAX = 15

class TaskRunner(
    private val api: NeteaseApi,
    private val config: TaskConfig,
    private val log: (String) -> Unit,
    private val onStep: (String, String) -> Unit,
    private val onProgress: (Int, Int, String, String) -> Unit,
    private val onPercent: (Int) -> Unit,
    // callback(song, score, note)：批注提交成功后通知界面
    private val onNote: (String, String, String) -> Unit = { _, _, _ -> },
    // callback(works)：今日待评队列，先把曲目行"待评"地摆出来
    private val onQueue: (List<WorkItem>) -> Unit = {},
    // callback(work, state)：单曲状态变化（评分中 / 跳过 / 失败）
    private val onTrack: (Work, String) -> Unit = { _, _ -> },
    // callback(points)：任务结束后查到的合伙人积分/等级（拿不到就不回调）
    private val onPoints: (Map<String, String>) -> Unit = {},
    // 本地评分账本：同一任务重跑时不再提交已评过的歌
    private val ledger: RatingLedgerStore? = null,
) {
    @Volatile var cancelled = false
    private var currentStep = ""
    private var currentPhase = ""
    private var percent = 0
    private var baseDone = 0
    private var extraDone = 0
    private var extraAllDone = false
    //: 整轮已发出的真实评分请求数：第一次不等，之后每次请求前等一次
    private var requestsSent = 0

    // 阶段在全局进度里的区间（移植自桌面端 task_page.py）。
    // 两个评分阶段在 8~100 之间按条目数分配，见 planScoring。
    private val spans = mutableMapOf(
        "验证用户信息" to (0 to 2),
        "拉取每日任务" to (2 to 8),
        "评分基础任务" to (8 to 30),
        "额外评分任务" to (30 to 100),
    )

    suspend fun run(): TaskResult {
        baseDone = 0
        extraDone = 0
        extraAllDone = false
        requestsSent = 0
        Notes.resetRun()
        if (config.noteSource.equals("llm", ignoreCase = true)) {
            // 手机端没有 LLM：选了 llm 也走本地模板，说清楚比悄悄回落好
            log("手机端不接 LLM，批注仍用本地模板生成")
        }
        try {
            checkCancel()
            step("验证用户信息", "running")
            val nickname = api.verifyUser()
            step("验证用户信息", "success")
            log("用户名: $nickname")

            checkCancel()
            step("拉取每日任务", "running")
            val daily = api.getDailyTasks()
            // 服务端已完成的（含另一台设备评的）计入今日结果，并记进本地账本
            baseDone = daily.items.count { it.completed }
            rememberCompleted(daily.id, daily.items)
            log("今日任务：${if (daily.complete) "已完成" else "未完成"}[$baseDone/${daily.count}]")
            step("拉取每日任务", "success")
            // 额外清单先拉好，再和基础任务一起**一次性**摆进曲目表：
            // 分两次 onQueue 会让界面先闪 5 首再跳到 15 首。
            // 额外清单接口会把当天基础任务也列在等待评分的作品里。
            // 基础 5 首由基础阶段负责，先按 id / 歌名剔除，避免：
            // 1) 曲目表被额外的 15 首上限裁成 15 行（本应基础 5 + 额外 15 = 20 行）
            // 2) 基础曲目占掉额外的每日额度
            val (baseIds, baseNames) = baseKeys(daily.items)
            val preloadedExtra = runCatching { api.getExtraTasks() }.getOrNull()
            val extraItems = preloadedExtra?.let {
                filterExtraItems(it.first, baseIds, baseNames)
            }
            val extraCompleted = extraItems?.count { it.completed } ?: 0
            extraItems?.let { rememberCompleted(daily.id, it) }
            onQueue(daily.items + extraItems.orEmpty())

            if (!daily.complete) {
                checkCancel()
                step("评分基础任务", "running")
                rateWorks(daily.id, daily.pending)
                step("评分基础任务", "success")
            }

            checkCancel()
            step("额外评分任务", "running")
            processExtra(
                daily.id,
                extraItems?.let { it to extraCompleted },
                baseIds,
                baseNames,
            )
            step("额外评分任务", "success")

            // 顺手查一次积分/等级（拿不到就什么都不发，界面不显示）
            runCatching { api.getPartnerPoints() }.getOrNull()
                ?.takeIf { it.isNotEmpty() }
                ?.let(onPoints)

            return TaskResult.Success(baseDone, extraDone, extraAllDone)
        } catch (e: CancellationException) {
            step(currentStep, "cancelled")
            log("任务已取消")
            return TaskResult.Cancelled(baseDone, extraDone)
        } catch (e: Exception) {
            log("执行失败: ${e.message}")
            step(currentStep, "failed")
            val (kind, hint) = classify(e)
            return TaskResult.Failed(e, kind, hint, baseDone, extraDone)
        }
    }

    private fun step(name: String, status: String) {
        currentStep = name
        onStep(name, status)
        val span = spans[name] ?: return
        when (status) {
            "running" -> {
                currentPhase = name
                advance(span.first)
            }
            // 取消不推到阶段终点：进度条应该停在用户按下取消的那一刻
            "success", "failed" -> {
                advance(span.second)
                if (currentPhase == name) currentPhase = ""
            }
            "cancelled" -> {
                if (currentPhase == name) currentPhase = ""
            }
        }
    }

    /** 全局进度只前进不后退；补跑阶段不会把进度条拉回去。 */
    private fun advance(pct: Int) {
        val v = pct.coerceIn(0, 100)
        if (v > percent) {
            percent = v
            onPercent(v)
        }
    }

    /** 把本阶段的 done/total 映射到本阶段区间内。 */
    private fun phaseProgress(done: Int, total: Int) {
        val span = spans[currentPhase] ?: return
        if (total <= 0) return
        val frac = (done.toFloat() / total).coerceIn(0f, 1f)
        advance((span.first + (span.second - span.first) * frac).roundToInt())
    }

    /** 按条目数把 8~100 分给基础和额外两个评分阶段（与桌面端同一算法）。 */
    private fun planScoring(baseTotal: Int) {
        if (baseTotal <= 0) return
        val extraEst = if (!config.fullExtraTasks) 7 else baseTotal * 3
        if (extraEst <= 0) return
        val spanSize = 100 - 8
        val baseHi = (8 + spanSize * baseTotal.toFloat() / (baseTotal + extraEst))
            .roundToInt()
            .coerceIn(9, 99)
        spans["评分基础任务"] = 8 to baseHi
        spans["额外评分任务"] = baseHi to 100
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

    /** 把服务端已完成的曲目记进账本：下次同一任务里标记滞后也不会再提交。 */
    private fun rememberCompleted(taskId: Any, items: List<WorkItem>) {
        val store = ledger ?: return
        val account = api.userId
        for (item in items) {
            if (!item.completed || item.score.isBlank()) continue
            store.mark(account, taskId, item.work.id, item.score)
        }
    }

    private suspend fun rateWorks(taskId: Any, pending: List<Work>) {
        if (pending.isEmpty()) {
            log("没有待评分作品")
            return
        }
        log("开始评分...")
        var done = 0
        val total = pending.size
        // 服务端已完成的基础曲目已经计入 baseDone；阶段进度仍从 0 开始
        val baseBefore = baseDone
        planScoring(total)
        // 今日曲目在 run() 拉完每日任务时已经整体摆进曲目表（含已评过的），
        // 这里不再重复摆一遍。
        onProgress(0, total, "", "")
        phaseProgress(0, total)
        for (work in pending) {
            checkCancel()
            try {
                sign(work, taskId, isExtra = false) { w, score ->
                    done++
                    baseDone = baseBefore + done
                    onProgress(done, total, w.name, score)
                    phaseProgress(done, total)
                }
            } catch (e: NoMoreWorksException) {
                log("今日已没有更多可评定歌曲，停止基础评分")
                break
            }
        }
    }

    private suspend fun sign(work: Work, taskId: Any, isExtra: Boolean, onScored: (Work, String) -> Unit): Boolean {
        checkCancel()
        // 本任务已由服务端确认收下：不再发评分请求，按已评推进
        val cached = ledger?.score(api.userId, taskId, work.id)
        if (cached != null) {
            log("${work.name}「${work.authorName}」本任务已评过（本地记录 $cached 分），跳过重复提交")
            onScored(work, cached)
            return true
        }
        onTrack(work, TrackState.RUNNING)
        // 只在两次真实请求之间等待：前面几首都已评过时，第一首真正要评的歌直接开始
        if (requestsSent > 0) {
            val delaySec = randomWait()
            log("等待 %.1f 秒后继续...".format(delaySec))
            sleepCancellable(delaySec)
        }
        requestsSent++

        val score = scoreFor(work)
        val tag = "$score-A-1"
        // 批注随评分一次提交；noteEnabled 关闭时为空串（等同于旧版行为）
        val comment = Notes.generate(
            work = work,
            score = score,
            enabled = config.noteEnabled,
            voice = config.noteVoice,
            length = config.noteLength,
            maxChars = config.noteMaxChars,
        )
        val data = JSONObject().apply {
            put("taskId", taskId)
            put("workId", work.id)
            put("score", score)
            put("tags", tag)
            put("customTags", "%5B%5D")
            put("comment", comment)
            put("syncYunCircle", "true")
            if (isExtra) put("extraResource", "true")
        }

        var attempt = 0
        while (true) {
            attempt++
            val resp = try {
                api.weapiPost(NeteaseApi.SCORE_URL, data)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // 写入结果不明（超时/断连/响应不是 JSON）：只查一次服务端，
                // 确认到了就按成功处理，确认不到再报错。**绝不重投评分**——
                // 超时不代表服务端没收到，重投就是重复评分。
                if (api.isWorkRated(work.id, isExtra)) {
                    log("${work.name} 提交结果不明，但服务端已记录这次评分，按成功处理")
                    ledger?.mark(api.userId, taskId, work.id, score)
                    onScored(work, score)
                    if (comment.isNotEmpty()) {
                        log("批注已提交：$comment")
                        onNote(work.name, score, comment)
                    }
                    return true
                }
                throw e
            }
            val code = resp.optInt("code", -1)
            if (code == 200) {
                log("${work.name}「${work.authorName}」评分完成：${score}分")
                ledger?.mark(api.userId, taskId, work.id, score)
                onScored(work, score)
                // 批注单独一条日志 + 单独回调：界面靠它把"留下了什么话"落到曲目行上
                if (comment.isNotEmpty()) {
                    log("批注已提交：$comment")
                    onNote(work.name, score, comment)
                }
                return true
            }
            val msg = resp.optString("message", resp.optString("msg", "未知错误"))
            when {
                msg.contains("频繁") && attempt < 3 -> {
                    val retry = randomWait()
                    log("遇到频率限制，等待 %.1f 秒后重试（第 $attempt 次）...".format(retry))
                    sleepCancellable(retry)
                }
                code == 405 && msg.contains("资源状态异常") -> {
                    log("歌曲「${work.name}」资源状态异常，跳过（服务端未记下这次评分）")
                    onTrack(work, TrackState.SKIPPED)
                    return false
                }
                code == 405 && msg.contains("没有更多") -> {
                    // 今天没有可评的歌了：这是完成信号，不是额度异常
                    throw NoMoreWorksException(msg)
                }
                else -> {
                    onTrack(work, TrackState.FAILED)
                    throw RuntimeException("评分失败: $msg (响应码: $code)")
                }
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

    private suspend fun processExtra(
        taskId: Any,
        preloaded: Pair<List<WorkItem>, Int>? = null,
        baseIds: Set<String> = emptySet(),
        baseNames: Set<String> = emptySet(),
    ) {
        val fetched = preloaded ?: api.getExtraTasks().let { (items, _) ->
            val kept = filterExtraItems(items, baseIds, baseNames)
            kept to kept.count { it.completed }
        }
        var completedCount = fetched.second
        // 本轮开始前服务端已完成的额外曲目：计入今日结果，也补进本地账本
        val extraBefore = completedCount
        extraDone = extraBefore
        rememberCompleted(taskId, fetched.first)
        var uncompleted = fetched.first.filter { !it.completed }
        // 整份清单都摆进曲目表（含已评的）：今天已经评完时，这里至少看得见评过哪些歌
        onQueue(fetched.first)
        val full = config.fullExtraTasks
        val dailyLimit = if (full) EXTRA_DAILY_MAX else 7
        val maxNew = (dailyLimit - extraBefore).coerceAtLeast(0)
        var target = minOf(uncompleted.size, maxNew)

        if (uncompleted.isEmpty()) {
            log("额外评定完成数: $completedCount")
            extraAllDone = true
            return
        }
        if (target <= 0) {
            log("今日已完成 $completedCount 个额外评分任务，已达到每日上限")
            return
        }
        log("发现 ${uncompleted.size} 个待额外评定任务")

        var success = 0
        // 被服务端拒绝（资源状态异常）的歌：要能告诉用户"缺的是哪首"
        val skipped = mutableListOf<String>()
        // 本轮已被服务端明确拒绝的作品：补跑轮别再请求同一首
        val rejected = mutableSetOf<String>()
        onProgress(0, target, "", "")
        phaseProgress(0, target)
        var noMore = false
        for (pass in 0 until 2) {
            if (success >= target) break
            if (pass > 0) {
                // 单首失败只会跳过，整轮跑完重新核对一次，把漏掉的补上
                val refreshed = try {
                    api.getExtraTasks()
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    log("补跑检查失败，结束额外评分: ${e.message}")
                    break
                }
                val refreshedItems = filterExtraItems(
                    refreshed.first, baseIds, baseNames,
                )
                uncompleted = refreshedItems.filter { !it.completed }
                completedCount = refreshedItems.count { it.completed }
                rememberCompleted(taskId, refreshedItems)
                // 服务端分批返回：先把新一批整份摆进曲目表，再去评分，
                // 不要等评到哪首才冒出一行
                onQueue(refreshedItems)
                target = minOf(maxNew, maxOf(target, success + uncompleted.size))
                if (uncompleted.isEmpty() || success >= target) {
                    log("补跑检查：没有剩余额外任务")
                    break
                }
                log("补跑检查：还有 ${target - success} 个额外任务未完成")
            }
            for (item in uncompleted) {
                if (success >= target) break
                checkCancel()
                val work = item.work
                val workKey = work.id.toString()
                if (workKey in rejected) {
                    // 上一轮服务端已明确拒绝，重复执行也不会成功
                    continue
                }
                try {
                    // 本任务已确认收下的，连听歌上报都不用再发
                    if (ledger?.score(api.userId, taskId, work.id) == null) {
                        api.reportListen(work)
                        log("歌曲 ${work.name} 听歌记录上报成功")
                    }
                    val rated = sign(work, taskId, isExtra = true) { w, score ->
                        success++
                        extraDone = extraBefore + success
                        onProgress(success, target, w.name, score)
                        phaseProgress(success, target)
                    }
                    if (!rated) {
                        // 服务端没接受这首：不算成功，重试也不会成功，记下来告诉用户
                        rejected.add(workKey)
                        skipped.add(work.name)
                        log("「${work.name}」未评上，先跳过")
                        continue
                    }
                    log("成功完成第 $success/$target 个额外评分任务")
                    // 等待节奏由 sign() 在两次真实请求之间统一控制，这里不再重复等
                } catch (e: CancellationException) {
                    throw e
                } catch (e: NoMoreWorksException) {
                    log("今日已没有更多可评定歌曲，额外任务今日已全部完成")
                    noMore = true
                    break
                } catch (e: Exception) {
                    log("处理歌曲 ${work.name} 失败，尝试下一个: ${e.message}")
                }
            }
            if (noMore) break
        }
        extraDone = extraBefore + success
        if (noMore) {
            // 服务端已经没有可评的歌了：这是完成，不是"还有 N 个没完成"，也不再补跑
            extraAllDone = true
            return
        }
        if (success < target) {
            val names = if (skipped.isEmpty()) "" else "：${skipped.joinToString("、")}"
            log(
                "检查后仍有 ${target - success} 个额外评分任务未完成$names" +
                    "（服务端拒绝的作品，重复执行也不会成功）",
            )
        } else {
            log("额外评分任务处理完成，成功评分 $success 首")
        }
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
