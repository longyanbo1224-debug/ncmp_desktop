# ncmp mobile（Android）

Android 客户端。**完整的功能说明、使用教程、常见问题请见仓库根目录的 [README](../README.md)**；这里只保留 Android 开发相关内容。

## 环境

- JDK 17+
- Android SDK：`platforms;android-34`、`build-tools;34.0.0`、`platform-tools`
- SDK 位置通过 `ANDROID_HOME` 环境变量或 `local.properties`（`sdk.dir=...`）指定

## 构建

在**仓库根目录**执行一键打包（产物：`dist/android/ncmp-mobile.apk`）：

```bash
build_android.bat
```

或在本目录用 Gradle：

```bash
./gradlew :app:assembleDebug
# 产物：app/build/outputs/apk/debug/app-debug.apk
```

> 首次构建会通过 Gradle wrapper 下载 Gradle 8.7（腾讯镜像）；依赖走 `settings.gradle.kts` 中的阿里云 Maven 镜像。

## 签名

当前为 **debug 签名**，可直接安装测试，但不能上架应用商店。正式发布需要在 `app/build.gradle.kts` 配置 `signingConfigs` 生成 release 包。

## 目录结构

```
app/src/main/java/com/ncmp/mobile/
├── MainActivity.kt        入口（通知权限申请）
├── TaskService.kt         前台服务：后台执行任务（WakeLock + 常驻通知）
├── AlarmReceiver.kt       定时闹钟触发 / 开机重排
├── data/
│   ├── NeteaseCrypto.kt   WeAPI / EAPI / AES / RSA 加密
│   ├── NeteaseApi.kt      HTTP 客户端（登录 + 任务接口）
│   ├── TaskRunner.kt      任务编排 + 失败分类
│   ├── TaskBus.kt         任务状态中转（服务 → 界面）
│   ├── TaskHistory.kt     打卡记录存储
│   ├── AlarmScheduler.kt  每日定时（AlarmManager）
│   └── SessionStore.kt    Cookie / 配置加密存储
└── ui/                    Jetpack Compose 界面
```

## 说明

- 核心逻辑（加密、接口、评分策略）与桌面端 `core/` 逐行对应
- Cookie 存 Android Keystore 加密的 SharedPreferences
- 本项目为**非官方**第三方程序，仅供个人学习、研究和技术交流，使用风险自负
