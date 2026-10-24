package com.ncmp.mobile.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// 网易云品牌红为主色
private val LightColors = lightColorScheme(
    primary = Color(0xFFC20C0C),
    secondary = Color(0xFF7A7A7A),
    background = Color(0xFFF5F5F5),
    surface = Color(0xFFFFFFFF),
    surfaceVariant = Color(0xFFEDEDED),
    onSurfaceVariant = Color(0xFF555555),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFE5484D),
    secondary = Color(0xFF9A9A9A),
    background = Color(0xFF121212),
    surface = Color(0xFF1E1E1E),
    surfaceVariant = Color(0xFF2A2A2A),
    onSurfaceVariant = Color(0xFFBBBBBB),
)

@Composable
fun NCMPTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    MaterialTheme(
        colorScheme = if (dark) DarkColors else LightColors,
        content = content,
    )
}
