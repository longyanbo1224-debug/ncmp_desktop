package com.ncmp.mobile.ui.widgets

import android.graphics.Paint
import android.graphics.Typeface
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ncmp.mobile.data.DayCell
import com.ncmp.mobile.ui.theme.NCMP

private const val WEEKS = 53

/**
 * 年度打卡格子图（桌面端 StreakGrid 的手机版）。
 *
 * 绿=当天成功，砖红=当天失败，灰=当天没跑——和桌面端同一套状态色。
 * 格子尺寸跟着屏宽算，53 周刚好铺满一行，不用横向滚动。
 */
@Composable
fun StreakGrid(days: List<DayCell>, modifier: Modifier = Modifier) {
    val labelWidth = 13.dp
    val gap = 2.dp
    val monthHeight = 13.dp

    BoxWithConstraints(modifier.fillMaxWidth()) {
        val cell = ((maxWidth - labelWidth - gap * (WEEKS - 1)) / WEEKS)
            .coerceIn(2.dp, 6.dp)
        val gridHeight = cell * 7 + gap * 6

        val textPaint = remember {
            Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = NCMP.Muted.toArgb()
                typeface = Typeface.DEFAULT
            }
        }

        Canvas(Modifier.fillMaxWidth().height(monthHeight + gridHeight)) {
            val cellPx = cell.toPx()
            val gapPx = gap.toPx()
            val labelPx = labelWidth.toPx()
            val top = monthHeight.toPx()

            textPaint.textSize = 7.sp.toPx()

            // 月份标签：某列第一天的月份变了，就在那一列上方标一次
            textPaint.textAlign = Paint.Align.LEFT
            var lastMonth = -1
            for (i in days.indices step 7) {
                val month = days[i].date.substring(5, 7).toIntOrNull() ?: continue
                val col = i / 7
                if (month != lastMonth) {
                    if (col > 0) {
                        drawContext.canvas.nativeCanvas.drawText(
                            "${month}月",
                            labelPx + col * (cellPx + gapPx),
                            top - 4.dp.toPx(),
                            textPaint,
                        )
                    }
                    lastMonth = month
                }
            }

            // 星期标签：和桌面端一样只标一、三、五
            textPaint.textAlign = Paint.Align.RIGHT
            for ((row, text) in listOf(0 to "一", 2 to "三", 4 to "五")) {
                drawContext.canvas.nativeCanvas.drawText(
                    text,
                    labelPx - 3.dp.toPx(),
                    top + row * (cellPx + gapPx) + cellPx * 0.85f,
                    textPaint,
                )
            }

            val radius = CornerRadius(1.dp.toPx())
            for (i in days.indices) {
                val col = i / 7
                val row = i % 7
                drawRoundRect(
                    color = when (days[i].status) {
                        "success" -> NCMP.Green
                        "fail" -> NCMP.Red
                        else -> NCMP.Track
                    },
                    topLeft = Offset(
                        labelPx + col * (cellPx + gapPx),
                        top + row * (cellPx + gapPx),
                    ),
                    size = Size(cellPx, cellPx),
                    cornerRadius = radius,
                )
            }
        }
    }
}

/** 格子图下面的图例 + 连续/累计。 */
@Composable
fun StreakLegend(streak: Int, total: Int, modifier: Modifier = Modifier) {
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        LegendItem(NCMP.Green, "成功")
        Spacer(Modifier.width(10.dp))
        LegendItem(NCMP.Red, "失败")
        Spacer(Modifier.width(10.dp))
        LegendItem(NCMP.Track, "没跑")
        Spacer(Modifier.weight(1f))
        Text(
            "连续 $streak 天，累计 $total 天",
            fontSize = 10.sp,
            color = NCMP.Muted,
        )
    }
}

@Composable
private fun LegendItem(color: Color, label: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier
                .size(8.dp)
                .clip(RoundedCornerShape(2.dp))
                .background(color),
        )
        Spacer(Modifier.width(4.dp))
        Text(label, fontSize = 10.sp, color = NCMP.Muted)
    }
}
