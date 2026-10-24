package com.ncmp.mobile.ui

import android.annotation.SuppressLint
import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Logout
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.ncmp.mobile.ui.theme.NCMPTheme

@Composable
fun NCMPApp(vm: AppViewModel) {
    NCMPTheme {
        Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            if (vm.loggedIn) MainScreen(vm) else LoginScreen(vm)
        }
    }
}

// ======================================================================
// 登录页
// ======================================================================

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LoginScreen(vm: AppViewModel) {
    var tab by remember { mutableStateOf(0) }
    Scaffold(topBar = { TopAppBar(title = { Text("登录网易云音乐") }) }) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
        ) {
            TabRow(selectedTabIndex = tab) {
                Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("网页登录") })
                Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("Cookie") })
            }
            Spacer(Modifier.height(12.dp))
            when (tab) {
                0 -> WebLoginTab(vm, Modifier.weight(1f))
                else -> CookieLoginTab(vm)
            }
        }
    }
}

/** 内嵌浏览器登录：直接展示网易官方登录页（扫码 / 手机验证码 / 密码等官方渠道），登录后提取 Cookie。 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun WebLoginTab(vm: AppViewModel, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val webView = remember {
        WebView(context).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            // 桌面 UA：避免被识别成手机端而跳转到「下载 App」页
            settings.userAgentString =
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            // 桌面版页面按自身宽度渲染（不缩放），手机可横向滑动看到完整页面
            settings.useWideViewPort = true
            settings.loadWithOverviewMode = false
            // 页面加载后轮询点「登录」，自动弹出官方登录弹窗（二维码等）
            var loginTriggered = false
            webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView, url: String) {
                    if (!loginTriggered) {
                        loginTriggered = true
                        view.evaluateJavascript(
                            "(function(){var n=0;function f(){var els=document.querySelectorAll('a,span,div,button');for(var i=0;i<els.length;i++){if(els[i].textContent.trim()==='登录'){els[i].click();return true;}}return false;}function p(){if(f())return;if(++n<24)setTimeout(p,500);}setTimeout(p,1500);})()",
                            null,
                        )
                    }
                }
            }
            CookieManager.getInstance().setAcceptCookie(true)
            CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
            loadUrl("https://music.163.com/#/login")
        }
    }
    DisposableEffect(Unit) {
        onDispose { webView.destroy() }
    }

    Column(modifier = modifier.fillMaxWidth()) {
        Text(
            "下面是网易官方登录页，支持扫码 / 手机号 / 验证码等官方方式，登录完成后点按钮",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.secondary,
        )
        Spacer(Modifier.height(8.dp))
        AndroidView(factory = { webView }, modifier = Modifier.weight(1f).fillMaxWidth())
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(
                onClick = { webView.reload() },
                modifier = Modifier.weight(1f),
            ) {
                Icon(Icons.Filled.Refresh, contentDescription = null)
                Spacer(Modifier.width(4.dp))
                Text("刷新")
            }
            Button(
                onClick = { vm.extractCookieFromWebView() },
                modifier = Modifier.weight(1f),
            ) {
                Text("我已登录，获取 Cookie")
            }
        }
        if (vm.webError.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Text(
                vm.webError,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun CookieLoginTab(vm: AppViewModel) {
    Column {
        Text(
            "粘贴已登录的 Cookie（MUSIC_U / __csrf），绕开风控",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.secondary,
        )
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = vm.cookieMusicU,
            onValueChange = { vm.cookieMusicU = it },
            label = { Text("MUSIC_U") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = vm.cookieCsrf,
            onValueChange = { vm.cookieCsrf = it },
            label = { Text("__csrf") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(16.dp))
        Button(onClick = { vm.cookieLogin() }, modifier = Modifier.fillMaxWidth()) {
            Text("登录")
        }
        if (vm.cookieError.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            Text(
                vm.cookieError,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

// ======================================================================
// 主界面
// ======================================================================

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(vm: AppViewModel) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (vm.nickname.isEmpty()) "音乐合伙人" else vm.nickname) },
                actions = {
                    IconButton(onClick = { vm.logout() }) {
                        Icon(Icons.Filled.Logout, contentDescription = "退出登录")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
        ) {
            ConfigSection(vm)
            Spacer(Modifier.height(12.dp))
            RunSection(vm)
            Spacer(Modifier.height(12.dp))
            ResultBanner(vm)
            Spacer(Modifier.height(8.dp))
            LogSection(vm)
        }
    }
}

@Composable
private fun ConfigSection(vm: AppViewModel) {
    var expanded by remember { mutableStateOf(false) }
    Card {
        Column(Modifier.padding(12.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { expanded = !expanded },
            ) {
                Icon(Icons.Filled.Settings, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("任务参数", modifier = Modifier.weight(1f))
                Text(
                    if (expanded) "收起" else "展开",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.secondary,
                )
            }
            if (expanded) {
                Spacer(Modifier.height(12.dp))
                Text("评分策略", style = MaterialTheme.typography.labelLarge)
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    val options = listOf(1 to "1-2分", 2 to "2-3分", 3 to "3-4分", 4 to "固定4分")
                    options.forEach { (value, label) ->
                        FilterChip(
                            selected = vm.scoreStrategy == value,
                            onClick = { vm.scoreStrategy = value },
                            label = { Text(label) },
                        )
                    }
                }
                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = vm.waitMin,
                        onValueChange = { vm.waitMin = it },
                        label = { Text("等待下限(秒)") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = vm.waitMax,
                        onValueChange = { vm.waitMax = it },
                        label = { Text("等待上限(秒)") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f),
                    )
                }
                Text(
                    "每首歌之间随机等待的秒数区间，越大越不易被风控",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.secondary,
                )
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("完成全部额外任务", modifier = Modifier.weight(1f))
                    Switch(checked = vm.fullExtra, onCheckedChange = { vm.fullExtra = it })
                }
                Spacer(Modifier.height(8.dp))
                Button(onClick = { vm.saveConfig() }) { Text("保存设置") }
            }
        }
    }
}

@Composable
private fun RunSection(vm: AppViewModel) {
    if (vm.running) {
        Column {
            if (vm.progressTotal > 0) {
                LinearProgressIndicator(
                    progress = { vm.progressDone.toFloat() / vm.progressTotal },
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    "${vm.progressDone}/${vm.progressTotal}" +
                        (if (vm.currentSong.isNotEmpty()) "  ·  ${vm.currentSong}" else ""),
                    style = MaterialTheme.typography.bodySmall,
                )
            } else {
                Text(vm.currentStep, style = MaterialTheme.typography.bodySmall)
            }
            Spacer(Modifier.height(8.dp))
            Button(
                onClick = { vm.cancelTask() },
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
            ) {
                Icon(Icons.Filled.Stop, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("取消")
            }
        }
    } else {
        Button(
            onClick = { vm.runTask() },
            modifier = Modifier
                .fillMaxWidth()
                .height(48.dp),
        ) {
            Icon(Icons.Filled.PlayArrow, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("立即执行")
        }
    }
}

@Composable
private fun ResultBanner(vm: AppViewModel) {
    if (vm.resultLabel.isNotEmpty()) {
        val color = if (vm.resultIsError) {
            MaterialTheme.colorScheme.error
        } else {
            MaterialTheme.colorScheme.primary
        }
        Card(colors = CardDefaults.cardColors(containerColor = color.copy(alpha = 0.1f))) {
            Column(Modifier.padding(12.dp)) {
                Text(vm.resultLabel, color = color, fontWeight = FontWeight.Bold)
                if (vm.resultHint.isNotEmpty()) {
                    Spacer(Modifier.height(4.dp))
                    Text(vm.resultHint, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}

@Composable
private fun ColumnScope.LogSection(vm: AppViewModel) {
    val listState = rememberLazyListState()
    LaunchedEffect(vm.logLines.size) {
        if (vm.logLines.isNotEmpty()) listState.scrollToItem(vm.logLines.size - 1)
    }
    Column(
        modifier = Modifier
            .weight(1f)
            .fillMaxWidth(),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("运行日志", style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.width(8.dp))
            TextButton(onClick = { vm.clearLog() }) { Text("清空") }
        }
        Surface(
            color = MaterialTheme.colorScheme.surfaceVariant,
            modifier = Modifier.fillMaxSize(),
        ) {
            if (vm.logLines.isEmpty()) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(
                        "暂无日志",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            } else {
                LazyColumn(state = listState, contentPadding = PaddingValues(8.dp)) {
                    items(vm.logLines) { line ->
                        Text(
                            line,
                            style = MaterialTheme.typography.bodySmall,
                            fontFamily = FontFamily.Monospace,
                        )
                    }
                }
            }
        }
    }
}
