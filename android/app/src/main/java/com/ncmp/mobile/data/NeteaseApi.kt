package com.ncmp.mobile.data

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.FormBody
import okhttp3.Headers
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import kotlin.random.Random

/**
 * 网易云音乐 API 客户端（登录 + 音乐合伙人任务）。
 *
 * Cookie 用 OkHttp 的 CookieJar 自动管理（等价于桌面版 requests.Session 的行为）：
 * 登录接口 Set-Cookie 里的 MUSIC_U / __csrf 会被自动保存并在后续请求中带上。
 */
class NeteaseApi {
    private val cookies = ConcurrentHashMap<String, String>()

    /** 登录态 Cookie（任务请求与桌面版 core 一样只依赖这两枚）。 */
    var musicU: String?
        get() = cookies["MUSIC_U"]
        set(value) {
            if (value == null) cookies.remove("MUSIC_U") else cookies["MUSIC_U"] = value
        }
    var csrf: String?
        get() = cookies["__csrf"]
        set(value) {
            if (value == null) cookies.remove("__csrf") else cookies["__csrf"] = value
        }

    /** 调试日志回调（把 WeAPI 原始响应显示到界面日志）。 */
    var debugLogger: ((String) -> Unit)? = null

    // 扫码 / 密码登录所需的会话配置（一次进程内固定）
    private val sDeviceId = "unknown-${Random.nextInt(1000000)}"
    private val wnMCID = generateWNMCID()
    private val deviceId = (1..32).map { "0123456789abcdef".random() }.joinToString("")

    private val client = OkHttpClient.Builder()
        .protocols(listOf(Protocol.HTTP_1_1))
        .cookieJar(object : CookieJar {
            override fun saveFromResponse(url: HttpUrl, cookieList: List<Cookie>) {
                for (c in cookieList) {
                    if (c.value.isEmpty()) cookies.remove(c.name) else cookies[c.name] = c.value
                }
            }

            override fun loadForRequest(url: HttpUrl): List<Cookie> =
                cookies.entries
                    .filter { it.value.isNotEmpty() }
                    .map { (name, value) ->
                        Cookie.Builder().domain(url.host).name(name).value(value).path("/").build()
                    }
        })
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    init {
        // 任务请求只需 MUSIC_U + __csrf（与桌面版 core 的 plain session 一致）。
        // 不再全局塞 WEVNSM/sDeviceId/WNMCID：那是扫码登录用的，且与 WebView 登录会话的设备指纹不一致。
    }

    // ------------------------------------------------------------------
    // 底层请求
    // ------------------------------------------------------------------

    /** 登录前先访问首页，建立会话 cookie，降低风控误判概率。 */
    private suspend fun warmUp() {
        try {
            val request = Request.Builder()
                .url("https://music.163.com/")
                .header("User-Agent", UA_DEFAULT)
                .build()
            client.newCall(request).execute().use { it.body?.close() }
        } catch (_: Exception) {
            // 忽略
        }
    }

    /** 普通 GET，返回解析后的 JSONObject。 */
    suspend fun getJson(url: String, referer: String? = null): JSONObject =
        withContext(Dispatchers.IO) {
            val headers = Headers.Builder()
                .add("User-Agent", UA_DEFAULT)
            referer?.let { headers.add("Referer", it) }
            val request = Request.Builder().url(url).get().headers(headers.build()).build()
            client.newCall(request).execute().use { resp ->
                parseJson(resp.body?.string())
            }
        }

    /** WeAPI POST（自动加 csrf_token 与 ?csrf_token= 查询参数）。 */
    suspend fun weapiPost(url: String, payload: JSONObject, referer: String? = null): JSONObject =
        withContext(Dispatchers.IO) {
            payload.put("csrf_token", csrf ?: "")
            val enc = NeteaseCrypto.weapiEncrypt(payload.toString())
            val body = FormBody.Builder()
                .add("params", enc["params"]!!)
                .add("encSecKey", enc["encSecKey"]!!)
                .build()
            val headers = Headers.Builder()
                .add("User-Agent", UA_DEFAULT)
                .add("Referer", referer ?: "https://music.163.com")
            val fullUrl = "$url?csrf_token=${csrf ?: ""}"
            val request = Request.Builder().url(fullUrl).post(body).headers(headers.build()).build()
            client.newCall(request).execute().use { resp ->
                val text = resp.body?.string()
                android.util.Log.e(
                    "ncmp",
                    "weapiPost $url -> http=${resp.code} len=${text?.length} ct=${resp.header("Content-Type")} body=[$text]",
                )
                debugLogger?.invoke("weapi $url -> [${resp.code}] len=${text?.length} $text")
                parseJson(text)
            }
        }

