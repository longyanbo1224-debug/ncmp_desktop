package com.ncmp.mobile.ui

import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlarmManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.res.Configuration
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.requiredWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
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
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
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
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.ncmp.mobile.R
import com.ncmp.mobile.data.DayRecord
import com.ncmp.mobile.data.Notes
import com.ncmp.mobile.data.PartnerTitles
import com.ncmp.mobile.data.TrackItem
import com.ncmp.mobile.data.TrackState
import com.ncmp.mobile.data.gridDays
import com.ncmp.mobile.data.groupDays
import com.ncmp.mobile.data.streakDays
import com.ncmp.mobile.ui.theme.NCMP
import com.ncmp.mobile.ui.theme.NCMPTheme
import com.ncmp.mobile.ui.widgets.SegmentedMeter
import com.ncmp.mobile.ui.widgets.StreakGrid
import com.ncmp.mobile.ui.widgets.StreakLegend
import kotlinx.coroutines.delay
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale

@Composable
fun NCMPApp(vm: AppViewModel) {
    NCMPTheme {
        Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            if (vm.loggedIn) MainScreen(vm) else LoginScreen(vm)
        }
    }
}

/** 请求「精确闹钟」权限（Android 12+ 定时任务需要，否则定时可能被系统拦截）。 */
private fun ensureExactAlarmPermission(context: Context) {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        try {
            val am = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            if (!am.canScheduleExactAlarms()) {
                context.startActivity(
                    Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM).apply {
                        data = Uri.parse("package:${context.packageName}")
                    },
                )
            }
        } catch (_: Exception) {
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
    Column(Modifier.fillMaxSize().systemBarsPadding().padding(horizontal = 22.dp)) {
        Spacer(Modifier.height(24.dp))
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
                            "(function(){var m=document.querySelector('meta[name=viewport]');if(m){var c=m.getAttribute('content')||'';if(c.indexOf('user-scalable=no')>=0){m.setAttribute('content',c.replace('user-scalable=no','user-scalable=yes'));}}var n=0;function f(){var els=document.querySelectorAll('a,span,div,button,li');for(var i=0;i<els.length;i++){var t=(els[i].textContent||'').trim();if(t==='登录'||t==='立即登录'||t==='登录/注册'){try{els[i].scrollIntoView({block:'center',inline:'center'});}catch(e){}return true;}}return false;}function p(){if(f())return;if(++n<30)setTimeout(p,500);}setTimeout(p,1200);})()",
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
            "页面已自动定位到登录区域，可双指捏合放大缩小。登录后点下方按钮。",
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
        Button(
            onClick = { vm.extractCookieFromWebView() },
            modifier = Modifier.fillMaxWidth().height(48.dp),
            shape = RoundedCornerShape(10.dp),
            colors = ButtonDefaults.buttonColors(containerColor = NCMP.Brand),
        ) { Text("我已登录，获取 Cookie", fontSize = 15.sp, fontWeight = FontWeight.SemiBold) }
        Spacer(Modifier.height(8.dp))
        OutlinedButton(
            onClick = { webView.reload() },
            modifier = Modifier.fillMaxWidth().height(42.dp),
            shape = RoundedCornerShape(10.dp),
        ) {
            Icon(Icons.Filled.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(4.dp))
            Text("刷新页面", fontSize = 13.sp)
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
    var tab by remember { mutableStateOf(0) }
    // 保存设置之类的一次性反馈走底部 Snackbar：比在表单里加一行小字显眼
    val snackbarHostState = remember { SnackbarHostState() }
    LaunchedEffect(vm.saveHint) {
        if (vm.saveHint.isNotEmpty()) {
            snackbarHostState.showSnackbar(
                message = vm.saveHint,
                duration = SnackbarDuration.Short,
            )
            vm.clearSaveHint()
        }
    }
    Scaffold(
        containerColor = NCMP.Ground,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = { Header(vm) },
        bottomBar = {
            NavigationBar(containerColor = NCMP.Panel) {
                NavigationBarItem(
                    selected = tab == 0,
                    onClick = { tab = 0 },
                    icon = { Icon(Icons.Filled.PlayArrow, contentDescription = null) },
                    label = { Text("任务") },
                    colors = NavigationBarItemDefaults.colors(
                        selectedIconColor = NCMP.Brand,
                        selectedTextColor = NCMP.Brand,
                        indicatorColor = NCMP.Soft,
                    ),
                )
                NavigationBarItem(
                    selected = tab == 1,
                    onClick = { tab = 1; vm.refreshHistory() },
                    icon = { Icon(Icons.Filled.Check, contentDescription = null) },
                    label = { Text("记录") },
                    colors = NavigationBarItemDefaults.colors(
                        selectedIconColor = NCMP.Brand,
                        selectedTextColor = NCMP.Brand,
                        indicatorColor = NCMP.Soft,
                    ),
                )
                NavigationBarItem(
                    selected = tab == 2,
                    onClick = { tab = 2 },
                    icon = { Icon(Icons.Filled.Info, contentDescription = null) },
                    label = { Text("关于") },
                    colors = NavigationBarItemDefaults.colors(
                        selectedIconColor = NCMP.Brand,
                        selectedTextColor = NCMP.Brand,
                        indicatorColor = NCMP.Soft,
                    ),
                )
            }
        },
    ) { padding ->
        if (tab == 0) {
            Column(
                Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 22.dp),
            ) {
                // 主视角是曲目表；日志退成兜底（docs/DESIGN.md §5 手机）
                HeroSection(vm)
                ThinRule()
                TrackListSection(vm)
                ThinRule()
                RunDetailSection(vm)
                ThinRule()
                ConfigSection(vm)
            }
        } else if (tab == 1) {
            Column(
                Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(horizontal = 22.dp),
            ) {
                HistoryContent(vm)
            }
        } else {
            AboutContent(Modifier.padding(padding))
        }
    }
}

@Composable
private fun Header(vm: AppViewModel) {
    // 版本号取自安装包信息（项目没开 buildConfig，取 PackageManager 更稳）
    val context = LocalContext.current
    val versionName = remember(context) {
        runCatching {
            context.packageManager.getPackageInfo(context.packageName, 0).versionName
        }.getOrNull().orEmpty()
    }
    Column(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 22.dp)) {
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
                Text(
                    if (versionName.isEmpty()) "ncmp" else "ncmp · v$versionName",
                    fontSize = 11.sp,
                    color = NCMP.Muted,
                )
            }
            IconButton(onClick = { vm.logout() }) {
                Icon(Icons.Filled.Logout, contentDescription = "退出登录", tint = NCMP.Muted)
            }
        }
        ThinRule()
    }
}

