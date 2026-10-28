package com.ncmp.mobile.data

/**
 * 合伙人称号换算 —— 与桌面端 `core/partner_points.py` 同一份规则。
 *
 * 阈值来自用户提供的一手规则：320 分高级（可维持身份）、400 分资深、480 分首席。
 * 分数取"本期积分"，拿不到就取任何一个名字里含"积分"的字段。
 */
object PartnerTitles {

    /** (积分下限, 称号)，按分数升序 */
    val TABLE: List<Pair<Int, String>> = listOf(
        320 to "高级音乐合伙人",
        400 to "资深音乐合伙人",
        480 to "首席音乐合伙人",
    )

    const val BELOW_FIRST = "未达保级线"

    data class Info(
        val label: String,
        val nextLabel: String?,
        val gap: Int?,
        val table: List<Pair<Int, String>> = TABLE,
    )

    /** 从积分表里挑出用于换算的分数；一个都解析不出来就返回 null。 */
    fun scoreOf(points: Map<String, String>): Int? {
        for (key in listOf("本期积分", "合伙人积分")) {
            parse(points[key])?.let { return it }
        }
        for ((key, value) in points) {
            if (key.contains("积分")) parse(value)?.let { return it }
        }
        return null
    }

    private fun parse(raw: String?): Int? =
        raw?.trim()?.replace(",", "")?.toDoubleOrNull()?.toInt()

    fun titleFor(score: Int?): Info {
        if (score == null) return Info("", null, null)
        var label = BELOW_FIRST
        var nextLabel: String? = null
        var gap: Int? = null
        for ((threshold, name) in TABLE) {
            if (score >= threshold) {
                label = name
            } else if (nextLabel == null) {
                nextLabel = name
                gap = threshold - score
            }
        }
        return Info(label, nextLabel, gap)
    }
}
