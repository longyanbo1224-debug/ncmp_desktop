<p align="center">
  <img src="resources/app-icon.png" width="140" alt="ncmp logo">
</p>

<h1 align="center">ncmp</h1>

<p align="center">
  网易云音乐「音乐合伙人」任务自动化<br>
  <strong>桌面端（Windows）+ 手机端（Android）</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Android-C20C0C" alt="Platform">
  <img src="https://img.shields.io/badge/License-Non--commercial-9E9E9E" alt="License">
</p>

> ⚠️ **免责声明**：本项目为**非官方**第三方程序，仅供个人学习、研究和技术交流使用，严禁商业化或规模化刷量。使用即视为自行承担账号封禁等一切后果。详见文末 [免责声明](#免责声明)。

---

## 目录

- [项目简介](#项目简介)
- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [云端执行（可选）](#云端执行可选)
- [项目架构](#项目架构)
- [视觉设计](#视觉设计)
- [从源码构建](#从源码构建)
- [常见问题](#常见问题)
- [免责声明](#免责声明)
- [致谢与许可](#致谢与许可)

---

## 项目简介

ncmp 把网易云音乐「音乐合伙人」的每日评分任务自动化，提供了**两个客户端**：

| 客户端 | 平台 | 形态 |
|---|---|---|
| ncmp desktop | Windows | PySide6 桌面程序（exe） |
| ncmp mobile | Android | Kotlin + Jetpack Compose（APK） |

它解决的痛点是原 GitHub Actions 脚本形态对非技术用户不友好：Cookie 手动抓取、任务过程看不见、Cookie 过期只能事后发现、参数要敲 Secrets 网页表单。

**核心职责**：一眼回答「今天跑了吗？成功了吗？」，并让「还没配置 → 跑完了」这条路一眼看得懂。

项目仓库：<https://github.com/longyanbo1224-debug/ncmp_desktop>（fork 自上游 [ACAne0320/ncmp](https://github.com/ACAne0320/ncmp)）

---

## 功能特性

### 任务执行

- **可视化登录**：桌面端扫码 / 密码双通道；手机端用内嵌 WebView 直连网易**官方登录页**（扫码 / 手机号 / 验证码等官方渠道），另支持直接粘贴 Cookie 绕开风控
- **Cookie 管理**：桌面端存系统钥匙串（Windows Credential Manager）；手机端存 Android Keystore 加密的 SharedPreferences；到期自动提醒重新获取
- **任务执行可视化**：分段进度条 + 步骤视图 + 流式日志，能看到每首歌的评分进度。桌面端与手机端使用同一套全局进度：验证 / 拉取 / 基础评分 / 额外评分按阶段分配，基础 5 首跑完不会先顶到 100%，额外任务也不会从 0 重新开始
- **任务取消**：本地取消即时停任务；云端取消会请求 GitHub 停止远端 run。界面区分「完成 / 用户手动取消 / 失败」三种状态
- **额外任务补跑**：单首失败会被跳过，整轮结束后自动重新核对服务端任务列表并补跑一轮，不用手动再点一次执行
- **失败原因分类**：直接告诉你是哪一类问题——**Cookie 失效 / 风控拦截 / 网络异常 / 接口返回错误 / 未知**，并给出对应的下一步。桌面端遇到网络类失败会等 60 秒整轮重试一次；单首遇到「频繁」最多试 3 次后放弃；风控和 Cookie 类不做整轮重试
- **额度用完**：按正常结束处理，不判失败；基础阶段额度用完会停止基础评分并继续尝试额外任务

### 自动化（桌面端）

- **定时自动**：到点自动执行（本地常驻 / 云端 / 两者都行）
- **错过补跑**：定时设了 09:00 但电脑 09:30 才开机时，启动时检查「今天该跑但还没跑」并自动补一次。限制：只补当天、每天最多补一次、有截止时间（默认 23:00）、只对本地模式生效
- **本地随机延迟**：0–30 分钟随机窗口，避免每天都在同一秒发起请求
- **云端执行**：触发 GitHub Actions 跑任务，电脑关机也能跑

### 记录与通知（桌面端）

- **连续打卡图**：首页一张 53 周格子图，绿=成功 / 红=失败 / 灰=没跑，悬停看具体日期
- **打卡记录表**：最近几次明细，失败和取消会展开原因
- **邮件通知**：任务完成 / Cookie 失效 / 定时任务结果 / 云端执行完成均可发邮件，3 个开关独立（默认全开），邮件带状态色条、关键信息表和「下一步」提示
- **应用内通知**：右下角弹出，5 秒自动消失，不抢焦点
- **持久化日志**：按天滚动、保留 7 天

### 手机端（Android）

- **官方网页登录**：内嵌 WebView 直连网易官方登录页（手机号 / 验证码 / 扫码），另支持粘贴 Cookie 绕开风控；页面可双指缩放
- **后台执行**：任务在**前台服务**中运行，切后台 / 锁屏不中断（常驻通知 + WakeLock/WiFi 锁）
- **定时执行**：每天 `HH:mm` 自动执行（AlarmManager，保存时需授予「闹钟和提醒」权限；重启/重开后自动重排；受系统省电策略影响，建议做后台保活）
- **打卡记录**：底部「记录」页是一年格子图（绿=成功 / 红=失败 / 灰=没跑），下面是按天合并的执行情况——同一天跑几次都收在同一条，点开看每次的时间、状态和失败原因
- **进度与容错**：与桌面端同一套阶段进度条；额外任务失败会自动补跑一轮，额度用完按正常结束处理
- **手动控制**：评分策略、等待时间、额外任务开关均可调

### 其他

- **系统托盘** / **关闭行为可配置** / **自动更新检查（只提示不自动替换）** / **滚轮保护** / **单实例**（再次启动会把已运行的窗口——包括最小化到托盘的——直接拉到前台，不再弹「已在运行」）
- **界面**：浅灰底 + 白色面板 + 网易云品牌红点缀，随包思源黑体/宋体子集

---

## 快速开始

### 桌面端（exe）

1. 到 [Releases](https://github.com/longyanbo1224-debug/ncmp_desktop/releases) 下载 `ncmp.desktop.zip`
2. 解压，双击 `ncmp desktop.exe`（首次启动若提示「未识别发布者」→「更多信息」→「仍要运行」）

三步用起来：

1. **登录**：切到「账号」页，扫码或密码登录获取 Cookie
2. **配置**：「设置」页默认值已预填，按需修改后保存
3. **执行**：「任务」页点「立即执行」，实时看进度和日志

### 手机端（APK，v1.1.1）

1. 安装 `ncmp-mobile.apk`（见 [Releases](https://github.com/longyanbo1224-debug/ncmp_desktop/releases)，或从源码构建）
2. 打开 App →「网页登录」→ 在官方登录页里登录（手机号 / 验证码 / 扫码）→ 点「我已登录，获取 Cookie」
3. 进入主界面 → 点「开始评分」
4. 底部「记录」页查看年度打卡图和每天的执行情况；「任务参数」里可开启**定时执行**

> 手机端接口与桌面端 `core/` 完全一致。任务在**前台服务**中执行，支持切后台 / 锁屏继续跑（需在系统里给 App 后台保活白名单）。

---

## 配置说明

设置页分 6 组：

| 组 | 说明 |
|---|---|
| 常规 | 关闭按钮行为（每次询问 / 最小化到托盘 / 直接退出）、打开日志文件夹 |
| 网易云账号 | 手机号、密码 / MD5（可一键转成 MD5） |
| 任务参数 | 评分策略（1-2 / 2-3 / 3-4 / 固定4分）、等待时间、是否完成所有额外任务 |
| 邮件通知 | 接收邮箱、SMTP 授权码、服务器端口（默认 `smtp.qq.com`）、3 个开关 |
| GitHub Actions | 云端执行配置（见下节，可选） |
| 定时执行 | 启用开关、触发时间、模式（本地 / 云端 / 两者）、本地随机延迟、错过补跑开关与截止时间 |

**评分策略**：根据歌名/歌手名里是否含英文决定打分（默认「3-4 分」策略——含英文打 4 分，否则打 3 分）。

---

## 云端执行（可选）

电脑关机时任务也能自动跑——靠 GitHub Actions 云端定时。配置 5 步：

1. fork ncmp 仓库到自己 GitHub 账号
2. 设置页点「同步完整 workflow」，把 `resources/workflow_example.yml` 一键写入 fork 仓库的 `.github/workflows/refresh_cookie.yml`，并把云端 cron 时间一并写入
3. 生成 GitHub Personal Access Token（勾选 repo + workflow）
4. 「设置 → GitHub Actions」填 4 个字段（悬停有获取说明）→「保存」→「测试连接」
5. 点「同步 Cookie、邮件和任务参数到 GitHub Secrets」把本地 Cookie、邮件配置和额外任务开关写入仓库

两个同步按钮的区别：改了 Cookie / 邮箱授权码 → 只点「同步 Cookie、邮件和任务参数」；改了 cron / 定时 / 成功邮件开关 → 点「同步完整 workflow」。

> 错过补跑只对本地模式生效；云端由 GitHub Actions 自己按 cron 跑。

---

## 项目架构

### 两层结构

代码分成干净的两层，**核心逻辑与界面完全解耦**：

```
core/   ← 任务引擎（纯 Python，不依赖任何 UI）
  ├── bot.py          任务编排：验证用户 → 拉取任务 → 评分基础 → 额外评分
  ├── signer.py       WeAPI 加密（AES-CBC + RSA）
  ├── tasks/          每日评分 / 额外任务 / 听歌上报
  └── utils/          配置 / 日志 / 错误分类 / 通知

app/    ← 桌面壳（PySide6）
  ├── ui/             五个页面 + 自绘控件（电平表 / 通知气泡 / 打卡图）
  ├── login/          扫码 / 密码登录
  ├── workers/        任务 / 登录 / 云端 / Cookie 校验的工作线程
  └── cloud/          GitHub Actions 触发与同步
```

手机端把 `core/` 用 Kotlin 重新实现了一遍（`android/app/src/main/java/com/ncmp/mobile/data/`），加密、接口、评分策略逐行对应。

### 加密与接口

| 用途 | 加密 | 接口 |
|---|---|---|
| 密码登录 | EAPI（AES-128-ECB） | `/eapi/w/login/cellphone` |
| 扫码登录 | WeAPI | `/weapi/login/qrcode/unikey` + `/client/login` |
| 验证用户 | 无 | `GET /api/nuser/account/get` |
| 拉取每日任务 | 无 | `GET /api/music/partner/daily/task/get` |
| 评分 | WeAPI | `/weapi/music/partner/work/evaluate` |
| 额外任务列表 | 无 | `GET /api/music/partner/extra/wait/evaluate/work/list` |
| 听歌上报 | WeAPI | `/weapi/partner/resource/interact/report` |

WeAPI = AES-128-CBC（key `0CoJUm6Qyw8W8jud`，IV `0102030405060708`）双重加密 + RSA `encSecKey`。

### 关键设计模式

- **回调解耦**：任务引擎通过 `on_step` / `on_progress` 回调向 UI 报告状态，核心层不依赖界面
- **取消透传**：`CancelledError` 一路透传，不被通用 `Exception` 吞掉，UI 才能区分「取消」和「失败」
- **失败分类**：按异常类型和错误文案分五类（网络优先判，避免误报成 Cookie 失效）

---

## 视觉设计

设计变量全部集中在 `app/ui/theme.py`（手机端 `ui/theme/Theme.kt`），改一个文件全程序生效。

**设计主张**：品牌红表示「可交互」，状态色表示「现在怎么样」，两者互不干扰。进行中用琥珀（不是红），把「正在跑」和「失败」区分开。

**颜色**：

| 角色 | 色值 | 用途 |
|---|---|---|
| 底色 `GROUND` | `#F5F5F5` | 页面底色 |
| 面板 `PANEL` | `#FFFFFF` | 输入框、日志、卡片 |
| 品牌红 `BRAND` | `#C20C0C` | 主按钮、选中态、焦点框、链接 |
| 进行中 | `#E8A33D`（填充） | 状态 |
| 成功 | `#2C7549` | 状态 |
| 失败 | `#B3352B` | 状态 |

> 品牌红选 `#C20C0C` 而不是网易云的亮红 `#EC4141`，是因为亮红当文字对比度只有 3.57:1，不达标；`#C20C0C` 两种用法都够。

**字体**：展示用宋体（`NCMPSerifSC`），界面用黑体（`NCMPSansSC`），数据用等宽。字体随包分发，任何机器上一致。

**形状与间距**：控件圆角 4px、面板圆角 6px；间距梯度 4/8/12/16/24/32/48；全界面不用投影，分层靠细线和明度差。

**高光元素**：任务页进度条是**分段式电平表**（`app/ui/widgets/meter.py` 自绘），40 格按状态色点亮——跑的时候琥珀、成功变绿、失败变红。

**应用图标**：设计源是 `resources/app-icon.png`（256×256）。改完运行 `python scripts/gen_icon.py` 生成 `resources/app.ico`；exe 文件图标、窗口、系统托盘和应用内通知都读这一份，保证四处一致。

---

## 从源码构建

### 桌面端

依赖：Python 3.10+、Git

```bash
build.bat
```

产物：`dist/ncmp desktop/`（分发时整个文件夹一起 zip，不要只发 exe）

> 首次打包会自动安装 Python 依赖（PyPI 包走清华镜像；pyncm 不在 PyPI，仅在首次未安装时从 GitHub 拉取，之后自动跳过）。国内网络建议先配 pip 镜像：
>
> ```bash
> pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
> ```

只跑源码（不打包）：

```bash
pip install -r requirements.txt
python app/main.py
```

### 手机端（Android）

依赖：**JDK 17**（17 或 21 均可）、Android SDK（platforms;android-34 / build-tools;34.0.0）

```bash
build_android.bat
```

产物：`dist/android/ncmp-mobile.apk`

> 首次打包会通过 Gradle wrapper 下载 Gradle 8.7（走腾讯镜像）。需已配置 Android SDK（`android/local.properties` 或 `ANDROID_HOME`）。
>
> 设了 `JAVA_HOME` 时脚本会自动把它的 `bin` 加到 PATH 前面；没设则要求 `java` 已在 PATH 上。
>
> 不要用 Android Studio 2026 自带的 JBR 跑构建：它是 Java 25，Gradle 8.7 / AGP 8.5.2 不支持，会报 `What went wrong: 25.0.x`。在 Studio 里把 *Settings → Build Tools → Gradle → Gradle JDK* 指向 JDK 17。

或用 Android Studio 打开 `android/` 目录点 Run；或命令行：

```bash
cd android
# 先建 local.properties 指向 SDK，或设置 ANDROID_HOME
./gradlew :app:assembleDebug
# APK 输出在 android/app/build/outputs/apk/debug/app-debug.apk
```

`android/settings.gradle.kts` 已内置阿里云 Maven 镜像加速依赖下载。

> Android 工程的目录结构、签名配置等开发细节见 [android/README.md](android/README.md)。
>
> 两个打包脚本的产物互不覆盖：桌面端只替换 `dist/ncmp desktop/`，Android 只写入 `dist/android/ncmp-mobile.apk`，先打哪个都行。

---

## 常见问题

### 扫码登录失败？

二维码 5 分钟过期，点「重新生成」。或改密码登录；触发风控时程序会提示改回扫码。

### Cookie 过期了？

约 2 周过期。程序后台会定时验证，失效时弹通知 + 跳到登录页。首页状态变红「Cookie 失效了」也是这个信号。

### 手机端登录被风控（提示「网络环境存在安全风险」）？

手机端请用「网页登录」走官方登录页，不要用客户端直连接口。若网页登录也异常，检查手机是否开了代理 / VPN。

### 手机端定时任务到点没执行？

手机定时依赖系统闹钟 + 前台服务，需要满足以下条件：

1. 保存定时设置时弹出「允许设置闹钟和提醒」要**允许**（否则闹钟不精确，后台启动会被系统拦截，只弹通知不跑）
2. 设置 → 应用 → ncmp：**自启动**开启、**省电策略**设为「无限制」、**通知**允许
3. 把 App 从后台任务列表**锁定**，防止一键清理

设置完可把时间设为 2~3 分钟后、切后台自测：到点通知栏应出现常驻通知，跑完「记录」页会出现或更新当天那一条。

### 退出登录会丢配置吗？

不会。退出登录只清除登录态（Cookie / 昵称），评分策略、等待时间、定时设置都会保留。

### 今天任务没跑成怎么办？

- 电脑开机晚了 → 开启「错过补跑」自动补一次
- 补跑也没跑 → 「任务」页点「立即执行」手动补
- 想知道哪次失败 → 首页「最近几次」展开失败原因，日志里有完整过程
- 手机端 → 「记录」页点开当天条目，看当天的每一次执行结果

### 额外任务没跑满 15 首？

单首评分失败（资源异常、限流等）会被跳过，整轮跑完后程序会自动重新拉取任务列表并补跑一轮。补跑后仍有剩余时，日志会写明还剩几个；常见原因是网易额度用完或风控限流。

额度用完按正常结束处理，不算失败，不会发失败通知；限流时建议把「等待时间」调大，或换个时间再跑。

### 任务失败但不知道原因？

「任务」页会直接给出分类（Cookie 失效 / 风控拦截 / 网络异常 / 接口返回错误 / 未知）和「下一步」提示。

### 重新打包 / 升级会丢配置吗？

不会。配置存用户目录或系统凭据管理器，不在打包目录里：

- 行为配置 / 任务历史 / 日志：`%LOCALAPPDATA%\ncmp desktop\`
- 非敏感字段：`~/.ncmp_desktop\setting.json`
- 凭据（Cookie / 密码 / gh_token / 邮箱授权码）：Windows 凭据管理器（keyring，service `ncmp desktop`）

---

## 版本记录

桌面端与手机端同步发布 **v1.1.1**，安装包见 [Releases](https://github.com/longyanbo1224-debug/ncmp_desktop/releases)，详细说明见 [v1.1.1 更新记录](release-notes/v1.1.1.md)。

### 手机端（Android）

安装包见 [Releases](https://github.com/longyanbo1224-debug/ncmp_desktop/releases)；每个版本的详细说明见对应文件。

| 版本 | 日期 | 主要更新 |
|---|---|---|
| [v1.1.1](release-notes/v1.1.1.md) | 2026-10-26 | 年度打卡图 + 按天执行情况、与桌面端一致的阶段进度条、额外任务补跑、失败策略统一、桌面图标统一 |
| [v1.1.0](release-notes/android-v1.1.0.md) | 2026-10-25 | 定时执行（含精确闹钟授权、重启/重开自动重排）、打卡记录、前台服务后台执行、界面按桌面端设计语言重构、网页登录双指缩放、退出登录保留配置 |
| [v1.0.0](release-notes/android-v1.0.0.md) | 2026-10-24 | 首个版本：官方网页登录 / Cookie 登录、手动执行任务 |

---

## 免责声明

1. 本项目是**非官方**的第三方程序，与网易云音乐（网易公司）及其「音乐合伙人」活动**无任何关联**，未获得任何官方授权。
2. 本项目仅供**个人学习、研究和技术交流**使用，严禁用于商业用途、代挂服务或规模化批量刷取任务奖励。
3. 使用本项目可能违反网易云音乐《用户协议》及相关活动规则，由此导致的**账号封禁、奖励作废、收益损失等一切后果，由使用者本人自行承担**，作者不承担任何直接或间接责任。
4. 项目中的「网易云音乐」等名称仅用于标识服务来源，相关商标权利归其权利人所有。
5. 如权利人认为本项目侵犯其合法权益，请通过 GitHub Issue 联系作者，作者将及时下架处理。

---

## 项目热度

[![Star History Chart](https://api.star-history.com/svg?repos=longyanbo1224-debug/ncmp_desktop&type=Date)](https://star-history.com/#longyanbo1224-debug/ncmp_desktop&Date)

---

## 致谢与许可

- 基于 [ACAne0320/ncmp](https://github.com/ACAne0320/ncmp)（MIT）
- 使用 [pyncm](https://github.com/sakarie9/pyncm)、[qtawesome](https://github.com/spyder-ide/qtawesome)、PySide6、OkHttp、Jetpack Compose
- 随包字体是 Google [Noto Sans SC / Noto Serif SC](https://fonts.google.com/noto) 的改名子集化派生版，以 SIL Open Font License 1.1 分发（见 `app/ui/fonts/OFL.txt`）
- YanboLong Non-Commercial License（基于 MIT 修改的非商业许可，详见 [LICENSE](LICENSE)）