/**
 * 页头：日期（宋体 22）+ 一句状态陈述 + 一条细电平表 + 全宽主按钮。
 *
 * 这一行是页面的"话"，其余都是它的注脚（docs/DESIGN.md §5 手机）。
 */
@Composable
private fun HeroSection(vm: AppViewModel) {
    val isCancelled = vm.resultLabel == "已取消"

    // 进度以曲目表为准：它在整轮运行里不会因为阶段切换而回零
    val total = vm.tracks.size
    val done = vm.tracks.count { it.state == TrackState.DONE }
    val notes = vm.tracks.count { it.note.isNotBlank() }
    val tally = "今日 $done/$total · 已提交 $notes 条批注"

    val statusLine: String
    val statusColor: Color
    when {
        vm.running -> {
            statusLine = "评分中 · $tally"
            statusColor = NCMP.AmberText
        }
        vm.resultLabel.isNotEmpty() && vm.resultIsError -> {
            statusLine = "这次没跑完：${vm.resultLabel.removePrefix("失败：")}"
            statusColor = NCMP.Red
        }
        vm.resultLabel.isNotEmpty() && isCancelled -> {
            statusLine = "已取消 · $tally"
            statusColor = NCMP.Muted
        }
        else -> {
            statusLine = tally
            statusColor = NCMP.Muted
        }
    }

    // 用跨阶段的全局进度：基础 5 首跑完不会先顶到 100%，额外任务也不会从 0 重新开始
    val meterProgress = when {
        vm.running -> vm.percent / 100f
        vm.resultLabel.isNotEmpty() && !vm.resultIsError && !isCancelled -> 1f
        vm.percent > 0 -> vm.percent / 100f
        else -> 0f
    }
    val meterColor = when {
        vm.resultIsError -> NCMP.Red
        vm.running -> NCMP.Amber
        isCancelled -> NCMP.Muted
        vm.resultLabel.isNotEmpty() -> NCMP.Green
        else -> NCMP.Brand
    }

    Column(Modifier.fillMaxWidth().padding(top = 18.dp, bottom = 16.dp)) {
        Text(
            todayLine(),
            fontFamily = FontFamily.Serif,
            fontSize = 22.sp,
            fontWeight = FontWeight.Bold,
            color = NCMP.Ink,
        )
        Spacer(Modifier.height(6.dp))
        Text(statusLine, fontSize = 13.sp, color = statusColor)
        Spacer(Modifier.height(16.dp))

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
                Text("开始评分", fontSize = 16.sp, fontWeight = FontWeight.Bold)
            }
        }

        // 电平表收成一条细带，压在页头下方：它说明"进行到哪了"，但不再是主角
        Spacer(Modifier.height(16.dp))
        SegmentedMeter(
            progress = meterProgress,
            color = meterColor,
            modifier = Modifier.fillMaxWidth().height(10.dp),
        )
    }
}

