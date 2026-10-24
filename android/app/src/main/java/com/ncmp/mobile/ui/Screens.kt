package com.ncmp.mobile.ui

import android.annotation.SuppressLint
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings
import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import com.ncmp.mobile.R
import com.ncmp.mobile.ui.theme.NCMP
import com.ncmp.mobile.ui.theme.NCMPTheme
import com.ncmp.mobile.ui.widgets.SegmentedMeter

@Composable
fun NCMPApp(vm: AppViewModel) {
    NCMPTheme {
        Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            if (vm.loggedIn) MainScreen(vm) else LoginScreen(vm)
        }
    }
}

/** 打开后台保活设置：先请求忽略电池优化，失败则打开应用详情页。 */
private fun openBatterySettings(context: Context) {
    try {
        val pm = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        if (!pm.isIgnoringBatteryOptimizations(context.packageName)) {
            context.startActivity(
                Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                    data = Uri.parse("package:${context.packageName}")
                },
            )
            return
        }
    } catch (_: Exception) {
    }
    try {
        context.startActivity(
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                data = Uri.parse("package:${context.packageName}")
            },
        )
    } catch (_: Exception) {
    }
}

// ======================================================================
// 登录页
// ======================================================================

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LoginScreen(vm: AppViewModel) {
    var tab by remember { mutableStateOf(0) }
    Column(Modifier.fillMaxSize().padding(horizontal = 20.dp)) {
        Spacer(Modifier.height(44.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Image(
                painter = painterResource(R.mipmap.ic_launcher),
                contentDescription = null,
                modifier = Modifier.size(56.dp).clip(RoundedCornerShape(14.dp)),
            )
            Spacer(Modifier.width(12.dp))
            Column {
                Text("ncmp", fontSize = 24.sp, fontWeight = FontWeight.Bold, color = NCMP.Ink)
                Text("音乐合伙人任务自动化", fontSize = 13.sp, color = NCMP.Muted)
            }
        }
        Spacer(Modifier.height(28.dp))
        TabRow(
            selectedTabIndex = tab,
            containerColor = Color.Transparent,
            contentColor = NCMP.Brand,
        ) {
            Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("网页登录") })
            Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("Cookie") })
        }
        Spacer(Modifier.height(16.dp))
        when (tab) {
            0 -> WebLoginTab(vm, Modifier.weight(1f))
            else -> CookieLoginTab(vm)
        }
        Spacer(Modifier.height(20.dp))
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun WebLoginTab(vm: AppViewModel, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val webView = remember {
        WebView(context).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.userAgentString =
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            settings.useWideViewPort = true
            settings.loadWithOverviewMode = false
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
    DisposableEffect(Unit) { onDispose { webView.destroy() } }

    Column(modifier = modifier.fillMaxWidth()) {
        Text(
            "下面是网易官方登录页，支持扫码 / 手机号 / 验证码等官方方式",
            fontSize = 12.sp,
            color = NCMP.Muted,
        )
        Spacer(Modifier.height(10.dp))
        Surface(
            shape = RoundedCornerShape(12.dp),
            color = NCMP.Panel,
            modifier = Modifier.weight(1f).fillMaxWidth(),
        ) {
            AndroidView(factory = { webView }, modifier = Modifier.fillMaxSize())
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(
                onClick = { webView.reload() },
                modifier = Modifier.weight(1f).height(46.dp),
                shape = RoundedCornerShape(10.dp),
            ) {
                Icon(Icons.Filled.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(4.dp))
                Text("刷新")
            }
            Button(
                onClick = { vm.extractCookieFromWebView() },
                modifier = Modifier.weight(1.6f).height(46.dp),
                shape = RoundedCornerShape(10.dp),
                colors = ButtonDefaults.buttonColors(containerColor = NCMP.Brand),
            ) {
                Text("我已登录，获取 Cookie")
            }
        }
        if (vm.webError.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Text(vm.webError, color = NCMP.Red, fontSize = 12.sp)
        }
    }
}

@Composable
private fun CookieLoginTab(vm: AppViewModel) {
    Column {
        Text(
            "粘贴已登录的 Cookie（MUSIC_U / __csrf），绕开风控",
            fontSize = 12.sp,
            color = NCMP.Muted,
        )
        Spacer(Modifier.height(14.dp))
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
        Spacer(Modifier.height(18.dp))
        Button(
            onClick = { vm.cookieLogin() },
            modifier = Modifier.fillMaxWidth().height(48.dp),
            shape = RoundedCornerShape(10.dp),
            colors = ButtonDefaults.buttonColors(containerColor = NCMP.Brand),
        ) {
            Text("登录")
        }
        if (vm.cookieError.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            Text(vm.cookieError, color = NCMP.Red, fontSize = 12.sp)
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
                title = {
                    Column {
                        Text(
                            if (vm.nickname.isEmpty()) "音乐合伙人" else vm.nickname,
                            fontSize = 18.sp,
                            fontWeight = FontWeight.Bold,
                            color = NCMP.Ink,
                        )
                        Text("ncmp", fontSize = 11.sp, color = NCMP.Muted)
                    }
                },
                actions = {
                    IconButton(onClick = { vm.logout() }) {
                        Icon(Icons.Filled.Logout, contentDescription = "退出登录", tint = NCMP.Muted)
                    }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp, vertical = 12.dp),
        ) {
            HeroCard(vm)
            Spacer(Modifier.height(12.dp))
            ConfigCard(vm)
            Spacer(Modifier.height(12.dp))
            LogCard(vm)
        }
    }
}

@Composable
private fun HeroCard(vm: AppViewModel) {
    val isCancelled = vm.resultLabel == "已取消"
    val statusText: String
    val statusColor: Color
    val subText: String
    when {
        vm.running -> {
            statusText = "正在执行…"
            statusColor = NCMP.Amber
            subText = if (vm.progressTotal > 0)
                "${vm.currentStep} · ${vm.progressDone}/${vm.progressTotal}" + if (vm.currentSong.isNotEmpty()) " · ${vm.currentSong}" else ""
            else vm.currentStep.ifEmpty { "准备中…" }
        }
        vm.resultLabel.isNotEmpty() && vm.resultIsError -> {
            statusText = vm.resultLabel
            statusColor = NCMP.Red
            subText = vm.resultHint
        }
        vm.resultLabel.isNotEmpty() -> {
            statusText = vm.resultLabel
            statusColor = if (isCancelled) NCMP.Muted else NCMP.Green
            subText = if (isCancelled) "" else "今天的评分任务已完成"
        }
        else -> {
            statusText = "准备就绪"
            statusColor = NCMP.Ink
            subText = "点击下方按钮开始今日评分"
        }
    }

    Card(
        colors = CardDefaults.cardColors(containerColor = NCMP.Panel),
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.fillMaxWidth().padding(18.dp)) {
            Text(statusText, fontSize = 26.sp, fontWeight = FontWeight.Bold, color = statusColor)
            if (subText.isNotEmpty()) {
                Spacer(Modifier.height(6.dp))
                Text(subText, fontSize = 13.sp, color = NCMP.Muted)
            }
            if (vm.running && vm.progressTotal > 0) {
                Spacer(Modifier.height(16.dp))
                SegmentedMeter(
                    progress = vm.progressDone.toFloat() / vm.progressTotal,
                    color = if (vm.resultIsError) NCMP.Red else NCMP.Amber,
                    modifier = Modifier.fillMaxWidth().height(14.dp),
                )
            }
            Spacer(Modifier.height(16.dp))
            if (vm.running) {
                OutlinedButton(
                    onClick = { vm.cancelTask() },
                    modifier = Modifier.fillMaxWidth().height(50.dp),
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = NCMP.Red),
                ) {
                    Icon(Icons.Filled.Stop, contentDescription = null, modifier = Modifier.size(20.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("取消任务", fontSize = 16.sp)
                }
            } else {
                Button(
                    onClick = { vm.runTask() },
                    modifier = Modifier.fillMaxWidth().height(50.dp),
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = NCMP.Brand),
                ) {
                    Icon(Icons.Filled.PlayArrow, contentDescription = null, modifier = Modifier.size(22.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("立即执行", fontSize = 16.sp, fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}

@Composable
private fun ConfigCard(vm: AppViewModel) {
    var expanded by remember { mutableStateOf(false) }
    val context = LocalContext.current
    Card(
        colors = CardDefaults.cardColors(containerColor = NCMP.Panel),
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.fillMaxWidth().padding(16.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().clickable { expanded = !expanded },
            ) {
                Icon(Icons.Filled.Settings, contentDescription = null, tint = NCMP.Muted, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text("任务参数", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = NCMP.Ink, modifier = Modifier.weight(1f))
                Text(if (expanded) "收起" else "展开", fontSize = 12.sp, color = NCMP.Muted)
            }
            if (expanded) {
                Spacer(Modifier.height(14.dp))
                Text("评分策略", fontSize = 13.sp, color = NCMP.Muted)
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    val options = listOf(1 to "1-2分", 2 to "2-3分", 3 to "3-4分", 4 to "固定4分")
                    options.forEach { (value, label) ->
                        FilterChip(
                            selected = vm.scoreStrategy == value,
                            onClick = { vm.scoreStrategy = value },
                            label = { Text(label, fontSize = 12.sp) },
                        )
                    }
                }
                Spacer(Modifier.height(14.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
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
                Spacer(Modifier.height(6.dp))
                Text("每首歌之间随机等待的秒数，越大越不易被风控", fontSize = 11.sp, color = NCMP.Muted)
                Spacer(Modifier.height(10.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("完成全部额外任务", fontSize = 14.sp, color = NCMP.Ink, modifier = Modifier.weight(1f))
                    Switch(checked = vm.fullExtra, onCheckedChange = { vm.fullExtra = it })
                }
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button(
                        onClick = { vm.saveConfig() },
                        shape = RoundedCornerShape(10.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = NCMP.Brand),
                    ) { Text("保存设置") }
                    OutlinedButton(
                        onClick = { openBatterySettings(context) },
                        shape = RoundedCornerShape(10.dp),
                    ) { Text("后台保活设置", fontSize = 13.sp) }
                }
            }
        }
    }
}

@Composable
private fun ColumnScope.LogCard(vm: AppViewModel) {    val listState = rememberLazyListState()
    val context = LocalContext.current
    LaunchedEffect(vm.logLines.size) {
        if (vm.logLines.isNotEmpty()) listState.scrollToItem(vm.logLines.size - 1)
    }
    Card(
        colors = CardDefaults.cardColors(containerColor = NCMP.Panel),
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().weight(1f),
    ) {
        Column(Modifier.fillMaxSize().padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("运行日志", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = NCMP.Ink)
                Spacer(Modifier.width(4.dp))
                TextButton(onClick = {
                    val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    cm.setPrimaryClip(ClipData.newPlainText("ncmp log", vm.logLines.joinToString("\n")))
                }) { Text("复制", fontSize = 13.sp) }
                TextButton(onClick = { vm.clearLog() }) { Text("清空", fontSize = 13.sp) }
            }
            Spacer(Modifier.height(6.dp))
            Surface(
                color = Color(0xFFFAFAFA),
                shape = RoundedCornerShape(10.dp),
                modifier = Modifier.fillMaxSize(),
            ) {
                if (vm.logLines.isEmpty()) {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Text("暂无日志", fontSize = 13.sp, color = NCMP.Muted)
                    }
                } else {
                    LazyColumn(state = listState, contentPadding = PaddingValues(10.dp)) {
                        items(vm.logLines) { line ->
                            Text(
                                line,
                                fontSize = 12.sp,
                                fontFamily = FontFamily.Monospace,
                                color = NCMP.Ink,
                                modifier = Modifier.padding(vertical = 1.dp),
                            )
                        }
                    }
                }
            }
        }
    }
}
