package com.ncmp.mobile.ui.widgets

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.ncmp.mobile.ui.theme.NCMP
import kotlin.math.roundToInt

/** 桌面端同款「分段电平表」（VU 表）进度条。 */
@Composable
fun SegmentedMeter(
    progress: Float,
    color: Color,
    modifier: Modifier = Modifier,
    segments: Int = 40,
    // 未点亮的格子跟随主题（深色下不能还是浅灰）
    emptyColor: Color = NCMP.Track,
) {
    Canvas(modifier = modifier) {
        val gap = 3.dp.toPx()
        val segW = (size.width - gap * (segments - 1)) / segments
        val filled = (progress.coerceIn(0f, 1f) * segments).roundToInt()
        for (i in 0 until segments) {
            drawRoundRect(
                color = if (i < filled) color else emptyColor,
                topLeft = Offset(i * (segW + gap), 0f),
                size = Size(segW.coerceAtLeast(1f), size.height),
                cornerRadius = CornerRadius(2.dp.toPx()),
            )
        }
    }
}
