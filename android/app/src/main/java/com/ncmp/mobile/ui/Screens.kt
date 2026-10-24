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
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
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
import kotlinx.coroutines.delay

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

@Composable
private fun ThinRule(color: Color = NCMP.Rule) {
    Box(Modifier.fillMaxWidth().height(1.dp).background(color))
}

// ======================================================================
// 登录页
// ======================================================================

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LoginScreen(vm: AppViewModel) {
    var tab by remember { mutableStateOf(0) }
    Column(Modifier.fillMaxSize().padding(horizontal = 22.dp)) {
        Spacer(Modifier.height(48.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Image(
                painter = painterResource(R.mipmap.ic_launcher),
                contentDescription = null,
                modifier = Modifier.size(52.dp).clip(RoundedCornerShape(13.dp)),
            )
            Spacer(Modifier.width(12.dp))
            Column {
                Text("ncmp", fontSize = 23.sp, fontWeight = FontWeight.Bold, color = NCMP.Ink)
                Text("音乐合伙人任务自动化", fontSize = 12.sp, color = NCMP.Muted)
            }
        }
        Spacer(Modifier.height(30.dp))
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
            // 保持原始大小（可读），靠 JS 自动滚动到登录区域，不用手动横向滑动
            settings.loadWithOverviewMode = false
            settings.setSupportZoom(true)
            settings.builtInZoomControls = true
            settings.displayZoomControls = false
            var loginTriggered = false
            webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView, url: String) {
                    if (!loginTriggered) {
                        loginTriggered = true
                        view.evaluateJavascript(
                            "(function(){var n=0;function f(){var els=document.querySelectorAll('a,span,div,button,li');for(var i=0;i<els.length;i++){var t=(els[i].textContent||'').trim();if(t==='登录'||t==='立即登录'||t==='登录/注册'){try{els[i].scrollIntoView({block:'center',inline:'center'});}catch(e){}return true;}}return false;}function p(){if(f())return;if(++n<30)setTimeout(p,500);}setTimeout(p,1200);})()",
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

    // 登录成功后自动检测并进入，无需手动点按钮
    LaunchedEffect(Unit) {
        while (true) {
            delay(1500)
            val c = CookieManager.getInstance().getCookie("https://music.163.com") ?: ""
            if (c.contains("MUSIC_U=") && c.contains("__csrf=")) {
                vm.extractCookieFromWebView()
                break
            }
        }
    }

    Column(modifier = modifier.fillMaxWidth()) {
        Text(
            "已自动定位到登录区域。输入手机号 → 获取验证码 → 填短信码即可，登录后会自动继续。",
            fontSize = 12.sp,
            color = NCMP.Muted,
        )
        Spacer(Modifier.height(10.dp))
        Surface(
            shape = RoundedCornerShape(12.dp),
            color = Color.White,
            modifier = Modifier.weight(1f).fillMaxWidth(),
        ) {
            AndroidView(factory = { webView }, modifier = Modifier.fillMaxSize())
        }
        Spacer(Modifier.height(10.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(
                onClick = { webView.reload() },
                modifier = Modifier.height(44.dp),
                shape = RoundedCornerShape(10.dp),
            ) {
                Icon(Icons.Filled.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(4.dp))
                Text("刷新")
            }
            Spacer(Modifier.width(12.dp))
            Text("登录后自动检测，也可手动", fontSize = 11.sp, color = NCMP.Muted, modifier = Modifier.weight(1f))
            TextButton(onClick = { vm.extractCookieFromWebView() }) { Text("获取 Cookie", fontSize = 13.sp) }
        }
        if (vm.webError.isNotEmpty()) {
            Spacer(Modifier.height(6.dp))
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
        Spacer(Modifier.height(16.dp))
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
        ) { Text("登录") }
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
        containerColor = NCMP.Ground,
        topBar = { Header(vm) },
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 22.dp),
        ) {
            HeroSection(vm)
            ThinRule()
            ConfigSection(vm)
            ThinRule()
            LogSection(vm)
        }
    }
}

@Composable
private fun Header(vm: AppViewModel) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 22.dp)) {
        Row(
            Modifier.fillMaxWidth().padding(vertical = 16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    if (vm.nickname.isEmpty()) "音乐合伙人" else vm.nickname,
                    fontSize = 18.sp,
                    fontWeight = FontWeight.Bold,
                    color = NCMP.Ink,
                )
                Text("ncmp", fontSize = 11.sp, color = NCMP.Muted)
            }
            IconButton(onClick = { vm.logout() }) {
                Icon(Icons.Filled.Logout, contentDescription = "退出登录", tint = NCMP.Muted)
            }
        }
        ThinRule()
    }
}

