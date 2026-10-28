package com.ncmp.mobile.data

/**
 * 批注文案模板库 + 生成器（从 `core/notes/templates.py` + `core/notes/generator.py`
 * 逐句移植：句池、骨架、截断规则都和桌面端一致）。
 *
 * 批注是**随评分一起提交到网易云的那句话**，会公开留在账号名下，
 * 所以这里的每一句都遵守两条底线：
 *
 * 1. **不编造听觉细节。** 程序没有听过这首歌，写"副歌前的留白用得很克制"
 *    就是凭空捏造。模板只允许谈听歌场景、整体判断和处置方式。
 * 2. **不喊口号。**"太好听了！""必须单曲循环！"这类句子是刷屏语，不是批注。
 *    批注要像内页上的一句手写批注：短、具体、克制。
 *
 * 三段式骨架（见 docs/DESIGN.md §6）：
 * 开场（听歌场景） → 判断（和档位对应） → 收尾（怎么处置）
 *
 * 手机端没有 LLM：`note_source = "llm"` 时也按 "template" 处理。
 */
object Notes {

    // ==================================================================
    // 语料
    // ==================================================================

    /** 开场：谈的是"我什么时候、为什么点开它"，不涉及音乐本身。三套语气共用。 */
    private val OPENERS = listOf(
        "通勤路上点开的，",
        "今天排到的一首，",
        "早上第一首，",
        "夜里放的，",
        "顺手点进来的，",
        "歌单翻到底才看到的，",
        "第一次听，",
        "列表里排在最后的那首，",
        "趁着空闲听的，",
        "等车的时候放完的，",
    )

    /** 判断：与评分的档位对应。写得越具体越像假话，所以只谈整体完成度。 */
    private val JUDGEMENTS = mapOf(
        "high" to listOf(
            "结构完整，该收的地方都收住了",
            "编排有分寸，没有为了热闹去堆东西",
            "铺得稳，听完不觉得空",
            "完成度比预期高，重复听也不腻",
            "整体是统一的，没有前后打架的地方",
            "该给的东西都给了，没有敷衍的地方",
        ),
        "mid" to listOf(
            "整体稳，但记不太住",
            "有几处想再展开一点，没铺开就收了",
            "编曲够用，记忆点少了些",
            "不难听，但听完想不起哪一句",
            "中规中矩，和歌名给的期待差不多",
            "底子是好的，差一点自己的东西",
        ),
        "low" to listOf(
            "和我预期的差得有点远",
            "编曲偏平，听到后半段就走神了",
            "制作上没问题，但没对上我的口味",
            "不是我会主动找的那一类",
            "该有的都有，只是没打动我",
            "听完的当下没什么感觉",
        ),
    )

    /** 收尾：给出处置方式。这是批注里最有信息量的一句。 */
    private val CLOSERS = listOf(
        "先放进歌单，改天再听一遍。",
        "适合晚上走路的时候放。",
        "就先这样，位置留着。",
        "留着，下次细听再来改。",
        "不算惊喜，但值得占一个位置。",
        "记下来了，回头再验证一次。",
        "放进常听列表，不着急定论。",
        "下次排到的时候再听一次。",
    )

    /** 热络：情绪更外露，但依然不描述音乐本身。 */
    private val WARM_JUDGEMENTS = mapOf(
        "high" to listOf(
            "听着很舒服，心情被照顾到了",
            "有些东西刚好接住了今天的情绪",
            "是愿意反复放的那一类",
            "听完会不自觉放慢手上的事",
            "整体很舒服，挑不出毛病",
        ),
        "mid" to listOf(
            "听着还行，情绪差一点到位",
            "有一小段挺好，其余记不住",
            "不难听，只是没留住我",
            "和今天的心情擦肩而过",
            "氛围是对的，内容少了点",
        ),
        "low" to listOf(
            "今天就当听个响",
            "情绪对不上，听着有点走神",
            "不是我此刻想听的声音",
            "差了点意思，听完没什么感觉",
            "没能把注意力拉过去",
        ),
    )

    private val WARM_CLOSERS = listOf(
        "存着，哪天心情对的时候再放一次。",
        "推荐给会喜欢这种调子的朋友。",
        "就放在列表里，慢慢听。",
        "先记一下，改天再来。",
        "留着，不着急下结论。",
    )

