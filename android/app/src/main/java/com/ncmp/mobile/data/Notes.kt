package com.ncmp.mobile.data

/**
 * 批注（乐评文案）生成器 —— 与桌面端 `core/notes/templates.py` 逐句一致。
 *
 * 两条底线（改语料时别破坏它们）：
 *  1. 不编造听觉细节。程序没有听过这首歌，写"副歌前的留白用得很克制"就是凭空捏造；
 *     只允许谈听歌场景、整体完成度的判断、以及怎么处置。
 *  2. 不喊口号。"太好听了""必须单曲循环"是刷屏语，不是批注。
 *
 * 为了不"每句都像同一个模子"，语料分三段（开场 / 判断 / 收尾），并且允许四种排法：
 * 三段全用、省掉收尾、省掉开场、只留判断。排法由同一颗种子决定，
 * 所以同一首歌、同一个分数永远生成同一句。
 *
 * `{name}` 会被替换成歌名；拿不到歌名时，含占位符的句子会被跳过。
 */
object Notes {

    val VOICES = listOf("restrained", "warm", "brief")
    const val DEFAULT_VOICE = "restrained"

    val VOICE_LABELS = mapOf(
        "restrained" to "克制",
        "warm" to "热络",
        "brief" to "简短",
    )

    /** 四种排法：三段全用 / 省收尾 / 省开场 / 只留判断。 */
    val FORMATS = listOf("full", "no_closer", "no_opener", "single")

    /** 长度档 → 字数上限（与桌面端 LENGTHS 一致） */
    val LENGTHS = mapOf("brief" to 40, "standard" to 80, "detailed" to 120)
    const val DEFAULT_LENGTH = "standard"

    fun normalizeLength(length: String?): String =
        if (length != null && length in LENGTHS) length else DEFAULT_LENGTH

    fun normalizeVoice(voice: String?): String =
        if (voice != null && voice in VOICES) voice else DEFAULT_VOICE

    fun voiceLabel(voice: String?): String =
        VOICE_LABELS[normalizeVoice(voice)] ?: VOICE_LABELS.getValue(DEFAULT_VOICE)

    // ==================================================================
    // 语料
    // ==================================================================

