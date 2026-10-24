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
        // weapi 会话配置 cookie（与 pyncm 的 weapi_config 一致；eapi 的 header 字段已自带设备信息）
        cookies["WEVNSM"] = "1.0.0"
        cookies["sDeviceId"] = sDeviceId
        cookies["WNMCID"] = wnMCID
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
                parseJson(resp.body?.string())
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
            items.add(WorkItem(parseWork(work), item.optBoolean("completed", false)))
        }
        return DailyTasks(id, count, completedCount, items)
    }

    /** 返回 (未完成列表, 已完成数量)。 */
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
            items.add(WorkItem(parseWork(work), item.optBoolean("completed", false)))
        }
        val completedCount = items.count { it.completed }
        return items.filter { !it.completed } to completedCount
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
    }
}
