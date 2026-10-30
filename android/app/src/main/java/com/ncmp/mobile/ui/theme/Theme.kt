package com.ncmp.mobile.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color

/**
 * 与桌面端 DESIGN.md 对齐的颜色标记。
 *
 * **值随深浅色切换**：`NCMPTheme` 在组合开始时按系统设置写入这些属性，
 * 界面里直接读 `NCMP.Ink` 这类值即可，不需要每处都去取 `MaterialTheme.colorScheme`
 * ——手机端界面大量使用固定色标记，靠这一层统一换肤，改动面最小。
 */
object NCMP {
    var Brand by mutableStateOf(Color(0xFFC20C0C)); private set   // 品牌红：可交互
    var BrandHover by mutableStateOf(Color(0xFFA50A0A)); private set
    var Ink by mutableStateOf(Color(0xFF1A1A1A)); private set     // 主要文字
    var Muted by mutableStateOf(Color(0xFF6B6B6B)); private set   // 次要文字
    var Rule by mutableStateOf(Color(0xFFE5E5E5)); private set    // 细线/边框
    var Ground by mutableStateOf(Color(0xFFF5F5F5)); private set  // 页面底色
    var Panel by mutableStateOf(Color(0xFFFFFFFF)); private set   // 面板
    var Amber by mutableStateOf(Color(0xFFE8A33D)); private set   // 进行中（只能当填充色）
    var AmberText by mutableStateOf(Color(0xFF8A5A0A)); private set
    var Green by mutableStateOf(Color(0xFF2C7549)); private set   // 成功
    var Red by mutableStateOf(Color(0xFFB3352B)); private set     // 失败
    var Track by mutableStateOf(Color(0xFFE0E0E0)); private set   // 打卡图空格子
    var Soft by mutableStateOf(Color(0x14C20C0C)); private set    // 品牌红浅底

    /** 深色取值与桌面端 `theme.py` 的 `_DARK_OVERRIDE` 一致。 */
    internal fun apply(dark: Boolean) {
        Brand = if (dark) Color(0xFFE85256) else Color(0xFFC20C0C)
        BrandHover = if (dark) Color(0xFFF0666A) else Color(0xFFA50A0A)
        Ink = if (dark) Color(0xFFE8E9EA) else Color(0xFF1A1A1A)
        Muted = if (dark) Color(0xFF9AA0A4) else Color(0xFF6B6B6B)
        Rule = if (dark) Color(0xFF2A2E31) else Color(0xFFE5E5E5)
        Ground = if (dark) Color(0xFF121416) else Color(0xFFF5F5F5)
        Panel = if (dark) Color(0xFF191C1F) else Color(0xFFFFFFFF)
        Amber = if (dark) Color(0xFFE0A85C) else Color(0xFFE8A33D)
        AmberText = if (dark) Color(0xFFE0A85C) else Color(0xFF8A5A0A)
        Green = if (dark) Color(0xFF4FA97C) else Color(0xFF2C7549)
        Red = if (dark) Color(0xFFE06A5E) else Color(0xFFB3352B)
        Track = if (dark) Color(0xFF2C3033) else Color(0xFFE0E0E0)
        Soft = if (dark) Color(0x24E85256) else Color(0x14C20C0C)
    }
}

@Composable
fun NCMPTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    // 先写调色板，再组合内容：子界面读 NCMP.* 时拿到的就是当前主题的颜色
    NCMP.apply(dark)

    val scheme = if (dark) {
        darkColorScheme(
            primary = NCMP.Brand,
            onPrimary = Color.White,
            primaryContainer = NCMP.Soft,
            onPrimaryContainer = NCMP.Brand,
            secondary = NCMP.Muted,
            secondaryContainer = NCMP.Soft,
            onSecondaryContainer = NCMP.Brand,
            background = NCMP.Ground,
            onBackground = NCMP.Ink,
            surface = NCMP.Panel,
            onSurface = NCMP.Ink,
            surfaceVariant = Color(0xFF23272A),
            onSurfaceVariant = NCMP.Muted,
            outline = NCMP.Rule,
            outlineVariant = NCMP.Rule,
            error = NCMP.Red,
            onError = Color.White,
        )
    } else {
        lightColorScheme(
            primary = NCMP.Brand,
            onPrimary = Color.White,
            // 容器色不给品牌浅红的话，FilterChip / Switch 的选中态会用 Material
            // 默认的灰紫色，和桌面端的红色选中态完全不是一套。
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
    }
    MaterialTheme(colorScheme = scheme, content = content)
}