    /** 开场：谈的是"我什么时候、为什么点开它"，不涉及音乐本身。 */
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
        "睡前随手点开的，",
        "午休时放的，",
        "洗碗的时候听的，",
        "挂着当背景音听的，",
        "从推荐位点进去的，",
        "上一首放完自动接着放的，",
        "加班时放的，",
        "走路回家路上听的，",
        "翻旧列表翻到的，",
    )

    private val JUDGEMENTS = mapOf(
        "high" to listOf(
            "结构完整，该收的地方都收住了",
            "编排有分寸，没有为了热闹去堆东西",
            "铺得稳，听完不觉得空",
            "完成度比预期高，重复听也不腻",
            "整体是统一的，没有前后打架的地方",
            "该给的东西都给了，没有敷衍的地方",
            "起承转合是清楚的，不是拼起来的",
            "有自己的想法，而且守得住",
            "分寸感好，知道什么时候该停",
            "听过一遍还想再放一遍",
            "前后接得上，不是凑时长",
            "收得干净，没有拖尾巴",
        ),
        "mid" to listOf(
            "整体稳，但记不太住",
            "有几处想再展开一点，没铺开就收了",
            "编曲够用，记忆点少了些",
            "不难听，但听完想不起哪一句",
            "中规中矩，和歌名给的期待差不多",
            "底子是好的，差一点自己的东西",
            "每部分都对，合起来少点惊喜",
            "听着顺，但没有哪一段让我停下来",
            "完成度是够的，只是不太勾人",
            "每段单拎出来都还行，合起来不够紧",
            "该有的都有，串起来不够紧",
            "听得下去，但不会主动再点",
        ),
        "low" to listOf(
            "和我预期的差得有点远",
            "编曲偏平，听到后面就走神了",
            "制作上没问题，但没对上我的口味",
            "不是我会主动找的那一类",
            "该有的都有，只是没打动我",
            "听完的当下没什么感觉",
            "听完一遍，没有想再点的冲动",
            "听着有点累，中途想切歌",
            "想法是有的，落得不太稳",
            "和我对这类作品的期待不在一处",
            "平静听完，没有起伏",
            "听完了，但没留下什么",
        ),
    )

    private val CLOSERS = listOf(
        "先放进歌单，改天再听一遍。",
        "适合晚上走路的时候放。",
        "就先这样，位置留着。",
        "留着，下次细听再来改。",
        "不算惊喜，但值得占一个位置。",
        "记下来了，回头再验证一次。",
        "放进常听列表，不着急定论。",
        "下次排到的时候再听一次。",
        "《{name}》先放着，改天再说。",
        "暂时不进循环，留着当备选。",
        "这一首先记下，不作结论。",
        "给它一次重听的机会。",
        "存进列表，过一阵再看还对不对。",
        "就这样放着，什么时候想听再点。",
    )

    // 热络：情绪更外露，但依然不描述音乐本身
    private val WARM_JUDGEMENTS = mapOf(
        "high" to listOf(
            "听着很舒服，心情被照顾到了",
            "有些东西刚好接住了今天的情绪",
            "是愿意反复放的那一类",
            "听完会不自觉放慢手上的事",
            "整体很舒服，挑不出毛病",
            "愿意把它推给同样爱听歌的人",
            "这种东西听一次就记住了",
            "放完会想再点一遍",
            "刚好合今天的心气",
            "听的时候不想干别的",
        ),
        "mid" to listOf(
            "听着还行，情绪差一点到位",
            "有一小段挺好，其余记不住",
            "不难听，只是没留住我",
            "和今天的心情擦肩而过",
            "氛围是对的，内容少了点",
            "听完心情没变化，也不算白听",
            "有点可惜，差一口气",
            "听的时候舒服，听完就忘了",
            "能听，但不会到处推荐",
            "热度过了之后大概不会再点",
        ),
        "low" to listOf(
            "今天就当听个响",
            "情绪对不上，听着有点走神",
            "不是我此刻想听的声音",
            "差点意思，听完没什么感觉",
            "没能把注意力拉过去",
            "放了半首就想换了",
            "不是今天想听的那种",
            "听完没有想说什么的冲动",
            "和我之间隔着一层",
            "就这样吧，不强求",
        ),
    )

    private val WARM_CLOSERS = listOf(
        "存着，哪天心情对的时候再放一次。",
        "推荐给会喜欢这种调子的朋友。",
        "就放在列表里，慢慢听。",
        "先记一下，改天再来。",
        "留着，不着急下结论。",
        "《{name}》先收进歌单。",
        "有机会想再听一遍。",
        "放到常听里，来回多听几次。",
        "暂时收藏，过阵子再回来看。",
        "先放着，说不定哪天就听进去了。",
    )

    // 简短：一句话，不铺垫、不收尾
    private val BRIEF_JUDGEMENTS = mapOf(
        "high" to listOf(
            "完成度挺高，值得留个位置。",
            "稳，没什么可挑的。",
            "该有的都有，听着舒服。",
            "比预期好，可以循环。",
            "干净利落，听了两遍。",
            "挑不出毛病。",
            "这首留得住。",
            "对味，先收着。",
        ),
        "mid" to listOf(
            "中规中矩，记住的不多。",
            "还行，但不算我的类型。",
            "听完就过了，不难听。",
            "差一点自己的东西。",
            "稳，但平。",
            "能听，不会再点。",
            "和预期差不多。",
            "就这样，谈不上喜欢。",
        ),
        "low" to listOf(
            "和预期差得远。",
            "不是我的口味，先放着。",
            "听得有点散，先跳过。",
            "没对上，就这样吧。",
            "听完没印象。",
            "不是我的菜。",
            "先放了，下次再说。",
            "听不下去，切了。",
        ),
    )

    fun tierForScore(score: String): String {
        val value = score.trim().toIntOrNull() ?: return "mid"
        return when {
            value >= 4 -> "high"
            value == 3 -> "mid"
            else -> "low"
        }
    }

    fun openersFor(): List<String> = OPENERS

    fun judgementsFor(voice: String, tier: String): List<String> = when (voice) {
        "warm" -> WARM_JUDGEMENTS[tier] ?: WARM_JUDGEMENTS.getValue("mid")
        "brief" -> BRIEF_JUDGEMENTS[tier] ?: BRIEF_JUDGEMENTS.getValue("mid")
        else -> JUDGEMENTS[tier] ?: JUDGEMENTS.getValue("mid")
    }

    fun closersFor(voice: String): List<String> = when (voice) {
        "warm" -> WARM_CLOSERS
        "brief" -> emptyList()
        else -> CLOSERS
    }

    // ==================================================================
    // 本次运行的生成入口
    // ==================================================================

    /** 本次运行里已经用过的批注（跨歌曲去重，任务开始时清空）。 */
    private val used = mutableSetOf<String>()

    /** 本次运行里用过的开头：二十首歌里反复出现同一句开头，一眼就是模板。 */
    private val usedOpeners = mutableSetOf<String>()

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
        length: String = DEFAULT_LENGTH,
        maxChars: Int = NoteGenerator.DEFAULT_MAX_CHARS,
    ): String = NoteGenerator(enabled, voice, length, maxChars, used, usedOpeners)
        .generate(work, score)

    /** 每次任务开始时清空"本次已用过的句子"，让重跑之间不互相影响。 */
    @Synchronized
    fun resetRun() {
        used.clear()
        usedOpeners.clear()
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
    private val length: String = Notes.DEFAULT_LENGTH,
    private val maxChars: Int = DEFAULT_MAX_CHARS,
    /** 跨歌曲去重的"已用句子"集合；不传就是这一实例自己的。 */
    private val used: MutableSet<String> = mutableSetOf(),
    private val usedOpeners: MutableSet<String> = mutableSetOf(),
) {

    /** 上一次拼句实际用到的开头（没用到则是空串）。 */
    private var lastOpener = ""

    /** 长度上限：长度档与显式上限取小，夹在 10~200 之间。 */
    val limit: Int
        get() {
            val cap = Notes.LENGTHS[Notes.normalizeLength(length)] ?: DEFAULT_MAX_CHARS
            return if (maxChars in 10..200) minOf(cap, maxChars) else cap
        }

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
            val candidate = compose(work, score, salt)
            val openerRepeated = lastOpener.isNotEmpty() && lastOpener in usedOpeners
            if (candidate.isNotEmpty() && candidate !in used && !openerRepeated) {
                text = candidate
                break
            }
        }
        if (text.isEmpty()) {
            // 全撞车了就接受第一句，总比没有批注好
            text = compose(work, score, 0)
        }
        val fitted = fit(text)
        used.add(fitted)
        if (lastOpener.isNotEmpty()) usedOpeners.add(lastOpener)
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
    private fun seed(work: Work, score: String, salt: Int, part: String): Long {
        val key = "${work.id}|${work.name}|${work.authorName}|$score|$salt|$part"
        return key.hashCode().toLong() and 0xFFFFFFFFL
    }

    private fun pick(pool: List<String>, seed: Long): String =
        pool[(seed % pool.size).toInt()]

    /** 把 `{name}` 换成歌名；拿不到歌名就返回空串（调用方当没有这句）。 */
    private fun fill(text: String, work: Work): String {
        if (!text.contains("{name}")) return text
        val name = work.name.trim()
        return if (name.isEmpty()) "" else text.replace("{name}", name)
    }

    /** 按种子拼一句。排法也由种子决定，四种轮着来。 */
    private fun compose(work: Work, score: String, salt: Int): String {
        val tier = Notes.tierForScore(score)
        val openers = Notes.openersFor()
        val judgements = Notes.judgementsFor(voice, tier)
        lastOpener = ""
        // 每段各自一份哈希：用同一个种子取模会让相邻歌曲的开头几乎一样
        val opener = pick(openers, seed(work, score, salt, "o"))
        val judgement = pick(judgements, seed(work, score, salt, "j"))

        val closers = Notes.closersFor(voice)
        var closer = ""
        if (closers.isNotEmpty()) {
            closer = fill(pick(closers, seed(work, score, salt, "c")), work)
        }

        val tierLength = Notes.normalizeLength(length)

        // 简短档：只留判断那一句，和"标准"要能看出区别
        if (tierLength == "brief") return sentence(judgement)

        // 详细档：多一句判断，句子真正变长（而不是只把上限调大）
        if (tierLength == "detailed" && closer.isNotEmpty()) {
            var second = pick(judgements, seed(work, score, salt, "j2"))
            if (second == judgement) {
                second = pick(judgements, seed(work, score, salt, "j3"))
            }
            if (second != judgement) {
                lastOpener = opener
                return "$opener${sentence(judgement)}${sentence(second)}$closer"
            }
        }

        // 简短语气只有一句；收尾缺失（拿不到歌名）时也不硬凑
        val format = if (voice == "brief" || closer.isEmpty()) {
            "single"
        } else {
            val picked = Notes.FORMATS[
                (seed(work, score, salt, "f") % Notes.FORMATS.size).toInt()]
            // 标准档至少带开场，否则和"简短"撞成同一句
            if (picked == "single") "no_closer" else picked
        }

        return when (format) {
            "full" -> {
                lastOpener = opener
                "$opener${sentence(judgement)}$closer"
            }
            "no_closer" -> {
                lastOpener = opener
                "$opener${sentence(judgement)}"
            }
            "no_opener" -> "${sentence(judgement)}$closer"
            else -> sentence(judgement)
        }
    }

    /** 句子收尾统一一个句号；已经有的不重复加（简短语气的判断句自带句号）。 */
    private fun sentence(text: String): String =
        if (text.endsWith("。")) text else "$text。"

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
        const val DEFAULT_MAX_CHARS = 120

        private val WHITESPACE = Regex("\\s+")
    }
}

/** 一次性便捷入口：给一首歌生成一句批注（对应桌面端 `build_note`）。 */
fun buildNote(
    work: Work,
    score: String,
    enabled: Boolean = true,
    voice: String = Notes.DEFAULT_VOICE,
    length: String = Notes.DEFAULT_LENGTH,
    maxChars: Int = NoteGenerator.DEFAULT_MAX_CHARS,
): String = NoteGenerator(enabled, voice, length, maxChars).generate(work, score)
