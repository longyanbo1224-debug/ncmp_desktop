package com.ncmp.mobile.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys

/**
 * 登录态与配置的本地存储。Cookie（MUSIC_U / __csrf）属敏感信息，
 * 优先写入 EncryptedSharedPreferences；个别设备 Keystore 不可用时降级到普通存储。
 */
class SessionStore(context: Context) {

    private val prefs: SharedPreferences = try {
        val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
        EncryptedSharedPreferences.create(
            "ncmp_session",
            masterKeyAlias,
            context,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    } catch (_: Exception) {
        context.getSharedPreferences("ncmp_session_plain", Context.MODE_PRIVATE)
    }

    init {
        // 旧版本批注默认开启：只要保存过一次设置，就会把 true 落盘。
        // 新版本要求默认关闭、必须手动打开并保存——升级后第一次启动强制关一次，
        // 之后完全尊重用户的选择（用户再次打开并保存不会被覆盖）。
        if (!prefs.getBoolean(KEY_NOTE_DEFAULT_OFF_MIGRATED, false)) {
            prefs.edit()
                .putBoolean(KEY_NOTE_ENABLED, false)
                .putBoolean(KEY_NOTE_DEFAULT_OFF_MIGRATED, true)
                .apply()
        }
    }

    var musicU: String?
        get() = prefs.getString(KEY_MUSIC_U, null)
        set(value) = prefs.edit().putString(KEY_MUSIC_U, value).apply()

    var csrf: String?
        get() = prefs.getString(KEY_CSRF, null)
        set(value) = prefs.edit().putString(KEY_CSRF, value).apply()

    var nickname: String?
        get() = prefs.getString(KEY_NICKNAME, null)
        set(value) = prefs.edit().putString(KEY_NICKNAME, value).apply()

    var scoreStrategy: Int
        get() = prefs.getInt(KEY_SCORE, 3)
        set(value) = prefs.edit().putInt(KEY_SCORE, value).apply()

    var waitMin: Float
        get() = prefs.getFloat(KEY_WAIT_MIN, 15f)
        set(value) = prefs.edit().putFloat(KEY_WAIT_MIN, value).apply()

    var waitMax: Float
        get() = prefs.getFloat(KEY_WAIT_MAX, 20f)
        set(value) = prefs.edit().putFloat(KEY_WAIT_MAX, value).apply()

    var fullExtra: Boolean
        get() = prefs.getBoolean(KEY_FULL_EXTRA, true)
        set(value) = prefs.edit().putBoolean(KEY_FULL_EXTRA, value).apply()

    // 批注（乐评文案）：与桌面端同一套开关。默认关闭，需用户在设置里显式开启并保存
    var noteEnabled: Boolean
        get() = prefs.getBoolean(KEY_NOTE_ENABLED, false)
        set(value) = prefs.edit().putBoolean(KEY_NOTE_ENABLED, value).apply()

    /** 语气：restrained | warm | brief。手机端不接外部 LLM，只有本地模板。 */
    var noteVoice: String
        get() = prefs.getString(KEY_NOTE_VOICE, Notes.DEFAULT_VOICE) ?: Notes.DEFAULT_VOICE
        set(value) = prefs.edit().putString(KEY_NOTE_VOICE, value).apply()

    /** 批注来源：template（默认）/ llm。手机端没有 LLM，传 llm 也按 template 处理。 */
    var noteSource: String
        get() = prefs.getString(KEY_NOTE_SOURCE, "template") ?: "template"
        set(value) = prefs.edit().putString(KEY_NOTE_SOURCE, value).apply()

    /** 批注长度档：brief / standard / detailed（与桌面端一致）。 */
    var noteLength: String
        get() = prefs.getString(KEY_NOTE_LENGTH, Notes.DEFAULT_LENGTH) ?: Notes.DEFAULT_LENGTH
        set(value) = prefs.edit().putString(KEY_NOTE_LENGTH, value).apply()

    var noteMaxChars: Int
        get() = prefs.getInt(KEY_NOTE_MAX_CHARS, NoteGenerator.DEFAULT_MAX_CHARS)
        set(value) = prefs.edit().putInt(KEY_NOTE_MAX_CHARS, value).apply()

    /** 最近一次查到的合伙人积分/等级（JSON），记录页离线也能显示。 */
    var partnerPoints: String
        get() = prefs.getString(KEY_PARTNER_POINTS, "") ?: ""
        set(value) = prefs.edit().putString(KEY_PARTNER_POINTS, value).apply()

    /**
     * 今日额外额度是否已确认用完（day + taskId + account 全部匹配才命中）。
     *
     * 服务端返回 405「今日没有更多」后写入；同一天同一任务再执行时直接跳过
     * 额外阶段，不再等待 15–20 秒、不再发评分请求。换天 / 换任务 / 换账号自动失效。
     */
    fun isQuotaExhausted(day: String, taskId: String, account: String): Boolean {
        if (taskId.isBlank()) return false
        return prefs.getString(KEY_QUOTA_DAY, "") == day &&
            prefs.getString(KEY_QUOTA_TASK, "") == taskId &&
            prefs.getString(KEY_QUOTA_ACCOUNT, "") == account
    }

    fun markQuotaExhausted(day: String, taskId: String, account: String) {
        if (taskId.isBlank()) return
        prefs.edit()
            .putString(KEY_QUOTA_DAY, day)
            .putString(KEY_QUOTA_TASK, taskId)
            .putString(KEY_QUOTA_ACCOUNT, account)
            .apply()
    }

    // 定时执行
    var scheduleEnabled: Boolean
        get() = prefs.getBoolean(KEY_SCHEDULE_ENABLED, false)
        set(value) = prefs.edit().putBoolean(KEY_SCHEDULE_ENABLED, value).apply()

    var scheduleHour: Int
        get() = prefs.getInt(KEY_SCHEDULE_HOUR, 9)
        set(value) = prefs.edit().putInt(KEY_SCHEDULE_HOUR, value).apply()

    var scheduleMinute: Int
        get() = prefs.getInt(KEY_SCHEDULE_MINUTE, 0)
        set(value) = prefs.edit().putInt(KEY_SCHEDULE_MINUTE, value).apply()

    fun clear() {
        prefs.edit().clear().apply()
    }

    /** 仅清除登录态，保留任务配置与定时设置。 */
    fun clearAuth() {
        prefs.edit()
            .remove(KEY_MUSIC_U)
            .remove(KEY_CSRF)
            .remove(KEY_NICKNAME)
            .apply()
    }

    companion object {
        private const val KEY_MUSIC_U = "music_u"
        private const val KEY_CSRF = "csrf"
        private const val KEY_NICKNAME = "nickname"
        private const val KEY_SCORE = "score"
        private const val KEY_WAIT_MIN = "wait_min"
        private const val KEY_WAIT_MAX = "wait_max"
        private const val KEY_FULL_EXTRA = "full_extra"
        private const val KEY_NOTE_ENABLED = "note_enabled"
        private const val KEY_NOTE_DEFAULT_OFF_MIGRATED = "note_default_off_migrated"
        private const val KEY_NOTE_SOURCE = "note_source"
        private const val KEY_NOTE_VOICE = "note_voice"
        private const val KEY_NOTE_MAX_CHARS = "note_max_chars"
        private const val KEY_NOTE_LENGTH = "note_length"
        private const val KEY_PARTNER_POINTS = "partner_points"
        private const val KEY_QUOTA_DAY = "quota_exhausted_day"
        private const val KEY_QUOTA_TASK = "quota_exhausted_task"
        private const val KEY_QUOTA_ACCOUNT = "quota_exhausted_account"
        private const val KEY_SCHEDULE_ENABLED = "schedule_enabled"
        private const val KEY_SCHEDULE_HOUR = "schedule_hour"
        private const val KEY_SCHEDULE_MINUTE = "schedule_minute"
    }
}