    /** 简短：一句话，不铺垫、不收尾。 */
    private val BRIEF_JUDGEMENTS = mapOf(
        "high" to listOf(
            "完成度挺高，值得留个位置。",
            "稳，没什么可挑的。",
            "该有的都有，听着舒服。",
            "比预期好，可以循环。",
        ),
        "mid" to listOf(
            "中规中矩，记住的不多。",
            "还行，但不算我的类型。",
            "听完就过了，不难听。",
            "差一点自己的东西。",
        ),
        "low" to listOf(
            "和预期差得远。",
            "不是我的口味，先放着。",
            "听得有点散，先跳过。",
            "没对上，就这样吧。",
        ),
    )

    // ==================================================================
    // 三套语气（D3，见 docs/DESIGN.md §8）
    // ==================================================================
    // 同一个默认语气服务所有人，结果就是谁都不像。但语气只能是"说话的松紧"，
    // 不能是"知道得更多"——第三套原叫"技术流"，写两句就发现它必须描述编曲和
    // 人声位置，而程序根本没听过这首歌，那就是编造。所以改成"简短"。

    val VOICES: List<String> = listOf("restrained", "warm", "brief")
    const val DEFAULT_VOICE = "restrained"

    val VOICE_LABELS: Map<String, String> = mapOf(
        "restrained" to "克制",
        "warm" to "热络",
        "brief" to "简短",
    )

    /** 不认识的语气回落默认，永远返回一个合法值。 */
    fun normalizeVoice(voice: String?): String {
        val value = (voice ?: "").trim().lowercase()
        return if (value in VOICES) value else DEFAULT_VOICE
    }

    /** 语气的中文名（设置页 chip 用）。 */
    fun voiceLabel(voice: String?): String = VOICE_LABELS.getValue(normalizeVoice(voice))

    // ==================================================================
    // 档位与句池
    // ==================================================================

    /** 分数 → 档位。无法解析时按中间档处理，不抛异常。 */
    fun tierForScore(score: String?): String {
        val value = score?.trim()?.toIntOrNull() ?: return "mid"
        return when {
            value >= 4 -> "high"
            value == 3 -> "mid"
            else -> "low"
        }
    }

    /** 开场句池：三套语气共用——它只是"什么时候点开的"，语气无关。 */
    fun openersFor(): List<String> = OPENERS

    /** 取某套语气的判断句池。voice 不认识就回落默认。 */
    fun judgementsFor(voice: String?, tier: String): List<String> =
        when (normalizeVoice(voice)) {
            "warm" -> WARM_JUDGEMENTS[tier] ?: WARM_JUDGEMENTS.getValue("mid")
            "brief" -> BRIEF_JUDGEMENTS[tier] ?: BRIEF_JUDGEMENTS.getValue("mid")
            else -> JUDGEMENTS[tier] ?: JUDGEMENTS.getValue("mid")
        }

    /** 取某套语气的收尾句池（简短语气没有收尾）。 */
    fun closersFor(voice: String?): List<String> =
        when (normalizeVoice(voice)) {
            "warm" -> WARM_CLOSERS
            "brief" -> emptyList()
            else -> CLOSERS
        }

    // ==================================================================
    // 本次运行的生成入口
    // ==================================================================

    /** 本次运行里已经用过的批注（跨歌曲去重，任务开始时清空）。 */
    private val used = mutableSetOf<String>()

    /**
     * 给一首歌生成一句批注（随评分一起提交到 `comment` 字段）。
     *
     * 禁用或任何异常都返回空字符串——批注失败不能拖垮评分。
     * 手机端没有 LLM，`noteSource = "llm"` 也走这里。
     */
    @Synchronized
    fun generate(
        work: Work,
        score: String,
        enabled: Boolean = true,
        voice: String = DEFAULT_VOICE,
        maxChars: Int = NoteGenerator.DEFAULT_MAX_CHARS,
    ): String = NoteGenerator(enabled, voice, maxChars, used).generate(work, score)

    /** 每次任务开始时清空"本次已用过的句子"，让重跑之间不互相影响。 */
    @Synchronized
    fun resetRun() {
        used.clear()
    }
}

