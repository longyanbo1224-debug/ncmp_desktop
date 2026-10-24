package com.ncmp.mobile.data

import android.util.Base64
import java.math.BigInteger
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * 网易云音乐请求加密（从 ncmp 桌面版 core/signer.py + pyncm 1.8.1 逐行移植）。
 *
 *  - WeAPI：AES-128-CBC 双重加密 + RSA 生成 encSecKey（评分/签到/听歌上报/扫码登录用）
 *  - EAPI ：AES-128-ECB（密码登录 /eapi/w/login/cellphone 用，响应也需解密）
 */
object NeteaseCrypto {
    // WeAPI 常量（与 signer.py / pyncm.utils.crypto 完全一致）
    private const val WEAPI_AES_KEY = "0CoJUm6Qyw8W8jud"
    private const val WEAPI_AES_IV = "0102030405060708"
    private const val RSA_EXPONENT = "010001"
    private const val RSA_MODULUS =
        "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7"

    // EAPI 常量
    private const val EAPI_AES_KEY = "e82ckenh8dichen8"

    private val rsaN = BigInteger(RSA_MODULUS, 16)
    private val rsaE = BigInteger(RSA_EXPONENT, 16)

    private const val RANDOM_CHARS =
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

    fun randomString(length: Int): String =
        (1..length).map { RANDOM_CHARS.random() }.joinToString("")

    fun md5Hex(input: String): String =
        MessageDigest.getInstance("MD5")
            .digest(input.toByteArray(Charsets.UTF_8))
            .toHex()

    fun ByteArray.toHex(): String =
        joinToString("") { "%02x".format(it.toInt() and 0xFF) }

    private fun aesEncryptCbc(data: ByteArray, key: String, iv: String): ByteArray {
        val cipher = Cipher.getInstance("AES/CBC/PKCS5Padding")
        cipher.init(
            Cipher.ENCRYPT_MODE,
            SecretKeySpec(key.toByteArray(Charsets.UTF_8), "AES"),
            IvParameterSpec(iv.toByteArray(Charsets.UTF_8)),
        )
        return cipher.doFinal(data)
    }

    private fun aesEcb(data: ByteArray, key: String, mode: Int): ByteArray {
        val cipher = Cipher.getInstance("AES/ECB/PKCS5Padding")
        cipher.init(mode, SecretKeySpec(key.toByteArray(Charsets.UTF_8), "AES"))
        return cipher.doFinal(data)
    }

    /** RSA：反转随机串 -> 转大整数 -> m^e mod n -> 256 位小写 hex。 */
    private fun rsaEncrypt(randomStr: String): String {
        val reversed = randomStr.reversed()
        val m = BigInteger(1, reversed.toByteArray(Charsets.UTF_8))
        return m.modPow(rsaE, rsaN).toString(16).padStart(256, '0')
    }

    /** WeAPI 加密。返回 {params, encSecKey}。 */
    fun weapiEncrypt(plainJson: String): Map<String, String> {
        val key2 = randomString(16)
        // 第一次：AES-CBC 加密 JSON，结果转成 base64 字符串
        val firstBytes = aesEncryptCbc(plainJson.toByteArray(Charsets.UTF_8), WEAPI_AES_KEY, WEAPI_AES_IV)
        val firstB64 = Base64.encodeToString(firstBytes, Base64.NO_WRAP)
        // 第二次：用随机 key2 加密上面的 base64 字符串（注意是字符串，不是原始密文字节）
        val secondBytes = aesEncryptCbc(firstB64.toByteArray(Charsets.UTF_8), key2, WEAPI_AES_IV)
        val params = Base64.encodeToString(secondBytes, Base64.NO_WRAP)
        return mapOf("params" to params, "encSecKey" to rsaEncrypt(key2))
    }

    /** EAPI 加密。返回 params（hex 编码）。 */
    fun eapiEncrypt(path: String, plainJson: String): String {
        val url = path.replace("/eapi/", "/api/")
        val digest = md5Hex("nobody${url}use${plainJson}md5forencrypt")
        val data = "${url}-36cd479b6b5-${plainJson}-36cd479b6b5-${digest}"
        return aesEcb(data.toByteArray(Charsets.UTF_8), EAPI_AES_KEY, Cipher.ENCRYPT_MODE).toHex()
    }

    /** EAPI 响应解密。 */
    fun eapiDecrypt(data: ByteArray): ByteArray =
        aesEcb(data, EAPI_AES_KEY, Cipher.DECRYPT_MODE)
}