/** 页头日期：10月28日 周二 */
private fun todayLine(): String {
    val calendar = Calendar.getInstance()
    val weekdays = arrayOf("周一", "周二", "周三", "周四", "周五", "周六", "周日")
    val monthDay = SimpleDateFormat("M月d日", Locale.CHINA).format(calendar.time)
    val index = (calendar.get(Calendar.DAY_OF_WEEK) + 5) % 7
    return "$monthDay ${weekdays[index]}"
}

/** 档位标 4⁄5 的颜色：和桌面端同一条规则（设计文档 §4.1）。 */
private fun tierColor(score: String): Color = when (score.trim().toIntOrNull() ?: 0) {
    5, 4 -> NCMP.Ink
    3 -> NCMP.Muted
    else -> NCMP.Red
}

/**
 * 今日曲目表：今天评了哪几首、每首几分、留下了什么批注。
 *
 * 刻意不做卡片：行与行之间只有一条 1px 细线，批注是"引文"（宋体 + 左侧竖线），
 * 不是数据。设计依据见 docs/DESIGN.md §4.1。
 */
@Composable
private fun TrackListSection(vm: AppViewModel) {
    val tracks = vm.tracks
    // 曲目一多就把整页顶下去，所以默认展开、可手动收起；跑完想看结果时再展开
    var expanded by remember { mutableStateOf(true) }
    Column(Modifier.fillMaxWidth().padding(top = 18.dp, bottom = 8.dp)) {
        Row(
            Modifier
                .fillMaxWidth()
                .clickable { expanded = !expanded }
                .padding(vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                if (tracks.isEmpty()) "曲目" else "曲目 ${tracks.size}",
                fontSize = 15.sp,
                fontWeight = FontWeight.SemiBold,
                color = NCMP.Ink,
                modifier = Modifier.weight(1f),
            )
            if (tracks.isNotEmpty()) {
                Text(if (expanded) "收起" else "展开", fontSize = 12.sp, color = NCMP.Muted)
            }
        }
        Spacer(Modifier.height(4.dp))
        if (tracks.isEmpty()) {
            Text(
                "今天还没有排到曲子。点上面的「开始评分」评一次。",
                fontSize = 13.sp,
                color = NCMP.Muted,
                modifier = Modifier.padding(vertical = 20.dp),
            )
        } else if (expanded) {
            tracks.forEachIndexed { index, item ->
                if (index > 0) ThinRule()
                TrackRow(index + 1, item)
            }
        } else {
            // 收起时给一句摘要，别让标题变成孤零零一行
            val done = tracks.count { it.state == TrackState.DONE }
            Text(
                "已提交 $done / ${tracks.size} 首",
                fontSize = 12.sp,
                color = NCMP.Muted,
                modifier = Modifier.padding(bottom = 4.dp),
            )
        }
    }
}

/** 单曲状态 → 文案。用词见 docs/DESIGN.md §6，不得混用同义词。 */
private fun trackStateWord(state: String): String = when (state) {
    TrackState.DONE -> "已提交"
    TrackState.RUNNING -> "评分中"
    TrackState.SKIPPED -> "跳过"
    TrackState.FAILED -> "失败"
    else -> "待评"
}

/** 单曲状态 → 圆点颜色。状态不只靠颜色：文字永远在旁边。 */
private fun trackStateColor(state: String): Color = when (state) {
    TrackState.DONE -> NCMP.Green
    TrackState.RUNNING -> NCMP.Amber
    TrackState.FAILED -> NCMP.Red
    else -> NCMP.Muted
}

/**
 * 一行曲目：`01 │ 歌名（宋体 15） 4⁄5 ●已提交`，下一行是歌手，再下面才是批注。
 * 序号是合法的——今日曲目本来就是一个有序队列。
 */