/**
 * 按固定骨架拼一句批注。一次运行复用一个实例（或直接用 [Notes.generate]），
 * 内部只记「已经用过的句子」。
 *
 * 三条约束（与桌面端一致）：
 *
 * - **确定性**：同一首歌、同一个分数，永远生成同一句（种子取歌单标识与分数，
 *   不用随机数），重跑、补跑、预览和实际提交发出去的话一致。
 * - **永不抛异常**：任何异常都退化成空字符串（不写批注）。
 * - **不重复**：同一次运行里尽量不和已经用过的句子撞车；撞了换下一个 salt 重摇。
 */
class NoteGenerator(
    private val enabled: Boolean = true,
    private val voice: String = Notes.DEFAULT_VOICE,
    private val maxChars: Int = DEFAULT_MAX_CHARS,
    /** 跨歌曲去重的"已用句子"集合；不传就是这一实例自己的。 */
    private val used: MutableSet<String> = mutableSetOf(),
) {

    /** 长度上限：与桌面端一致，夹在 10~200 之间。 */
    val limit: Int get() = if (maxChars in 10..200) maxChars else DEFAULT_MAX_CHARS

    /** 为某首歌生成一句批注；禁用或失败时返回空字符串。 */
    fun generate(work: Work, score: String): String {
        if (!enabled) return ""
        return try {
            fromTemplate(work, score)
        } catch (_: Exception) {
            // 批注是锦上添花，绝不能因为它把评分流程搞挂
            ""
        }
    }

    /** 纯本地模板生成，确定性且不联网。 */
    fun fromTemplate(work: Work, score: String): String {
        var text = ""
        for (salt in 0 until MAX_REROLL) {
            val candidate = compose(seed(work, score, salt), score)
            if (candidate.isNotEmpty() && candidate !in used) {
                text = candidate
                break
            }
        }
        if (text.isEmpty()) {
            // 全撞车了就接受第一句，总比没有批注好
            text = compose(seed(work, score, 0), score)
        }
        val fitted = fit(text)
        used.add(fitted)
        return fitted
    }

    // ------------------------------------------------------------------
    // 内部
    // ------------------------------------------------------------------

    /**
     * 由歌曲标识与分数算出稳定种子（salt 用于重摇）。
     *
     * 桌面端用 `zlib.crc32`（无符号 32 位），这里用 `String.hashCode()`（有符号 32 位）；
     * 统一按 32 位无符号解释，保证后面取模、整除得到的下标非负。
     */
    private fun seed(work: Work, score: String, salt: Int): Long {
        val key = "${work.id}|${work.name}|${work.authorName}|$score|$salt"
        return key.hashCode().toLong() and 0xFFFFFFFFL
    }

    private fun pick(pool: List<String>, seed: Long): String =
        pool[(seed % pool.size).toInt()]

    private fun compose(seed: Long, score: String): String {
        val tier = Notes.tierForScore(score)
        val opener = pick(Notes.openersFor(), seed)
        val judgement = pick(Notes.judgementsFor(voice, tier), seed / 7)
        val closers = Notes.closersFor(voice)
        if (closers.isEmpty()) {
            // 简短语气：一句说完，不铺垫也不收尾
            return "$opener$judgement。"
        }
        val closer = pick(closers, seed / 31)
        return "$opener$judgement。$closer"
    }

    /** 把批注压到长度上限内：先丢收尾，再截断判断部分。 */
    private fun fit(text: String): String {
        val normalized = text.trim().split(WHITESPACE).joinToString(" ")
        val limit = this.limit
        if (normalized.length <= limit) return normalized
        // 优先保留前两段（开场 + 判断），收尾是最先可以牺牲的
        val parts = normalized.split("。")
        if (parts.size >= 2) {
            val kept = parts.dropLast(1).joinToString("。") + "。"
            if (kept.length <= limit) return kept
        }
        val head = normalized.take(maxOf(1, limit - 1)).trimEnd('，', '。')
        return "$head。"
    }

    companion object {
        /** 同一次运行里为避开重复句子最多重摇几次。 */
        private const val MAX_REROLL = 6

        /** 批注字数上限的默认值。 */
        const val DEFAULT_MAX_CHARS = 80

        private val WHITESPACE = Regex("\\s+")
    }
}

/** 一次性便捷入口：给一首歌生成一句批注（对应桌面端 `build_note`）。 */
fun buildNote(
    work: Work,
    score: String,
    enabled: Boolean = true,
    voice: String = Notes.DEFAULT_VOICE,
    maxChars: Int = NoteGenerator.DEFAULT_MAX_CHARS,
): String = NoteGenerator(enabled, voice, maxChars).generate(work, score)
