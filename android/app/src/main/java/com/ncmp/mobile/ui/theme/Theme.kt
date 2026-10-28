package com.ncmp.mobile.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** 与桌面端 DESIGN.md 对齐的颜色标记。 */
object NCMP {
    val Brand = Color(0xFFC20C0C)      // 品牌红：可交互
    val BrandHover = Color(0xFFA50A0A)
    val Ink = Color(0xFF1A1A1A)        // 主要文字
    val Muted = Color(0xFF6B6B6B)      // 次要文字
    val Rule = Color(0xFFE5E5E5)       // 细线/边框
    val Ground = Color(0xFFF5F5F5)     // 页面底色
    val Panel = Color(0xFFFFFFFF)      // 面板
    val Amber = Color(0xFFE8A33D)      // 进行中（只能当填充色）
    val AmberText = Color(0xFF8A5A0A)  // 琥珀色的文字替代，对比度 5.4:1
    val Green = Color(0xFF2C7549)      // 成功
    val Red = Color(0xFFB3352B)        // 失败
    val Track = Color(0xFFE0E0E0)      // 打卡图里"当天没跑"的格子
    val Soft = Color(0x14C20C0C)       // 品牌红浅底
}

private val LightColors = lightColorScheme(
    primary = NCMP.Brand,
    onPrimary = Color.White,
    // 容器色不给品牌浅红的话，FilterChip / Switch 的选中态会用 Material 默认的
    // 灰紫色，和桌面端的红色选中态完全不是一套。
    primaryContainer = NCMP.Soft,
    onPrimaryContainer = NCMP.Brand,
    secondary = NCMP.Muted,
    secondaryContainer = NCMP.Soft,
    onSecondaryContainer = NCMP.Brand,
    background = NCMP.Ground,
    onBackground = NCMP.Ink,
    surface = NCMP.Panel,
    onSurface = NCMP.Ink,
    surfaceVariant = Color(0xFFF0F0F0),
    onSurfaceVariant = NCMP.Muted,
    outline = NCMP.Rule,
    outlineVariant = NCMP.Rule,
    error = NCMP.Red,
    onError = Color.White,
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFE5484D),
    secondary = Color(0xFF9A9A9A),
    background = Color(0xFF121212),
    surface = Color(0xFF1E1E1E),
    surfaceVariant = Color(0xFF2A2A2A),
    onSurfaceVariant = Color(0xFFBBBBBB),
    outline = Color(0xFF3A3A3A),
)

@Composable
fun NCMPTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    MaterialTheme(
        colorScheme = if (dark) DarkColors else LightColors,
        content = content,
    )
}
