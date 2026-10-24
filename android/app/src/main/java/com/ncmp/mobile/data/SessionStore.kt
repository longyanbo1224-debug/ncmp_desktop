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

    companion object {
        private const val KEY_MUSIC_U = "music_u"
        private const val KEY_CSRF = "csrf"
        private const val KEY_NICKNAME = "nickname"
        private const val KEY_SCORE = "score"
        private const val KEY_WAIT_MIN = "wait_min"
        private const val KEY_WAIT_MAX = "wait_max"
        private const val KEY_FULL_EXTRA = "full_extra"
        private const val KEY_SCHEDULE_ENABLED = "schedule_enabled"
        private const val KEY_SCHEDULE_HOUR = "schedule_hour"
        private const val KEY_SCHEDULE_MINUTE = "schedule_minute"
    }
}