    private fun parseJson(text: String?): JSONObject =
        JSONObject(if (text.isNullOrBlank()) "{}" else text)

    // ------------------------------------------------------------------
    // 登录：密码（EAPI）
    // ------------------------------------------------------------------

    suspend fun passwordLogin(phone: String, md5Password: String): LoginResult =
        withContext(Dispatchers.IO) {
            warmUp()
            val eapiConfig = JSONObject().apply {
                put("os", "iPhone OS")
                put("appver", "10.0.0")
                put("osver", "16.2")
                put("channel", "distribution")
                put("deviceId", deviceId)
            }
            val header = JSONObject(eapiConfig.toString()).apply {
                put("requestId", Random.nextInt(20000000, 30000000).toString())
            }
            val payload = JSONObject().apply {
                put("type", "1")
                put("phone", phone)
                put("remember", "true")
                put("countrycode", "86")
                put("checkToken", "")
                put("password", md5Password)
                put("header", header.toString())
            }
            val params = NeteaseCrypto.eapiEncrypt(LOGIN_PATH, payload.toString())
            val body = FormBody.Builder().add("params", params).build()
            val request = Request.Builder()
                .url("https://music.163.com$LOGIN_PATH")
                .post(body)
                .header("User-Agent", UA_EAPI)
                .header("Referer", "")
                .build()

            try {
                client.newCall(request).execute().use { resp ->
                    val bytes = resp.body?.bytes()
                    if (bytes == null || bytes.isEmpty()) {
                        return@withContext LoginResult.failure("登录失败：空响应")
                    }
                    val json = try {
                        JSONObject(
                            NeteaseCrypto.eapiDecrypt(bytes)
                                .toString(Charsets.UTF_8)
                                .trim('\u0010', ' '),
                        )
                    } catch (_: Exception) {
                        // 失败时服务端返回的是明文 JSON，直接解析即可
                        JSONObject(String(bytes, Charsets.UTF_8).trim('\u0010', ' '))
                    }
                    val code = json.optInt("code", -1)
                    if (code != 200) {
                        val msg = json.optString("message", json.optString("msg", "登录失败"))
                        return@withContext LoginResult.failure("$msg (code=$code)", code)
                    }
                    extractCookies(json)
                    if (musicU.isNullOrEmpty() || csrf.isNullOrEmpty()) {
                        return@withContext LoginResult.failure("登录成功但未获取到 Cookie", code)
                    }
                    return@withContext LoginResult.success(musicU, csrf)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                android.util.Log.e("ncmp", "passwordLogin error", e)
                return@withContext LoginResult.failure("登录失败：${e.message}")
            }
        }

    // ------------------------------------------------------------------
    // 登录：扫码（WeAPI）
    // ------------------------------------------------------------------

    suspend fun qrUnikey(): String = withContext(Dispatchers.IO) {
        warmUp()
        val payload = JSONObject().apply {
            put("type", "1")
            put("noCheckToken", true)
            put("csrf_token", csrf ?: "")
        }
        val enc = NeteaseCrypto.weapiEncrypt(payload.toString())
        val body = FormBody.Builder()
            .add("params", enc["params"]!!)
            .add("encSecKey", enc["encSecKey"]!!)
            .build()
        val request = Request.Builder()
            .url("https://music.163.com/weapi/login/qrcode/unikey")
            .post(body)
            .header("User-Agent", UA_DEFAULT)
            .header("Referer", "https://music.163.com")
            .build()
        client.newCall(request).execute().use { resp ->
            val text = resp.body?.string()
            android.util.Log.e("ncmp", "qrUnikey http=${resp.code} resp=$text")
            val json = parseJson(text)
            val unikey = json.optString("unikey", "")
            if (unikey.isEmpty()) throw IOException("获取二维码令牌失败：$json")
            extractCookies(json)
            unikey
        }
    }

    fun qrCodeUrl(unikey: String): String {
        val chainId = "v1_${sDeviceId}_web_login_${System.currentTimeMillis()}"
        return "http://music.163.com/login?codekey=$unikey&chainId=$chainId"
    }

    suspend fun qrCheck(unikey: String): QrStatus = withContext(Dispatchers.IO) {
        val payload = JSONObject().apply {
            put("type", 1)
            put("key", unikey)
            put("noCheckToken", true)
            put("csrf_token", csrf ?: "")
        }
        val enc = NeteaseCrypto.weapiEncrypt(payload.toString())
        val body = FormBody.Builder()
            .add("params", enc["params"]!!)
            .add("encSecKey", enc["encSecKey"]!!)
            .build()
        val request = Request.Builder()
            .url("https://music.163.com/weapi/login/qrcode/client/login")
            .post(body)
            .header("User-Agent", UA_DEFAULT)
            .header("Referer", "https://music.163.com")
            .build()
        client.newCall(request).execute().use { resp ->
            val json = parseJson(resp.body?.string())
            val code = json.optInt("code", 0)
            if (code == 803) extractCookies(json)
            QrStatus(code, musicU, csrf)
        }
    }

    // ------------------------------------------------------------------
    // 任务
    // ------------------------------------------------------------------

    suspend fun verifyUser(): String {
        val json = getJson(VERIFY_URL)
        val profile = json.optJSONObject("profile")
            ?: throw IOException("验证用户信息失败：获取用户信息失败")
        val nickname = profile.optString("nickname", "")
        if (nickname.isEmpty()) throw IOException("验证用户信息失败：获取用户信息失败")
        return nickname
    }

    suspend fun signIn(): Pair<Boolean, String> {
        return try {
            val payload = JSONObject().apply { put("type", "0") }
            val resp = weapiPost(SIGN_IN_URL, payload)
            val code = resp.optInt("code", -1)
            when (code) {
                200 -> {
                    val point = resp.opt("point")
                    val msg = if (point != null) "签到成功，获得 $point 点经验" else "签到成功"
                    true to msg
                }
                -2 -> true to "今天已经签过了"
                301 -> false to "签到失败：需要重新登录"
                else -> false to "签到未完成（code=$code）"
            }
        } catch (e: Exception) {
            false to "签到请求失败（${e.message}）"
        }
    }

    suspend fun getDailyTasks(): DailyTasks {
        val json = getJson(DAILY_TASK_URL)
        val data = json.optJSONObject("data") ?: JSONObject()
        val id = data.opt("id") ?: ""
        val count = data.optInt("count", 0)
        val completedCount = data.optInt("completedCount", 0)
        val items = mutableListOf<WorkItem>()
        val works = data.optJSONArray("works") ?: JSONArray()
        for (i in 0 until works.length()) {
            val item = works.optJSONObject(i) ?: continue
            val work = item.optJSONObject("work") ?: continue
            items.add(
                WorkItem(
                    parseWork(work),
                    item.optBoolean("completed", false),
                    item.optString("score", ""),
                ),
            )
        }
        return DailyTasks(id, count, completedCount, items)
    }

    /** 返回 (整份清单, 已完成数量)。整份都要：已评的也要显示在曲目表里。 */
    suspend fun getExtraTasks(): Pair<List<WorkItem>, Int> {
        val json = getJson(EXTRA_LIST_URL, referer = "https://mp.music.163.com/")
        if (json.optInt("code", -1) != 200) {
            throw IOException("获取额外任务失败：${json.optString("message", "未知错误")}")
        }
        val arr = json.optJSONArray("data") ?: throw IOException("获取额外任务失败：无数据")
        val items = mutableListOf<WorkItem>()
        for (i in 0 until arr.length()) {
            val item = arr.optJSONObject(i) ?: continue
            val work = item.optJSONObject("work") ?: continue
            items.add(
                WorkItem(
                    parseWork(work),
                    item.optBoolean("completed", false),
                    item.optString("score", ""),
                ),
            )
        }
        val completedCount = items.count { it.completed }
        return items to completedCount
    }

    /** 确认某首是否已评上：**只查一次**，用于"写入结果不明"，绝不重投评分。 */
    suspend fun isWorkRated(workId: Any): Boolean = try {
        getDailyTasks().items.any {
            it.completed && it.work.id.toString() == workId.toString()
        }
    } catch (_: Exception) {
        false
    }

    /** 合伙人积分/等级；拿不到返回空 Map（界面"没数据就不显示"）。 */
    suspend fun getPartnerPoints(): Map<String, String> {
        val json = try {
            // 合伙人接口在 mp 域下：带和额外任务列表同一个 Referer
            weapiPost(PARTNER_HOME_URL, JSONObject(), referer = "https://mp.music.163.com/")
        } catch (e: Exception) {
            debugLogger?.invoke("合伙人积分查询失败：${e.message}")
            return emptyMap()
        }
        val code = json.optInt("code", -1)
        if (code != 200) {
            debugLogger?.invoke(
                "合伙人积分查询返回 code=$code ${json.optString("message")}",
            )
            return emptyMap()
        }
        val flat = mutableMapOf<String, String>()
        json.optJSONObject("data")?.let { flattenJson(it, flat) }
        // data 不是对象（或字段直接在顶层）时兜底：整份响应摊平再找
        if (flat.isEmpty()) flattenJson(json, flat)
        val fields = listOf(
            "云贝余额" to listOf("cloudBean", "cloudBeanCount", "cloudVillageBean", "cloud_bean"),
            "VIP 等级" to listOf("vipType", "vipLevel", "vip_type", "level"),
            "成长总值" to listOf("growthValue", "growth_value", "growth"),
            "本期积分" to listOf("periodIntegral", "period_integral", "integral", "periodScore"),
            "本周积分" to listOf("weekIntegral", "week_integral", "weekScore"),
        )
        val result = mutableMapOf<String, String>()
        for ((label, keys) in fields) {
            for (key in keys) {
                val value = flat[key] ?: continue
                if (value.isEmpty()) continue
                result[label] = value
                break
            }
        }
        if (result.isEmpty()) {
            // 日志会显示在「运行详情」里，方便按真实结构补字段名
            debugLogger?.invoke("合伙人积分：未识别到已知字段，body=${json.toString().take(300)}")
        }
        return result
    }

    /** 摊平嵌套对象；同名键外层优先（和平板/桌面端同一规则）。 */
    private fun flattenJson(node: JSONObject, out: MutableMap<String, String>) {
        val keys = node.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            when (val value = node.opt(key)) {
                is JSONObject -> flattenJson(value, out)
                is JSONArray -> for (i in 0 until value.length()) {
                    (value.opt(i) as? JSONObject)?.let { flattenJson(it, out) }
                }
                null -> Unit
                else -> if (!out.containsKey(key)) out[key] = value.toString()
            }
        }
    }