/** 主角：状态 + 当前歌曲 + 分段电平表 + 主操作。全部坐在底色上，不套卡片。 */
@Composable
private fun HeroSection(vm: AppViewModel) {
    val isCancelled = vm.resultLabel == "已取消"

    val title: String
    val titleColor: Color
    val sub: String
    when {
        vm.running -> {
            title = "正在评分"
            titleColor = NCMP.Amber
            sub = vm.currentStep.ifEmpty { "准备中…" }
        }
        vm.resultLabel.isNotEmpty() && vm.resultIsError -> {
            title = "执行失败"
            titleColor = NCMP.Red
            sub = vm.resultHint.ifEmpty { vm.resultLabel }
        }
        vm.resultLabel.isNotEmpty() && isCancelled -> {
            title = "已取消"
            titleColor = NCMP.Muted
            sub = "随时可以重新开始"
        }
        vm.resultLabel.isNotEmpty() -> {
            title = "今天完成"
            titleColor = NCMP.Green
            sub = "共 ${vm.progressTotal} 首已评分"
        }
        else -> {
            title = "今日评分"
            titleColor = NCMP.Ink
            sub = "点下方按钮开始"
        }
    }

    val meterProgress = when {
        vm.running && vm.progressTotal > 0 -> vm.progressDone.toFloat() / vm.progressTotal
        vm.resultLabel.isNotEmpty() && !vm.resultIsError && !isCancelled -> 1f
        vm.progressTotal > 0 -> vm.progressDone.toFloat() / vm.progressTotal
        else -> 0f
    }
    val meterColor = when {
        vm.resultIsError -> NCMP.Red
        vm.running -> NCMP.Amber
        vm.resultLabel.isNotEmpty() && !isCancelled -> NCMP.Green
        else -> NCMP.Brand
    }

    Column(Modifier.fillMaxWidth().padding(top = 22.dp, bottom = 20.dp)) {
        Text(title, fontFamily = FontFamily.Serif, fontSize = 32.sp, fontWeight = FontWeight.Bold, color = titleColor)
        Spacer(Modifier.height(4.dp))
        Text(sub, fontSize = 13.sp, color = NCMP.Muted)

        if (vm.running && vm.currentSong.isNotEmpty()) {
            Spacer(Modifier.height(18.dp))
            Text(
                vm.currentSong,
                fontFamily = FontFamily.Serif,
                fontSize = 21.sp,
                fontWeight = FontWeight.SemiBold,
                color = NCMP.Ink,
                maxLines = 2,
            )
            val meta = buildString {
                append("${vm.progressDone}/${vm.progressTotal}")
                if (vm.currentScore.isNotEmpty()) append("  ·  ${vm.currentScore} 分")
            }
            Spacer(Modifier.height(3.dp))
            Text(meta, fontFamily = FontFamily.Monospace, fontSize = 12.sp, color = NCMP.Muted)
        }

        Spacer(Modifier.height(18.dp))
        SegmentedMeter(
            progress = meterProgress,
            color = meterColor,
            modifier = Modifier.fillMaxWidth().height(18.dp),
        )
        Spacer(Modifier.height(20.dp))

        if (vm.running) {
            OutlinedButton(
                onClick = { vm.cancelTask() },
                modifier = Modifier.fillMaxWidth().height(50.dp),
                shape = RoundedCornerShape(12.dp),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = NCMP.Red),
            ) { Text("取消", fontSize = 16.sp) }
        } else {
            Button(
                onClick = { vm.runTask() },
                modifier = Modifier.fillMaxWidth().height(52.dp),
                shape = RoundedCornerShape(12.dp),
                colors = ButtonDefaults.buttonColors(containerColor = NCMP.Brand),
            ) {
                Icon(Icons.Filled.PlayArrow, contentDescription = null, modifier = Modifier.size(22.dp))
                Spacer(Modifier.width(6.dp))
                Text(
                    when {
                        vm.resultIsError -> "重试"
                        vm.resultLabel.isNotEmpty() && !isCancelled -> "再执行一次"
                        isCancelled -> "重新开始"
                        else -> "开始评分"
                    },
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
        }
    }
}

@Composable
private fun ConfigSection(vm: AppViewModel) {
    var expanded by remember { mutableStateOf(false) }
    val context = LocalContext.current
    Column(Modifier.fillMaxWidth()) {
        Row(
            Modifier.fillMaxWidth().clickable { expanded = !expanded }.padding(vertical = 15.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("任务参数", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = NCMP.Ink, modifier = Modifier.weight(1f))
            Text(if (expanded) "收起" else "展开", fontSize = 12.sp, color = NCMP.Muted)
        }
        if (expanded) {
            Column(Modifier.fillMaxWidth().padding(bottom = 16.dp)) {
                Text("评分策略", fontSize = 12.sp, color = NCMP.Muted)
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
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("完成全部额外任务", fontSize = 14.sp, color = NCMP.Ink, modifier = Modifier.weight(1f))
                    Switch(checked = vm.fullExtra, onCheckedChange = { vm.fullExtra = it })
                }
                Spacer(Modifier.height(12.dp))
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
private fun ColumnScope.LogSection(vm: AppViewModel) {
    val listState = rememberLazyListState()
    val context = LocalContext.current
    LaunchedEffect(vm.logLines.size) {
        if (vm.logLines.isNotEmpty()) listState.scrollToItem(vm.logLines.size - 1)
    }
    Column(Modifier.fillMaxWidth().weight(1f)) {
        Row(
            Modifier.fillMaxWidth().padding(top = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("运行日志", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = NCMP.Ink)
            Spacer(Modifier.width(4.dp))
            TextButton(onClick = {
                val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                cm.setPrimaryClip(ClipData.newPlainText("ncmp log", vm.logLines.joinToString("\n")))
            }) { Text("复制", fontSize = 12.sp) }
            TextButton(onClick = { vm.clearLog() }) { Text("清空", fontSize = 12.sp) }
        }
        if (vm.logLines.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("暂无日志", fontSize = 13.sp, color = NCMP.Muted)
            }
        } else {
            LazyColumn(
                state = listState,
                contentPadding = PaddingValues(top = 4.dp, bottom = 16.dp),
            ) {
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