@Composable
private fun TrackRow(index: Int, item: TrackItem) {
    Row(Modifier.fillMaxWidth().padding(vertical = 14.dp), verticalAlignment = Alignment.Top) {
        Text(
            "%02d".format(index),
            fontFamily = FontFamily.Serif,
            fontSize = 12.sp,
            color = NCMP.Muted,
            textAlign = TextAlign.Right,
            modifier = Modifier.width(24.dp),
        )
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    item.song,
                    fontFamily = FontFamily.Serif,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = NCMP.Ink,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                if (item.score.isNotBlank()) {
                    Spacer(Modifier.width(8.dp))
                    // 档位标 4⁄5：全应用唯一的"分数表达"，用分数斜线不用 /
                    Text(
                        "${item.score}⁄5",
                        fontFamily = FontFamily.Serif,
                        fontSize = 15.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = tierColor(item.score),
                    )
                }
                Spacer(Modifier.width(10.dp))
                Box(Modifier.size(6.dp).background(trackStateColor(item.state), CircleShape))
                Spacer(Modifier.width(5.dp))
                Text(
                    trackStateWord(item.state),
                    fontSize = 12.sp,
                    color = if (item.state == TrackState.DONE) NCMP.Ink else NCMP.Muted,
                )
            }
            if (item.artist.isNotBlank()) {
                Spacer(Modifier.height(3.dp))
                Text(item.artist, fontSize = 12.sp, color = NCMP.Muted)
            }
            if (item.note.isNotBlank()) {
                // 批注是"引文"：宋体 13 / 行高 1.7 / 左侧一根 1px 竖线
                Spacer(Modifier.height(8.dp))
                Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
                    Box(Modifier.width(1.dp).fillMaxHeight().background(NCMP.Rule))
                    Spacer(Modifier.width(10.dp))
                    Text(
                        item.note,
                        fontFamily = FontFamily.Serif,
                        fontSize = 13.sp,
                        lineHeight = 22.sp,
                        color = NCMP.Ink,
                        modifier = Modifier.weight(1f),
                    )
                }
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
                Spacer(Modifier.height(6.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("启用批注", fontSize = 14.sp, color = NCMP.Ink, modifier = Modifier.weight(1f))
                    Switch(checked = vm.noteEnabled, onCheckedChange = { vm.noteEnabled = it })
                }
                Spacer(Modifier.height(4.dp))
                Text(
                    // 手机端没有「账本」页：批注的去处就是上面的曲目表，文案照这个事实写
                    if (vm.noteEnabled) "批注会随评分一起提交，每一条都留在上面的曲目表里"
                    else "只评分，不写批注。",
                    fontSize = 11.sp,
                    color = NCMP.Muted,
                )
                if (vm.noteEnabled) {
                    Spacer(Modifier.height(10.dp))
                    Text("语气", fontSize = 12.sp, color = NCMP.Muted)
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Notes.VOICES.forEach { value ->
                            FilterChip(
                                selected = vm.noteVoice == value,
                                onClick = { vm.noteVoice = value },
                                label = { Text(Notes.voiceLabel(value), fontSize = 12.sp) },
                            )
                        }
                    }
                    Spacer(Modifier.height(10.dp))
                    Text("批注长度", fontSize = 12.sp, color = NCMP.Muted)
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(
                            "brief" to "简短",
                            "standard" to "标准",
                            "detailed" to "详细",
                        ).forEach { (value, label) ->
                            FilterChip(
                                selected = vm.noteLength == value,
                                onClick = { vm.noteLength = value },
                                label = { Text(label, fontSize = 12.sp) },
                            )
                        }
                    }
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "本地生成，不联网、不调用 AI；同一首歌每次生成同一句",
                        fontSize = 11.sp,
                        color = NCMP.Muted,
                    )
                }
                Spacer(Modifier.height(6.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("定时执行", fontSize = 14.sp, color = NCMP.Ink, modifier = Modifier.weight(1f))
                    Switch(checked = vm.scheduleEnabled, onCheckedChange = { vm.scheduleEnabled = it })
                }
                if (vm.scheduleEnabled) {
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = vm.scheduleTimeText,
                        onValueChange = { vm.scheduleTimeText = it },
                        label = { Text("每天执行时间 (HH:mm)") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(4.dp))
                    Text(
                        "系统省电策略可能延迟或拦截定时，建议先做下方「后台保活设置」",
                        fontSize = 11.sp,
                        color = NCMP.Muted,
                    )
                }
                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button(
                        onClick = {
                            vm.saveConfig()
                            if (vm.scheduleEnabled) ensureExactAlarmPermission(context)
                        },
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

/** 档位条的颜色：和曲目行档位标同一条规则（4-5 墨色 / 3 灰 / 1-2 红）。 */
private fun tierBarColor(tier: String): Color = when (tier) {
    "5", "4" -> NCMP.Ink
    "3" -> NCMP.Muted
    else -> NCMP.Red
}

/** 三个数：小标签 + 宋体大字，和桌面端记录页一致。 */
@Composable
private fun StatCell(label: String, value: String, modifier: Modifier = Modifier) {
    Column(modifier) {
        Text(label, fontSize = 11.sp, color = NCMP.Muted)
        Spacer(Modifier.height(2.dp))
        Text(
            value,
            fontFamily = FontFamily.Serif,
            fontSize = 22.sp,
            fontWeight = FontWeight.Bold,
            color = NCMP.Ink,
        )
    }
}

/** 一行键值（合伙人积分 / 称号表共用）。small = 阈值表这种次要信息用。 */
@Composable
private fun PointsRow(label: String, value: String, small: Boolean = false) {
    Row(Modifier.fillMaxWidth().padding(vertical = if (small) 1.dp else 2.dp)) {
        Text(
            label,
            fontSize = if (small) 11.sp else 12.sp,
            color = NCMP.Muted,
            modifier = Modifier.width(if (small) 56.dp else 88.dp),
        )
        Text(
            value,
            fontFamily = if (small) FontFamily.Default else FontFamily.Serif,
            fontSize = if (small) 11.sp else 15.sp,
            color = if (small) NCMP.Muted else NCMP.Ink,
        )
    }
}

/**
 * 记录页的"口味"块：累计曲目 / 档位分布 / 最近评过的曲子。
 *
 * 对齐桌面端记录页——完成率首页已经有了，这里想看的是"我评过什么、我偏向几分"。
 * 数据来自按曲目的本地记录（TrackLogStore），没有记录时给一句引导。
 */
@Composable
private fun LedgerSection(vm: AppViewModel) {
    val stats = vm.trackStats
    if (stats.total == 0) {
        Spacer(Modifier.height(18.dp))
        Text(
            "还没有曲目记录。跑一次评分之后，这里会长出你自己的口味曲线。",
            fontSize = 12.sp,
            color = NCMP.Muted,
        )
        return
    }

    Spacer(Modifier.height(20.dp))
    ThinRule()
    Spacer(Modifier.height(18.dp))
    Text("口味曲线", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = NCMP.Ink)
    Spacer(Modifier.height(8.dp))
    ThinRule()
    Spacer(Modifier.height(12.dp))

    val peak = stats.maxTierCount().coerceAtLeast(1)
    for (tier in listOf("5", "4", "3", "2", "1")) {
        val count = stats.tiers[tier] ?: 0
        Row(
            Modifier.fillMaxWidth().padding(vertical = 3.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "$tier 分",
                fontFamily = FontFamily.Serif,
                fontSize = 12.sp,
                color = NCMP.Muted,
                modifier = Modifier.width(34.dp),
            )
            Box(Modifier.weight(1f).height(8.dp)) {
                if (count > 0) {
                    Box(
                        Modifier
                            .fillMaxWidth(count.toFloat() / peak)
                            .height(8.dp)
                            .background(tierBarColor(tier)),
                    )
                }
            }
            Spacer(Modifier.width(10.dp))
            Text(
                "$count 首",
                fontSize = 11.sp,
                color = NCMP.Muted,
                modifier = Modifier.width(44.dp),
            )
        }
    }

    Spacer(Modifier.height(18.dp))
    ThinRule()
    Spacer(Modifier.height(16.dp))
    // 最近曲目可能几十条，默认收起，点标题展开
    var recentExpanded by remember { mutableStateOf(false) }
    Row(
        Modifier
            .fillMaxWidth()
            .clickable { recentExpanded = !recentExpanded }
            .padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            "最近评过的曲子 ${vm.recentTracks.size}",
            fontSize = 15.sp,
            fontWeight = FontWeight.SemiBold,
            color = NCMP.Ink,
            modifier = Modifier.weight(1f),
        )
        Text(
            if (recentExpanded) "收起" else "展开",
            fontSize = 12.sp,
            color = NCMP.Muted,
        )
    }
    if (recentExpanded) {
        Spacer(Modifier.height(4.dp))
        vm.recentTracks.forEachIndexed { index, record ->
            if (index > 0) ThinRule()
            TrackRow(
                index + 1,
                TrackItem(
                    song = record.song,
                    artist = record.artist,
                    score = record.score,
                    note = record.note,
                    state = TrackState.DONE,
                ),
            )
        }
    }
}

private const val GITHUB_URL = "https://github.com/longyanbo1224-debug/ncmp_desktop"
private const val RELEASES_URL = "$GITHUB_URL/releases"

/**
 * 关于页：版本、项目链接、参考来源与免责声明。
 *
 * 手机端以前只有顶栏一行版本号，找不到项目主页、更新地址和许可信息。
 */
@Composable
private fun AboutContent(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val versionName = remember(context) {
        runCatching {
            context.packageManager.getPackageInfo(context.packageName, 0).versionName
        }.getOrNull().orEmpty()
    }
    Column(
        modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 22.dp),
    ) {
        Spacer(Modifier.height(18.dp))
        Text(
            "关于",
            fontFamily = FontFamily.Serif,
            fontSize = 22.sp,
            fontWeight = FontWeight.Bold,
            color = NCMP.Ink,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            if (versionName.isEmpty()) "ncmp mobile" else "ncmp mobile · v$versionName",
            fontSize = 13.sp,
            color = NCMP.Muted,
        )

        Spacer(Modifier.height(22.dp))
        AboutHeading("项目")
        AboutLink(context, "GitHub", GITHUB_URL)
        ThinRule()
        AboutLink(context, "更新与下载", RELEASES_URL)
        ThinRule()
        AboutLink(context, "参考项目 3899/ncmm", "https://github.com/3899/ncmm")

        Spacer(Modifier.height(22.dp))
        AboutHeading("说明")
        Text(
            "非官方第三方程序，与网易云音乐无关联；仅供个人学习、研究使用，使用风险自负。" +
                "评分时提交的批注会以你自己的身份公开显示在账号下。",
            fontSize = 12.sp,
            color = NCMP.Muted,
            lineHeight = 20.sp,
        )

        Spacer(Modifier.height(18.dp))
        Text("作者 Loong · MIT License", fontSize = 12.sp, color = NCMP.Muted)
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun AboutHeading(title: String) {
    Text(title, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = NCMP.Ink)
    Spacer(Modifier.height(8.dp))
    ThinRule()
}

@Composable
private fun AboutLink(context: Context, label: String, url: String) {
    Text(
        label,
        fontSize = 13.sp,
        color = NCMP.Brand,
        modifier = Modifier
            .fillMaxWidth()
            .clickable {
                runCatching {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                }
            }
            .padding(vertical = 12.dp),
    )
}

@Composable
private fun HistoryContent(vm: AppViewModel) {
    // toList() 会读取快照状态：历史一更新就重组，不能直接拿可变列表当 remember 的 key
    val runs = vm.history.toList()
    val cells = remember(runs) { gridDays(runs) }
    val days = remember(runs) { groupDays(runs) }
    val streak = remember(cells) { streakDays(cells) }
    val successDays = remember(cells) { cells.count { it.status == "success" } }

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(top = 18.dp, bottom = 24.dp),
    ) {
        item {
            Text(
                "打卡记录",
                fontFamily = FontFamily.Serif,
                fontSize = 22.sp,
                fontWeight = FontWeight.Bold,
                color = NCMP.Ink,
            )
            Spacer(Modifier.height(14.dp))
            // 和桌面端记录页同一个顺序：先三个数，再分块
            Row(Modifier.fillMaxWidth()) {
                StatCell("连续", "$streak 天", Modifier.weight(1f))
                StatCell("累计曲目", "${vm.trackStats.total} 首", Modifier.weight(1f))
                StatCell("累计批注", "${vm.trackStats.notes} 条", Modifier.weight(1f))
            }
            if (vm.points.isNotEmpty()) {
                Spacer(Modifier.height(16.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "合伙人",
                        fontSize = 15.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = NCMP.Ink,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = { vm.refreshPoints() }) {
                        Text("刷新", fontSize = 12.sp, color = NCMP.Brand)
                    }
                }
                Spacer(Modifier.height(4.dp))
                vm.points.forEach { (label, value) -> PointsRow(label, value) }
                // 称号：当前档 + 距下一档还差多少 + 完整阈值表
                val title = PartnerTitles.titleFor(PartnerTitles.scoreOf(vm.points))
                if (title.label.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    PointsRow("当前称号", title.label)
                    if (title.nextLabel != null && title.gap != null) {
                        PointsRow("距下一档", "${title.nextLabel}（还差 ${title.gap} 分）")
                    }
                    Spacer(Modifier.height(6.dp))
                    title.table.forEach { (threshold, name) ->
                        PointsRow("$threshold 分", name, small = true)
                    }
                }
            }
            Spacer(Modifier.height(22.dp))
            // 和桌面端同一个分组骨架：小标题（15sp 半粗）+ 细线 + 内容
            Text("坚持", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = NCMP.Ink)
            Spacer(Modifier.height(8.dp))
            ThinRule()
            Spacer(Modifier.height(10.dp))
            Text("过去一年，每格一天 · 点一下放大看", fontSize = 12.sp, color = NCMP.Muted)
            Spacer(Modifier.height(14.dp))
            // 点一下：整屏浮层放大显示格子图（不旋转整个应用）。
            // 浮层里把格子尺寸上限放宽，横过来的时候格子才会真的变大；再点一下退出。
            var zoomed by remember { mutableStateOf(false) }
            Box(Modifier.fillMaxWidth().clickable { zoomed = true }) { StreakGrid(cells) }
            if (zoomed) {
                Dialog(
                    onDismissRequest = { zoomed = false },
                    properties = DialogProperties(usePlatformDefaultWidth = false),
                ) {
                    Box(
                        Modifier
                            .fillMaxSize()
                            // 用页面底色而不是黑底：放大后仍然像"这一页被拿起来看"，
                            // 而不是弹出一个遮罩层；点任意处退出。
                            .background(NCMP.Ground)
                            .clickable { zoomed = false },
                        contentAlignment = Alignment.Center,
                    ) {
                        // 只在**竖屏**时把图转 90°：53 列贴着长边铺开，格子才放得大。
                        // 横屏（平板通常这样用）本来宽度就够，再转 90° 等于把宽方向
                        // 压成高度，图反而变小——那种情况直接用整屏宽度。
                        BoxWithConstraints(Modifier.fillMaxSize()) {
                            if (maxHeight > maxWidth) {
                                Box(
                                    Modifier
                                        .requiredWidth(maxHeight - 24.dp)
                                        .rotate(90f)
                                        .align(Alignment.Center),
                                ) {
                                    StreakGrid(cells)
                                }
                            } else {
                                Box(
                                    Modifier
                                        .fillMaxWidth()
                                        .padding(horizontal = 24.dp)
                                        .align(Alignment.Center),
                                ) {
                                    StreakGrid(cells)
                                }
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.height(10.dp))
            StreakLegend(streak, successDays)
            LedgerSection(vm)
            Spacer(Modifier.height(20.dp))
            ThinRule()
            Spacer(Modifier.height(18.dp))
            Text(
                "执行情况",
                fontFamily = FontFamily.Serif,
                fontSize = 20.sp,
                fontWeight = FontWeight.Bold,
                color = NCMP.Ink,
            )
            Spacer(Modifier.height(3.dp))
            Text(
                "一天一条；同一天多次执行合并在这里，点开看明细",
                fontSize = 12.sp,
                color = NCMP.Muted,
            )
            Spacer(Modifier.height(6.dp))
        }

        if (days.isEmpty()) {
            item {
                Box(
                    Modifier.fillMaxWidth().padding(vertical = 40.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        "还没有执行记录，去「任务」页跑第一次",
                        fontSize = 13.sp,
                        color = NCMP.Muted,
                    )
                }
            }
        } else {
            items(days, key = { it.date }) { day ->
                DayRow(day)
            }
        }
    }
}

/** 一天一条：默认只显示结论，点开看当天的每一次执行。 */
@Composable
private fun DayRow(day: DayRecord) {
    var expanded by remember(day.date) { mutableStateOf(false) }
    val latest = day.runs.firstOrNull()
    val summary = if (day.runs.size == 1) {
        latest?.message.orEmpty()
    } else {
        "执行 ${day.runs.size} 次，最近 ${latest?.time.orEmpty()} ${statusWord(latest?.status.orEmpty())}"
    }

    Column(
        Modifier
            .fillMaxWidth()
            .clickable { expanded = !expanded }
            .padding(vertical = 12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                dayTitle(day.date),
                fontSize = 14.sp,
                fontWeight = FontWeight.SemiBold,
                color = NCMP.Ink,
            )
            Spacer(Modifier.width(6.dp))
            Text(weekdayOf(day.date), fontSize = 11.sp, color = NCMP.Muted)
            Spacer(Modifier.weight(1f))
            Text(
                statusWord(day.status),
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
                color = statusColor(day.status),
            )
            Icon(
                imageVector = if (expanded) Icons.Filled.KeyboardArrowUp
                else Icons.Filled.KeyboardArrowDown,
                contentDescription = if (expanded) "收起" else "展开",
                tint = NCMP.Muted,
                modifier = Modifier.size(18.dp),
            )
        }
        Spacer(Modifier.height(3.dp))
        Text(
            summary,
            fontSize = 12.sp,
            color = NCMP.Muted,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )

        if (expanded) {
            Spacer(Modifier.height(10.dp))
            Surface(
                color = NCMP.Panel,
                shape = RoundedCornerShape(10.dp),
                border = BorderStroke(1.dp, NCMP.Rule),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
                    day.runs.forEachIndexed { index, run ->
                        if (index > 0) {
                            Spacer(Modifier.height(8.dp))
                            ThinRule()
                            Spacer(Modifier.height(8.dp))
                        }
                        Row(verticalAlignment = Alignment.Top) {
                            Text(
                                run.time.ifEmpty { "--" },
                                fontFamily = FontFamily.Monospace,
                                fontSize = 12.sp,
                                color = NCMP.Muted,
                                modifier = Modifier.width(44.dp),
                            )
                            Text(
                                statusWord(run.status),
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold,
                                color = statusColor(run.status),
                                modifier = Modifier.width(38.dp),
                            )
                            Column(Modifier.weight(1f)) {
                                Text(run.message, fontSize = 12.sp, color = NCMP.Ink)
                                if (run.detail.isNotEmpty()) {
                                    Spacer(Modifier.height(2.dp))
                                    Text(run.detail, fontSize = 11.sp, color = NCMP.Muted)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    ThinRule()
}

private fun statusColor(status: String): Color = when (status) {
    "success" -> NCMP.Green
    "fail" -> NCMP.Red
    "cancel" -> NCMP.AmberText
    else -> NCMP.Muted
}

private fun statusWord(status: String): String = when (status) {
    "success" -> "成功"
    "fail" -> "失败"
    "cancel" -> "取消"
    else -> "记录"
}

private fun dayTitle(date: String): String {
    val parts = date.split("-")
    if (parts.size != 3) return date
    val month = parts[1].toIntOrNull() ?: return date
    val day = parts[2].toIntOrNull() ?: return date
    return "${month}月${day}日"
}

private fun weekdayOf(date: String): String = try {
    val cal = Calendar.getInstance().apply {
        time = SimpleDateFormat("yyyy-MM-dd", Locale.US).parse(date)!!
    }
    listOf("周日", "周一", "周二", "周三", "周四", "周五", "周六")[
        cal.get(Calendar.DAY_OF_WEEK) - 1
    ]
} catch (_: Exception) {
    ""
}

/**
 * 运行详情（docs/DESIGN.md §4.3）：原来的步骤与日志收进折叠区，默认收起，
 * **只在失败时自动展开**。这是"过程可见"的兜底，不再是主视角。
 */
@Composable
private fun RunDetailSection(vm: AppViewModel) {
    var expanded by remember { mutableStateOf(false) }
    // 新的一次执行从收起开始
    LaunchedEffect(vm.running) {
        if (vm.running) expanded = false
    }
    // 失败时自动展开：这是用户唯一需要看日志的时刻
    LaunchedEffect(vm.resultIsError) {
        if (vm.resultIsError) expanded = true
    }
    Column(Modifier.fillMaxWidth()) {
        Row(
            Modifier.fillMaxWidth().clickable { expanded = !expanded }.padding(vertical = 15.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "运行详情",
                fontSize = 15.sp,
                fontWeight = FontWeight.SemiBold,
                color = NCMP.Ink,
                modifier = Modifier.weight(1f),
            )
            Text(if (expanded) "收起" else "展开", fontSize = 12.sp, color = NCMP.Muted)
        }
        if (expanded) {
            Column(Modifier.fillMaxWidth().padding(bottom = 14.dp)) {
                if (vm.resultIsError) {
                    Text(
                        "这次没跑完：${vm.resultLabel.removePrefix("失败：")}",
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = NCMP.Red,
                    )
                    if (vm.resultHint.isNotEmpty()) {
                        Spacer(Modifier.height(4.dp))
                        Text(vm.resultHint, fontSize = 12.sp, color = NCMP.Muted)
                    }
                    Spacer(Modifier.height(12.dp))
                }
                LogSection(vm)
            }
        }
    }
}

@Composable
private fun LogSection(vm: AppViewModel) {
    val listState = rememberLazyListState()
    val context = LocalContext.current
    LaunchedEffect(vm.logLines.size) {
        if (vm.logLines.isNotEmpty()) listState.scrollToItem(vm.logLines.size - 1)
    }
    Column(Modifier.fillMaxWidth().height(240.dp)) {
        Row(
            Modifier.fillMaxWidth().padding(bottom = 4.dp),
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
        Surface(
            color = Color.White,
            shape = RoundedCornerShape(12.dp),
            border = BorderStroke(1.dp, NCMP.Rule),
            modifier = Modifier.fillMaxSize(),
        ) {
            if (vm.logLines.isEmpty()) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text("暂无日志", fontSize = 13.sp, color = NCMP.Muted)
                }
            } else {
                LazyColumn(
                    state = listState,
                    contentPadding = PaddingValues(10.dp),
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
}