    suspend fun reportListen(work: Work) {
        val payload = JSONObject().apply {
            put("workId", work.id)
            put("resourceId", work.resourceId)
            put("bizResourceId", "")
            put("interactType", "PLAY_END")
        }
        val resp = weapiPost(REPORT_LISTEN_URL, payload, referer = "https://mp.music.163.com/")
        if (resp.optInt("code", -1) != 200) {
            throw IOException("上报听歌记录失败：${resp.optString("message", "未知错误")}")
        }
    }

    // ------------------------------------------------------------------
    // 内部工具
    // ------------------------------------------------------------------

    private fun parseWork(w: JSONObject): Work = Work(
        id = w.opt("id") ?: "",
        name = w.optString("name", ""),
        authorName = w.optString("authorName", ""),
        resourceId = w.opt("resourceId") ?: "",
    )

    /** Set-Cookie 已由 CookieJar 写入 cookies；这里再兜底解析 body 里的 cookie 字段。 */
    private fun extractCookies(json: JSONObject) {
        parseCookieString(json.optString("cookie", ""))
    }

    private fun parseCookieString(cookieStr: String) {
        for (part in cookieStr.split(";")) {
            val idx = part.indexOf('=')
            if (idx > 0) {
                val name = part.substring(0, idx).trim()
                val value = part.substring(idx + 1).trim()
                if (name == "MUSIC_U" || name == "__csrf") cookies[name] = value
            }
        }
    }

    private fun generateWNMCID(): String {
        val prefix = (1..6).map { ('a'..'z').random() }.joinToString("")
        return "$prefix.${System.currentTimeMillis()}.01.0"
    }

    companion object {
        const val UA_DEFAULT =
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        const val UA_EAPI =
            "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36 Chrome/91.0.4472.164 NeteaseMusicDesktop/2.10.2.200154"

        const val LOGIN_PATH = "/eapi/w/login/cellphone"
        const val VERIFY_URL = "https://music.163.com/api/nuser/account/get"
        const val DAILY_TASK_URL =
            "https://interface.music.163.com/api/music/partner/daily/task/get"
        const val SCORE_URL =
            "https://interface.music.163.com/weapi/music/partner/work/evaluate"
        const val EXTRA_LIST_URL =
            "https://interface.music.163.com/api/music/partner/extra/wait/evaluate/work/list"
        const val REPORT_LISTEN_URL =
            "https://interface.music.163.com/weapi/partner/resource/interact/report"
        const val SIGN_IN_URL = "https://music.163.com/weapi/point/dailyTask"
        const val PARTNER_HOME_URL =
            "https://interface.music.163.com/weapi/music/partner/home/get"
    }
}
