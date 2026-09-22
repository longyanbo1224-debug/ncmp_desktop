# ncmp desktop 开发者文档（架构/技术/打包/API 参考，面向开发者与 AI 助手）

基于 [ACAne0320/ncmp](https://github.com/ACAne0320/ncmp) 改造的 PySide6 桌面程序，把原本跑在 GitHub Actions 上的"网易云音乐音乐合伙人"任务脚本复用为本地 GUI 应用，支持**本地 / 云端双模式**执行任务、扫码与密码双通道登录、Cookie keyring 加密存储、实时任务可视化、本地定时与云端 Actions 触发、系统托盘常驻。

项目仓库：<https://github.com/longyanbo1224/ncmp>（作者：Galvin），致谢上游 [ACAne0320/ncmp](https://github.com/ACAne0320/ncmp)。

---

## 一、项目简介

`ncmp` 原项目是一个跑在 GitHub Actions 上的无头脚本：Cookie 要手动 F12 抓取或靠 PAT 回写，任务过程只能在 Actions 网页看到，Cookie 约 2 周过期只能事后靠邮件发现，十余项配置都得敲进 Secrets 网页表单——对非技术用户不友好，且无头环境无法处理扫码登录。

桌面版把 ncmp 的核心逻辑（weapi 加密评分、pyncm 登录、Cookie 验证、邮件通知）复用为内嵌 `core/` 库，外加：

- 可视化获取 Cookie（扫码 + 手机号密码双通道，密码登录风控时自动提示改扫码）
- Cookie 本地 keyring 加密存储（替代明文 `setting.json` 与 GitHub Secrets 回写）
- 到期提醒重新获取（后台定时验证 + 系统托盘原生通知 + 自动跳转登录页）
- 实时任务执行可视化（流式日志 + 结构化步骤视图，对标 GitHub Actions live log 体验）
- 参数表单化配置（13+ 项做成控件，4+1 分组）
- 本地定时（QTimer 到点自动触发）+ 云端 Actions 触发双执行模式（电脑关机也能跑）
- Cookie 一键同步到 GitHub Secrets（PyNaCl 加密）+ 云端 cron 远程修改 + 一键关闭 GitHub 原生定时
- 品牌图标统一（窗口 / 任务栏 / 托盘 / exe，AppUserModelID）

> 与原 ncmp 的关系：`core/` 层基于 ncmp 源码改造（4 个文件加回调/取消点/keyring，其余直接复用），`app/` 层为全新桌面应用层。原 `core/utils/github.py`（GitHub Secrets 回写）已废弃，改由 `app/cloud/actions_trigger.py` 触发 Actions 代替回写。

---

## 二、核心功能

- **扫码登录**：调用 pyncm `LoginQrcodeUnikey` / `GetLoginQRCodeUrl` 生成二维码（qrcode + Pillow 渲染 PNG），`LoginQrcodeCheck` 每 2 秒轮询，状态码 800（过期）/ 801（等待扫描）/ 802（已扫描待确认）/ 803（登录成功）全覆盖，登录成功自动写 keyring。
- **密码登录**：包装 pyncm `LoginViaCellphone`，支持明文自动转 MD5（推荐仅存 MD5）。失败时区分风控：`code` 命中 502/503 或 `msg` 含「频繁/风险/验证/异常」关键词 → 提示「建议改用扫码登录」；其余（501 密码错误、506 参数错误等）保持普通失败文案。
- **Cookie keyring 存储**：Windows 走 Credential Manager（DPAPI 加密），`service = "ncmp-desktop"`，替代原明文 `setting.json` 与 GH Secrets 回写，比远端回写更安全；`gh_token` / `gh_repo` / `notify_email` / 邮箱授权码等身份配置也统一走 keyring，重新打包不丢。
- **任务可视化**：
  - 实时日志流——`GuiLogHandler` 挂 `logging` root，把 ncmp 全部日志通过 Qt 信号推到 UI 文本框（对标 Actions live log）；`emit` 内对 `pyncm.*` 的 DEBUG/INFO 噪音做过滤（双保险，避免扫码轮询刷屏）。
  - 结构化步骤视图——`StepList` 按 `running` / `success` / `failed` / `cancelled` / `pending` 五态推进，每步带语义色图标与耗时。
- **三态状态驱动首页**：Dashboard 根据 Cookie 状态切 `unconfigured`（未配置，灰色 key 图标空状态）/ `valid`（有效，绿色）/ `expired`（失效，红色）三态卡片，主按钮随状态变（立即获取 Cookie / 立即执行任务 / 重新登录），闭环引导配置→登录→执行。
- **本地执行**：`TaskWorker`（QThread）调 `core.bot.MusicPartnerBot.run()`，bot 带 `on_step(name, status, elapsed)` / `on_progress(done, total, song_name, score)` / `cancel_event` 三个回调，通过 Qt 信号转发到主线程 UI；`Signer._sleep` 分段循环 `cancel_event.wait(1)`，点取消即时响应。
- **云端执行**：`ActionsTrigger`（GitHub REST API 封装）触发 `workflow_dispatch` + `CloudWorker`（QThread）每 5 秒轮询 run 状态，电脑关机也跑（Actions 在 GitHub 云端执行，桌面程序只看状态）。复用 `StepList` 展示「触发 / 等待 / 完成」三阶段。
- **本地定时**：`QTimer`（`setSingleShot(True)`）到点触发 + 60 秒心跳校准（防系统休眠 / 时钟漂移后失准）；模式 `local`（启动 TaskWorker）/ `cloud`（触发 Actions）/ `both`（两者都启动）；到点弹托盘通知「定时任务已启动」。
- **云端 cron 修改**：调 GitHub Contents API 读 workflow 文件 → 正则替换 `cron:` 行 → base64 编码 PUT 回仓库，远程修改 fork workflow 的 schedule；「同步完整 workflow」支持勾选「关闭云端定时」后上传注释掉 `schedule` 块的版本。
- **Cookie 同步 GitHub Secrets**：`ActionsTrigger.set_secret` 用 PyNaCl `SealedBox` 加密 value 后 PUT 到 `/repos/{repo}/actions/secrets/{name}`；`sync_cookies` 一键把本地 `MUSIC_U` + `__csrf` 写入 `Cookie_MUSIC_U` + `Cookie___csrf` 两个 Secret 供 Actions 用。PyNaCl 未装时 deferred import 兜底返回明确错误。
- **系统托盘 + Windows 通知 + 关闭确认**：`QSystemTrayIcon` 常驻，双击恢复，右键菜单（显示主窗口 / 立即执行 / 检查刷新 Cookie / 关于 / 退出）；通知优先用托盘气泡 `showMessage`，否则降级 plyer / print；`closeEvent` 拦截，按 `AppConfig.close_action`（`None`=每次弹确认框 / `"close"`=直接关 / `"minimize"`=最小化到托盘）决定，可选「不再提示」并持久化。
- **后台 Cookie 验证**：`ValidateWorker`（QThread）每 6 小时（`validate_interval_sec` 可调）跑 `CookieValidator` 三步验证（Cookie 存在 / 用户信息有效 / 任务权限），失效即托盘通知 + 主窗口 `alert` 闪烁 + 自动跳登录页。失效时按 `notify_on_cookie_expired` 开关（默认 True）调 `NotificationService.send_notification("ncmp Cookie 失效", "Cookie 已失效，请重新登录获取")` 发邮件；邮件发送失败不吞掉 `expired` 信号，UI 仍照常弹托盘通知 + 跳登录页。
- **邮件通知（3 个开关）**：设置页「邮件通知」组除 SMTP 字段外还提供 3 个 `QCheckBox` 开关，均默认勾选，写入 `AppConfig` 与 `setting.json` 双份（`AppConfig` 持久化、`Config` 读取）：
  - `notify_on_task_done`（默认 True）：**手动执行**任务完成 / 失败 / 取消时发邮件，由 `TaskWorker._send_email` 按 `notify_context == "task"` 分支读取。
  - `notify_on_cookie_expired`（默认 True）：后台 `ValidateWorker` 发现 Cookie 失效时发邮件（见上一条）。
  - `notify_on_schedule`（默认 True）：**定时执行**（`schedule_mode=local/both`）任务结果发邮件，由 `TaskWorker._send_email` 按 `notify_context == "schedule"` 分支读取，独立于 `notify_on_task_done`——定时执行只看这个开关。
  - `TaskWorker._send_email(status)` 按 `self._notify_context`（`"task"` / `"schedule"`）选 `notify_on_task_done` / `notify_on_schedule`：开关关闭直接 return；按 `status` 决定文案（`success` → 「ncmp 任务完成」/「评分任务已成功完成」；`cancelled` → 「ncmp 任务已取消」/「用户手动取消任务」；`failed` → 「ncmp 任务失败」/「评分任务失败，请查看日志」）；`NotificationService` 抛异常静默吞掉不影响主流程。
  - `CloudWorker._send_email(status, url)` 同样按 `notify_on_schedule` 开关发邮件（云端执行统一走这个开关）：`success` → 「ncmp 云端执行完成」/「GitHub Actions 云端任务已成功完成\nRun 详情：{url}」；`failed` → 「ncmp 云端执行失败」/「GitHub Actions 云端任务失败，请查看日志\nRun 详情：{url}」；本地取消轮询不发（远端 run 未完成无结论）。触发失败（ProxyError 等）也发 failed 邮件。
- **取消任务提示（区分 cancelled / failed）**：用户点「取消」设 `cancel_event`，core 层 `Signer._sleep` / `MusicPartnerBot._check_cancel` 在下一个取消点 `raise CancelledError("用户取消任务")`（原 `bot.run` 改为 `raise` 透传而非 `return False`，便于上层区分取消与失败）；`bot.run` 标当前步骤 `cancelled` 后**重新抛出** `CancelledError`，`TaskWorker.run` 用 `except CancelledError` 捕获置 `status = "cancelled"`，通用 `Exception` 置 `status = "failed"`；`finished_sig = Signal(bool, str)` 现在传 `(ok, status)`（`ok` 对 cancelled/failed 均为 `False`）；`TaskPage._on_finished` 按 `status` 显示三种文案与样式（`success` → `✅ 任务执行完成` + `successText` 绿色；`cancelled` → `⚠️ 用户手动取消任务` + `warningText` 橙黄色，**不再显示「任务完成」**；`failed` → `❌ 任务执行失败` + `dangerText` 红色）；`MainWindow._on_task_finished_from_tray` 同样按 `status` 决定托盘通知文案（`cancelled` → 「用户手动取消任务」）。
- **参数表单化配置**：13+ 项做成控件，5 个 `QGroupBox` 分组（网易云账号 / 任务参数 / 邮件通知 / 定时执行 / GitHub Actions），废弃原 GH_TOKEN 回写改本地 keyring + 云端触发；附「测试通知」「验证 Cookie」「明文→MD5」「导入/导出 setting.json」工具按钮。
- **品牌图标统一**：`create_app_icon`（圆角蓝底 `#2E7DDE` + 白色 `fa5s.music`）+ `setWindowIcon` + `AppUserModelID`（`ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ncmp.desktop.app")`，在 QApplication 构造前调用），让窗口 / 任务栏 / 托盘 / exe 图标统一，不再显示 python.exe 默认图标。
- **单实例锁**：`app/main.py` 入口用 `QLockFile`（`%TEMP%\ncmp-desktop.lock`，`setStaleLockTime(0)` 防崩溃后锁死）拦截重复启动，第二个实例弹窗提示「ncmp desktop 已在运行」后退出，避免多开相互覆盖 keyring / 定时器。

---

## 三、技术栈

| 类别 | 依赖 | 用途 |
|---|---|---|
| 语言 | Python 3.10+ | 运行时 |
| GUI 框架 | PySide6>=6.5 | Qt6 Python 原生绑定（LGPL），主窗口 / 页面 / 控件 / 信号槽 / QThread / QTimer / QSystemTrayIcon |
| 网易云 API | [pyncm](https://github.com/sakarie9/pyncm) 1.8.1（sakarie9 fork） | 扫码登录 `LoginQrcodeUnikey` / `LoginQrcodeCheck` / `GetLoginQRCodeUrl`、密码登录 `LoginViaCellphone`、`Session` / `DumpSessionAsString` |
| 图标 | qtawesome>=1.3 | FontAwesome 5/6 图标集，导航 / 步骤 / 按钮 / 托盘 / 品牌图标 |
| 凭据存储 | keyring>=24 | Windows = Credential Manager / DPAPI 加密，存 Cookie / 密码 / 邮箱授权码 / gh_token / notify_email / gh_repo |
| 加密 | pycryptodome>=3.16 | weapi 评分接口的 AES-CBC 加密（`Signer._aes_encrypt`） |
| 加密 | PyNaCl>=1.5 | `SealedBox` 加密 GitHub Actions Secrets（deferred import，未装时降级返回错误） |
| HTTP | requests>=2.28 | 网易云 API 调用、GitHub REST API 调用 |
| 二维码 | qrcode>=7.4 + Pillow>=10 | 把 pyncm 返回的二维码 URL 渲染成 PNG 字节流供 UI 显示 |

> **pyncm 版本说明**：桌面版使用 `sakarie9/pyncm`（活跃维护 fork，1.8.1），**不是** PyPI 上的 `mos9527/pyncm`（已删），也**不是** `lmc2007/pyncmfork`。pyncm 1.8.1 与原版 API 有差异，桌面版已适配（见「常见问题」）。安装方式见 `requirements.txt`：
> ```bash
> pip install "pyncm @ git+https://github.com/sakarie9/pyncm.git@master"
> ```

> **打包优化**：PyInstaller 不再用 `--collect-all PySide6`（会全量收集 Qt 插件 / QML / 翻译导致 GB 级体积），改走 PyInstaller 自带 PySide6 hook，只收代码实际 import 的 `QtCore/QtGui/QtWidgets/QtNetwork`；配合 17 个 `--exclude-module`（`PySide6.QtWebEngineWidgets` / `QtWebEngineCore` / `QtWebEngineQuick` / `QtQml` / `QtQuick` / `QtQuick3D` / `QtQuickWidgets` / `Qt3DCore` / `Qt3DRender` / `QtCharts` / `QtDataVisualization` / `QtMultimedia` / `QtMultimediaWidgets` / `QtPdf` / `QtPdfWidgets` / `QtSql` / `QtTest`）和 8 个大库 exclude（`torch` / `tensorflow` / `pandas` / `scipy` / `matplotlib` / `IPython` / `jupyter` / `notebook`），打包体积从 GB 级降到 100-200MB，耗时从 5 分钟降到 1-2 分钟。详见「打包」章节。

---

## 四、项目架构

两层结构：`core/` 核心层（基于 ncmp 改造）+ `app/` 应用层（桌面 GUI）。

### 两层结构图

```
┌─────────────────────────────────────────────────────────────┐
│                      app/  桌面应用层                         │
│  main.py · app_config · cookie_store · task_history          │
│  login/ · workers/ · cloud/ · ui/ · notify/                  │
│         ▲ Qt Signal/Slot  ▲ keyring 回调                     │
├─────────┼───────────────────────────────────────────────────┤
│         │           core/  核心层（基于 ncmp 改造）          │
│         │  bot · signer · tasks/ · validators/ · utils/       │
│         └─ on_step/on_progress/cancel_event 回调             │
│                     on_cookie_refreshed 回调                │
└─────────────────────────────────────────────────────────────┘
```

### 完整目录树

```
e:\Users\yw\Desktop\ncmp\
├─ core/                              # 核心层（基于 ncmp 改造）
│   ├─ __init__.py                    # CancelledError（用户取消任务异常）
│   ├─ bot.py                         # [改造] MusicPartnerBot + on_step/on_progress/cancel_event 回调
│   ├─ signer.py                      # [改造] Signer + per-song on_progress + 取消检查点 + 分段 sleep
│   ├─ validators/
│   │   ├─ __init__.py
│   │   └─ cookie.py                  # [复用] CookieValidator 三步验证
│   ├─ tasks/
│   │   ├─ __init__.py
│   │   ├─ base.py                    # [复用] 任务基类
│   │   ├─ daily.py                   # [复用] 每日基础评分任务
│   │   ├─ extra.py                   # [复用] 额外评分任务
│   │   └─ cookie_refresh.py         # [改造] 去远端 GitHubService 回写，改调 on_cookie_refreshed 回调
│   └─ utils/
│       ├─ __init__.py
│       ├─ auth.py                    # [复用] AuthService 密码登录（已适配 pyncm 1.8.1）
│       ├─ config.py                  # [改造] Config 优先级 keyring > env > json
│       ├─ logger.py                  # [复用] Logger（标准 logging 封装）
│       └─ notification.py            # [复用] NotificationService SMTP 邮件
├─ app/                               # 桌面应用层
│   ├─ __init__.py
│   ├─ main.py                        # 入口：AppUserModelID + QApplication + light.qss + GuiLogHandler + MainWindow
│   ├─ app_config.py                  # AppConfig（桌面自身配置：验证间隔/最小化/主题/关闭行为/定时执行）
│   ├─ cookie_store.py                # CookieStore（keyring 本地存储，替代 github.py）
│   ├─ task_history.py                # 最近任务摘要记录（最多 20 条）
│   ├─ login/
│   │   ├─ __init__.py
│   │   ├─ qr_login.py                # 扫码登录（pyncm LoginQrcodeUnikey/Check + qrcode/Pillow 渲染）
│   │   └─ pwd_login.py               # 密码登录（直接走 pyncm 拿 code/msg 便于区分风控）
│   ├─ workers/                       # QThread 工作线程（避免阻塞 UI）
│   │   ├─ __init__.py
│   │   ├─ login_worker.py            # 登录线程（扫码轮询 + 密码 + 风控判定）
│   │   ├─ task_worker.py             # 任务执行线程（调 bot.run，转发 step/progress 信号）
│   │   ├─ cloud_worker.py            # 云端执行线程（触发 dispatch + 轮询 run 状态）
│   │   └─ validate_worker.py         # Cookie 后台验证线程（6h 周期）
│   ├─ cloud/
│   │   ├─ __init__.py
│   │   └─ actions_trigger.py         # GitHub Actions API 封装（trigger/轮询/cron/Secrets/Cookie同步）
│   ├─ ui/
│   │   ├─ __init__.py
│   │   ├─ main_window.py             # 主窗口：5 页 QStackedWidget + 左侧导航 + 托盘 + 关闭确认 + QTimer 定时
│   │   ├─ icons.py                    # 图标工厂（qtawesome 封装 + create_app_icon 品牌图标）
│   │   ├─ pages/
│   │   │   ├─ __init__.py
│   │   │   ├─ dashboard_page.py      # 首页：Cookie 三态卡片 + 快捷操作 + toast
│   │   │   ├─ login_page.py          # 账号页：扫码 / 密码 Tab 切换
│   │   │   ├─ task_page.py           # 任务页：日志流 + 步骤视图 + 本地/云端双执行按钮
│   │   │   ├─ settings_page.py      # 设置页：5 分组表单 + GitHub 测试连接/cron同步/Cookie同步
│   │   │   └─ about_page.py          # 关于页：版本 + 作者 + 致谢 + 核心依赖 + GitHub 链接
│   │   ├─ widgets/
│   │   │   ├─ __init__.py
│   │   │   ├─ log_view.py            # GuiLogHandler（实时日志）+ LogView（等宽只读）
│   │   │   ├─ step_list.py           # 结构化步骤视图（五态图标）
│   │   │   └─ tray_icon.py           # 系统托盘（4 菜单 + 双击恢复）
│   │   └─ styles/
│   │       └─ light.qss               # 扁平浅色主题（语义色 + objectName 字体分级）
│   └─ notify/
│       ├─ __init__.py
│       └─ desktop_notify.py          # 系统原生通知（托盘气泡优先，plyer/print 降级）
├─ resources/
│   ├─ app.ico                        # 应用图标（exe 打包用）
│   └─ workflow_example.yml           # GitHub Actions workflow 示例模板
├─ scripts/
│   └─ gen_icon.py                    # 生成 app.ico 的脚本
├─ requirements.txt
├─ build.bat                          # 一键打包脚本
├─ ncmp.spec                          # PyInstaller spec（build.bat 生成）
└─ README.md
```

### `core/` 改造的 4 个文件说明

| 文件 | 改造点 | 原因 |
|---|---|---|
| `core/bot.py` | `MusicPartnerBot.__init__` 加 `on_step` / `on_progress` / `cancel_event` 三个回调参数；`run()` 在每个阶段（验证用户/拉取任务/评分基础/额外评分）前后调 `_step(name, status)` 推进步骤视图；`_check_cancel` 在每阶段开始处响应取消；异常分支区分 `CancelledError`（标 cancelled）与通用 Exception（标 failed） | ncmp 原 `run()` 是无回调阻塞流程，UI 无法实时显示进度 / 取消 |
| `core/signer.py` | `Signer.__init__` 加 `on_progress` / `cancel_event` / `total` / `done_offset`；`sign()` 评分成功后调 `on_progress(done, total, work["name"], score)`；`_sleep` 改成分段循环 `cancel_event.wait(min(1.0, remaining))` 响应取消；新增 `_check_cancel` 在评分入口检查；`CancelledError` 单独 except 透传，不被通用 Exception 吞掉 | ncmp 原无取消点，`time.sleep(delay)` 是主要阻塞点；UI 需 per-song 进度 |
| `core/tasks/cookie_refresh.py` | `CookieRefreshTask.__init__` 加 `on_cookie_refreshed` 回调；`execute()` 刷新成功后通过回调把新 Cookie 交给上层持久化，删除原 `GitHubService` 远端回写 | 桌面版不碰 GitHub Secrets，改由 `app/cookie_store.CookieStore` 写本地 keyring |
| `core/utils/config.py` | `Config._load_config` 优先级改为 `keyring > env > json`；新增 `_load_keyring` / `_save_keyring` / `_delete_keyring` / `_has_keyring_data` / `_load_json_config` / `write_file_config`；keyring 映射包含 Cookie、密码、`gh_token`、`notify_email`、`gh_repo`；普通字段写入 `~/.ncmp_desktop/setting.json`，并兼容旧 `config/setting.json` 迁移 | 让 ncmp 主流程能直接从 keyring 拿凭据；普通参数与凭据在重新打包后都保留 |

### `app/` 各子模块职责

| 子模块 | 职责 |
|---|---|
| `app/main.py` | 入口：设 `AppUserModelID`（任务栏品牌图标）→ 构造 `QApplication`（`setQuitOnLastWindowClosed(False)`）→ 加载 `light.qss` → 安装 `GuiLogHandler` 到 logging root（`pyncm` logger 调 WARNING 防刷屏）→ 构造 `MainWindow` + 启动后台 `ValidateWorker` → `app.exec()` |
| `app/app_config.py` | `AppConfig`：桌面自身配置（`validate_interval_sec` / `minimize_to_tray` / `theme` / `close_action` / `schedule_enabled` / `schedule_time` / `schedule_mode`），持久化到 Qt `AppConfigLocation` 下的 `config.json` |
| `app/cookie_store.py` | `CookieStore`：Cookie 本地 keyring 存储（`service="ncmp-desktop"`，key 为 `MUSIC_U` / `__csrf` / `updated_at`），keyring 不可用时降级内存字典 |
| `app/task_history.py` | `TaskHistory`：最近任务摘要记录（最多 20 条），存 `task_history.json`（与 `AppConfig` 同目录），供首页 / 任务页摘要展示 |
| `app/login/` | `QrLogin`（扫码：pyncm unikey + qrcode/Pillow 渲染 PNG）、`PwdLogin`（密码：直接走 pyncm 拿 code/msg 便于区分风控） |
| `app/workers/` | `LoginWorker`（扫码轮询 2s + 密码 + 风控判定 502/503/关键词）、`TaskWorker`（调 bot.run 转发 step/progress 信号）、`CloudWorker`（触发 dispatch + 5s 轮询 run 状态）、`ValidateWorker`（6h 周期验证 Cookie） |
| `app/cloud/` | `ActionsTrigger`：GitHub REST API 封装（`trigger` / `get_latest_run` / `get_run` / `test_auth` / `get_workflow_file` / `update_workflow_cron` / `sync_full_workflow` / `get_repo_public_key` / `set_secret` / `sync_cookies`），错误统一返回 `(False, msg)` 不抛异常 |
| `app/ui/` | `MainWindow`（5 页 QStackedWidget + 左侧 QListWidget 导航 + 托盘 + 关闭确认 + QTimer 定时）、`icons`（qtawesome 封装 + `create_app_icon` 品牌图标）、`pages/`（dashboard 三态 / login 双 Tab / task 双执行 / settings 5 分组 / about）、`widgets/`（log_view / step_list / tray_icon）、`styles/light.qss` |
| `app/notify/` | `DesktopNotify`：托盘气泡 `showMessage` 优先，plyer 降级，print 兜底 |

### 关键设计模式

1. **QThread + Signal 线程安全**：所有跨线程数据传递走 `Signal/Slot`（Qt 自动切主线程槽），`GuiLogHandler.emit` 用信号推送日志，无需手动加锁。`logging.Handler` 不是 `QObject`，故 `GuiLogHandler` 内部持有一个 `_LogSignaler`（QObject）承载 `log_signal`，外部照常 `handler.log_signal.connect(...)`。
2. **GuiLogHandler 日志流**：挂到 `logging` root，把 ncmp 全部日志实时推到 UI 文本框；`emit` 内对 `pyncm.*` 的 DEBUG/INFO 噪音做过滤（双保险），`main.py` 又把 `pyncm` logger 调到 WARNING，避免扫码轮询 `LoginQrcodeCheck` 刷屏。
3. **三态状态驱动首页**：Dashboard 根据 Cookie 状态切 `unconfigured` / `valid` / `expired` 三态卡片，主按钮随状态变，闭环引导配置→登录→执行。
4. **keyring 优先级**：`core/utils/config.py` 加载顺序 `keyring > env > json`，凭据/身份字段走 keyring；普通业务字段写入用户目录 `~/.ncmp_desktop/setting.json`，旧 `config/setting.json` 仍兼容读取。
5. **双执行模式**：本地 `MusicPartnerBot.run()` 直接执行（带 per-song 进度）；云端 `ActionsTrigger.trigger()` 走 GitHub API（无 per-song 进度，复用 StepList 展示触发/等待/完成三阶段）；两者均通过 QThread 信号反馈到 UI。
6. **deferred import（延迟导入）**：`PyNaCl`（`actions_trigger.set_secret` 内 `from nacl.public import PublicKey, SealedBox`）、`plyer`（`desktop_notify`）、`keyring`（`cookie_store` / `config`）均为可选依赖，未安装时降级返回明确错误而非崩溃。`PyNaCl` 未装时「同步 Cookie 到 GitHub Secrets」返回 `"PyNaCl 未安装，无法加密 Secret（pip install PyNaCl）"`。
7. **core 层不依赖 app 层**：core 通过回调（`on_step` / `on_progress` / `cancel_event` / `on_cookie_refreshed`）把结果交给上层，由 `app/` 决定怎么持久化（keyring 还是别的），保持核心层可独立测试与复用。

---

## 五、配置指南

### 首次运行

```bash
# 1. 安装依赖（pyncm 需从 GitHub 安装）
pip install -r requirements.txt

# 2. 启动桌面程序
python app/main.py
```

### 配置目录

| 内容 | 位置 | 说明 |
|---|---|---|
| 桌面应用自身配置 | Qt `AppConfigLocation` 下 `config.json`（Windows 通常为 `%APPDATA%\ncmp-desktop\config.json`，无 PySide6 时降级到 `~/.ncmp_desktop/config.json`） | `AppConfig`：验证间隔 / 最小化 / 主题 / 关闭行为 / 定时执行 |
| 任务历史 | 同上目录下 `task_history.json` | `TaskHistory`：最近 20 条任务结果 |
| 业务非敏感字段 | 用户目录 `~/.ncmp_desktop/setting.json` | 等待时间 / 评分策略 / SMTP 服务器 / workflow_name / workflow_branch 等；旧 `config/setting.json` 可兼容迁移 |
| Cookie / 密码 / 邮箱授权码 / gh_token / notify_email / gh_repo | 系统 keyring，`service="ncmp-desktop"` | key 分别为 `MUSIC_U` / `__csrf` / `netease_password` / `netease_md5_password` / `email_password` / `gh_token` / `notify_email` / `gh_repo` |

### 设置页 5 分组字段清单

设置页按语义分 5 个 `QGroupBox`（前 4 组为业务字段，第 5 组为云端执行）：

| 分组 | 字段 | 控件 | 说明 |
|---|---|---|---|
| 网易云账号 | `Cookie_MUSIC_U` / `Cookie___csrf` | QLineEdit 只读 + Password echo + eye 切换 | 由登录流程自动写入，无需手动填；默认掩码显示，点眼睛查看 |
| | `netease_phone` | QLineEdit | 11 位手机号，仅密码登录需要 |
| | `netease_password` | QLineEdit Password + eye 切换 + 「→ MD5」按钮 | 明文密码，二选一，登录后建议转 MD5 |
| | `netease_md5_password` | QLineEdit Password + eye 切换 | MD5 密码（推荐，更安全） |
| 任务参数 | `wait_time_min` / `wait_time_max` | QSpinBox（0-3600 秒） | 每次评分等待秒数，默认 15 / 20，实际随机 |
| | `score` | QComboBox | 1=1-2分 / 2=2-3分 / 3=3-4分（默认）/ 4=固定4分 |
| | `full_extra_tasks` | QCheckBox | 勾选完成所有额外任务（忽略每日 7 个上限，默认勾选） |
| 邮件通知 | `notify_email` / `email_password` | QLineEdit / Password | 接收通知邮箱 / SMTP 授权码（非登录密码） |
| | `smtp_server` | QComboBox 可编辑 | 预设 QQ / Gmail / 163 / Outlook / 126，默认 `smtp.qq.com`，可手输 |
| | `smtp_port` | QSpinBox（1-65535） | SSL 默认 465，TLS 为 587 |
| | `notify_on_task_done` | QCheckBox（默认勾选） | 手动执行任务完成 / 失败 / 取消时发邮件（`TaskWorker._send_email` 按 `notify_context == "task"` 读取） |
| | `notify_on_cookie_expired` | QCheckBox（默认勾选） | 后台 `ValidateWorker` 发现 Cookie 失效时发邮件（独立于 `expired` 信号，邮件失败不影响 UI 弹托盘通知） |
| | `notify_on_schedule` | QCheckBox（默认勾选） | 定时执行（`schedule_mode=local/both`）任务结果发邮件，独立于 `notify_on_task_done`——定时执行只看这个开关 |
| 定时执行 | `schedule_enabled` | QCheckBox | 启用定时执行（写入 AppConfig，不入 setting.json） |
| | `schedule_time` | QTimeEdit HH:mm | 触发时间，24 小时制，默认 09:00 |
| | `schedule_mode` | QComboBox | local / cloud / both |
| GitHub Actions | `gh_token` | QLineEdit Password + eye 切换 | GitHub PAT（需 repo + workflow 权限），仅存 keyring 不上传 |
| | `gh_repo` | QLineEdit | `owner/repo` 形式，存 keyring，重新打包不丢 |
| | `workflow_name` | QLineEdit | 如 `refresh_cookie.yml` |
| | `workflow_branch` | QLineEdit | 如 `main` |
| | `gh_disable_schedule` | QCheckBox | 勾选后「同步完整 workflow」会注释 GitHub 原生 `schedule`，仅保留手动触发 |

附工具按钮：`保存` / `测试通知` / `验证 Cookie` / `明文→MD5` / `导入 setting.json` / `导出 setting.json`，以及 GitHub 区的 `测试连接` / `同步 cron` / `同步完整 workflow` / `同步 Cookie 到 GitHub Secrets`。四个 GitHub 网络操作均走 `_GitHubActionWorker` 后台线程，并显示 indeterminate 进度条。

> 「同步完整 workflow」按钮（`_sync_full_workflow`）：读取打包内 / 源码目录的 `resources/workflow_example.yml` 模板，调 GitHub Contents API PUT 覆盖到 fork 仓库的 `.github/workflows/{workflow_name}`，一键同步最新 workflow 文件（含 `concurrency` / `continue-on-error` / `upload-artifact` 等配置），无需手动复制粘贴。若勾选「关闭云端定时」，`_set_workflow_schedule()` 会先把 `schedule:` 与 `- cron:` 注释掉，再上传。

---

## 六、GitHub Actions 云端执行

桌面程序支持把任务托管到云端 Actions 执行（适合 24h 不开机也能跑的场景）。

### 配置步骤

设置页 GitHub Actions 分组顶部有 caption 始终可见，鼠标悬停 4 个字段有 tooltip 详细获取说明。完整流程 5 步：

1. **fork ncmp 仓库**：打开 https://github.com/ACAne0320/ncmp → 右上角 Fork 到自己账号下。
2. **复制 workflow 文件**：把本项目 `resources/workflow_example.yml` 内容复制到 fork 仓库的 `.github/workflows/refresh_cookie.yml`（文件名可自定义，需与下方 `workflow_name` 字段一致）。
3. **生成 GitHub PAT**：头像 → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token (classic) → 勾选 `repo`（全选）+ `workflow` → Generate → 复制 token（只显示一次，丢失需重新生成）。
4. **填写 4 字段并保存**：在设置页 GitHub Actions 分组填 `gh_token` / `gh_repo` / `workflow_name` / `workflow_branch`，点「保存」。`gh_token` / `gh_repo` 存 keyring，`workflow_name` / `workflow_branch` 写入 `~/.ncmp_desktop/setting.json`。
5. **测试与同步**：点「测试连接」验证 token + repo 可访问（GET `/repos/{repo}`，成功返回仓库 `full_name`）；再点「同步 Cookie 到 GitHub Secrets」把本地 `MUSIC_U` + `__csrf` 用 PyNaCl 加密后写入 `Cookie_MUSIC_U` + `Cookie___csrf` 两个 Secret 供云端 workflow 用。

### 4 字段 tooltip（鼠标悬停可见）

| 字段 | tooltip 要点 |
|---|---|
| `gh_token` | 路径：头像 → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate → 勾 repo+workflow；仅本地 keyring 保存，不上传。 |
| `gh_repo` | 仓库全名 `owner/repo`（如 `yourname/ncmp`）；也可填完整 URL `https://github.com/owner/repo`，`ActionsTrigger.__init__` 自动解析提取 owner/repo。 |
| `workflow_name` | `.github/workflows/` 下的 yml 文件名，如 `refresh_cookie.yml`。 |
| `workflow_branch` | 触发分支，fork 后默认 `main`（老仓库可能 `master`），看仓库主页左上分支选择器。 |

### Secrets 配置（在 fork 仓库网页手动配，云端执行需要）

在 fork 仓库 **Settings → Secrets and variables → Actions** 配置：

| Secret | 必填 | 说明 |
|---|---|---|
| `MUSIC_U` | 是 | 云音乐 Cookie 的 MUSIC_U |
| `CSRF` | 是 | 云音乐 Cookie 的 `__csrf` |
| `NETEASE_PHONE` | 密码登录用 | 手机号（与密码二选一） |
| `NETEASE_PASSWORD` | - | 明文密码（与 MD5 二选一） |
| `NETEASE_MD5_PASSWORD` | 推荐 | MD5 密码（可用桌面程序「明文→MD5」按钮生成） |
| `NOTIFY_EMAIL` | 可选 | 接收通知邮箱 |
| `EMAIL_PASSWORD` | 可选 | SMTP 授权码 |
| `SMTP_SERVER` | 可选 | 默认 `smtp.qq.com` |
| `SMTP_PORT` | 可选 | 默认 465 |
| `WAIT_TIME_MIN` / `WAIT_TIME_MAX` | 可选 | 评分等待秒数，默认 15 / 20 |
| `FULL_EXTRA_TASKS` | 可选 | `true`/`false`，默认 false |

> 也可以用桌面程序「同步 Cookie 到 GitHub Secrets」按钮自动写 `Cookie_MUSIC_U` + `Cookie___csrf`，workflow 示例同时兼容 `MUSIC_U` / `CSRF` 与 `Cookie_MUSIC_U` / `Cookie___csrf` 两套名字。

### cron 同步（北京时间 → UTC）

设置页 GitHub Actions 分组底部的「云端 cron」用 **`QTimeEdit` 时间选择器**（`HH:mm` 24 小时制，默认 09:00）输入北京时间，点「同步 cron」时程序自动转 UTC（北京 -8）写入 fork 仓库的 workflow schedule：

```
北京时间 09:00 → cron "0 1 * * *"（UTC 01:00）
北京时间 16:00 → cron "0 8 * * *"（UTC 08:00）
```

实现：`settings_page._sync_cron_to_workflow` 读 `QTimeEdit.time()`，`_utc_h = (hour - 8) % 24`，拼 `"分 时 * * *"`，调 `ActionsTrigger.update_workflow_cron` GET workflow 文件 → 正则替换 `cron:` 行 → base64 编码 PUT 回仓库。cron 表达式不存本地，每次点「同步 cron」直接改 fork 仓库文件。

> cron 不保存到本地配置，以 fork 仓库 workflow 文件里的实际值为准。

### workflow 触发方式

`refresh_cookie.yml` 支持两种入口：

- `workflow_dispatch`（手动）：桌面程序「云端执行」按钮走这个入口，可选传入 `score`（1/2/3/4）/ `wait_time_min` / `wait_time_max` / `full_extra_tasks` inputs（inputs 优先于 Secrets 默认值）。
- `schedule`（定时）：默认每天 08:00 UTC（北京时间 16:00）跑一次，可用桌面程序「同步 cron」按钮远程修改；勾选「关闭云端定时」后点「同步完整 workflow」即可注释 `schedule` 块。GitHub 原生 cron 由仓库 workflow 决定，与桌面端 `schedule_mode` 无关。

workflow 还含 `concurrency`（`ncmp-refresh` 组，`cancel-in-progress: false`，避免多 run 并发触发风控）、`continue-on-error: true`（失败不中断，继续上传日志）、`upload-artifact`（`run_output.log`，retention 14 天）。

### 任务页双按钮

任务页顶部两个执行按钮：

- **「立即执行(本地)」**：启动 `TaskWorker` 调 `bot.run()`，带 per-song 进度（`QProgressBar` + `StepList.addProgress`）。
- **「云端执行」**：启动 `CloudWorker` 触发 `workflow_dispatch` + 5s 轮询 run 状态，无 per-song 进度（GitHub 不暴露），复用 StepList 展示「触发 / 等待 / 完成」三阶段。

两个按钮互斥（运行中禁用），共用「取消」按钮。本地取消即停 bot；云端取消会定位本次 run 并调用 GitHub cancel API，尽量真正停止远端 run。

> 桌面程序的 `gh_token` 仅本地保存到 keyring，绝不上传到任何远端。

---

## 七、本地定时

桌面版有 **两套独立的定时机制**：本地定时（QTimer）与 workflow cron（GitHub Actions schedule）。两者互不感知、各自独立触发，互不冲突。

### 两套机制对比

| 机制 | 触发者 | 电脑关机是否跑 | 修改方式 |
|---|---|---|---|
| 本地定时（QTimer） | 桌面程序自身到点触发 | 不跑（要求程序常驻运行） | 设置页「定时执行」分组 |
| workflow cron（schedule） | GitHub 云端定时触发 | 仍跑（Actions 在 GitHub 跑） | 设置页「云端 cron」按钮远程改；「关闭云端定时」+「同步完整 workflow」可注释 schedule |

### 本地定时（QTimer）

`MainWindow` 用两个 `QTimer` 实现本地定时执行：

- **触发定时器** `_schedule_timer`：`setSingleShot(True)`，计算到下一次 `(HH:MM)` 壁钟时刻的秒数启动（今天已过则取明天），到点调 `_on_schedule_tick` 按 `schedule_mode` 启动 local/cloud/both 任务。
- **心跳定时器** `_schedule_heartbeat_timer`：`setSingleShot(False)`，每 60 秒调一次 `_setup_schedule` 重新计算并重排触发定时器，防系统休眠 / 时钟漂移后失准。

### 模式区别（仅本地定时）

| 模式 | 行为 | 电脑关机 |
|---|---|---|
| `local` | 启动 `TaskWorker` 调 `bot.run()` | 不跑（程序需运行） |
| `cloud` | 触发 GitHub Actions `workflow_dispatch` | 仍跑（Actions 在云端） |
| `both` | 两者都启动 | 本地不跑，云端仍跑 |

### 到点通知

到点先弹托盘通知「定时任务已启动」，本地完成由 `_on_task_finished_from_tray` 通知「任务执行完成」/「任务未完成」，云端完成由 `TaskPage.cloud_finished_sig` → `_on_schedule_cloud_finished` 通知「云端任务完成：成功」/「云端任务完成：失败（...）」。

设置页保存定时配置后 emit `schedule_config_changed` 信号，主窗口重读 `AppConfig` 并重排定时器（幂等）。

### 本地定时 vs workflow cron 并存建议

两套机制互不感知：

- **不一致**：本地定时和 workflow cron 设的时间不同 → 各自跑，互不干扰。
- **同时触发风险**：如果本地定时的时间 == workflow cron 的时间，且本地模式设为 `cloud` 或 `both` → 同一时刻既本地触发 dispatch 又云端 schedule 触发，**workflow 的 `concurrency` 不会取消已 in-progress 的 run**（`cancel-in-progress: false`）→ 两个 run 并发跑 → 风控风险。
- **建议**：常驻用本地定时，关机跑用 workflow cron，两者**错开时间**（如本地 09:00、workflow cron 16:00），避免双 dispatch。

---

## 八、打包

双击项目根目录 `build.bat` 即可一键打包。脚本为单行 pyinstaller 命令（无 `^` 续行符），所有 echo 输出用英文（避免中文乱码），开头 `taskkill /f /im ncmp.exe` 先杀运行中实例释放 exe 占用，结束后 `explorer /select,"...\ncmp.exe"` 自动定位生成的可执行文件：

```bat
@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [0/4] Closing running ncmp.exe ...
taskkill /f /im ncmp.exe >nul 2>&1

echo [1/4] Checking dependencies ...
pip install pyinstaller qtawesome pyncm PySide6 keyring qrcode Pillow pycryptodome PyNaCl requests >nul 2>&1

echo [2/4] Cleaning old build artifacts ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist ncmp.spec del /q ncmp.spec

echo [3/4] Building (1-2 minutes, please wait) ...
pyinstaller --noconsole --windowed -y --name ncmp --icon resources\app.ico --collect-all qtawesome --collect-all pyncm --add-data "app\ui\styles\light.qss;ui\styles" --add-data "resources\workflow_example.yml;resources" --hidden-import keyring.backends --hidden-import keyring.backends.Windows --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineQuick --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQuick3D --exclude-module PySide6.QtQuickWidgets --exclude-module PySide6.Qt3DCore --exclude-module PySide6.Qt3DRender --exclude-module PySide6.QtCharts --exclude-module PySide6.QtDataVisualization --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtMultimediaWidgets --exclude-module PySide6.QtPdf --exclude-module PySide6.QtPdfWidgets --exclude-module PySide6.QtSql --exclude-module PySide6.QtTest --exclude-module torch --exclude-module tensorflow --exclude-module pandas --exclude-module scipy --exclude-module matplotlib --exclude-module IPython --exclude-module jupyter --exclude-module notebook app\main.py

echo [4/4] Done.
echo Executable:  %~dp0dist\ncmp\ncmp.exe
explorer /select,"%~dp0dist\ncmp\ncmp.exe"
if not defined NOPAUSE pause
```

打包成功后可执行文件位于 `dist\ncmp\ncmp.exe`，体积 100-200MB，耗时 1-2 分钟。

**关键参数说明**：

- `taskkill /f /im ncmp.exe`：先杀运行中的 ncmp.exe 进程，释放文件占用避免 build/dist 目录删不掉。
- `--collect-all qtawesome` / `--collect-all pyncm`：收集这两个包的全部资源（图标字体 ttf/json、非 `.py` 文件），缺任何一个都会运行时 ImportError 或样式丢失。
- **不再用** `--collect-all PySide6`：PyInstaller 自带 PySide6 hook，自动只收集代码实际 import 的 `QtCore` / `QtGui` / `QtWidgets` / `QtNetwork`，不打包没用的 QML / Qt 插件 / 翻译，体积从 GB 级降到 100-200MB。
- 17 个 PySide6 子模块 `--exclude-module`：`QtWebEngineWidgets` / `QtWebEngineCore` / `QtWebEngineQuick` / `QtQml` / `QtQuick` / `QtQuick3D` / `QtQuickWidgets` / `Qt3DCore` / `Qt3DRender` / `QtCharts` / `QtDataVisualization` / `QtMultimedia` / `QtMultimediaWidgets` / `QtPdf` / `QtPdfWidgets` / `QtSql` / `QtTest`，明确排除桌面版用不到的 Qt 大模块。
- 8 个大库 `--exclude-module`：`torch` / `tensorflow` / `pandas` / `scipy` / `matplotlib` / `IPython` / `jupyter` / `notebook`，防止 PyInstaller 误把本机环境里装的这些大库拉进 exe。
- `--add-data "app\ui\styles\light.qss;ui\styles"`：把 qss 样式文件打进 exe（目标路径 `ui\styles\light.qss`），配合 `app/main.py` 的 `_resource_path()` 用 `sys._MEIPASS` 定位，确保打包后样式仍能正确加载。
- `--add-data "resources\workflow_example.yml;resources"`：把 workflow 模板打进 `_internal\resources\workflow_example.yml`，配合 `settings_page._sync_full_workflow` 用 `sys._MEIPASS` 定位，确保打包后「同步完整 workflow」能读模板。
- `--hidden-import keyring.backends` / `--hidden-import keyring.backends.Windows`：keyring 用 `importlib` 动态加载后端，PyInstaller 静态分析发现不了，必须显式声明，否则打包后启动报 `No keyring backend found`。
- `--icon resources\app.ico`：exe 图标。
- `--noconsole --windowed`：无控制台窗口的 GUI 程序。
- 英文 echo：脚本所有输出用英文（`[0/4] Closing running ncmp.exe ...` 等），避免 Windows 控制台默认 GBK 编码导致中文乱码。
- `explorer /select,"path"`：打包结束自动在新窗口选中生成的 `ncmp.exe`，方便右键发送桌面快捷方式。
- `if not defined NOPAUSE pause`：仅交互式双击运行时 pause 等待回车；CI 设了 `NOPAUSE` 环境变量时自动退出，方便自动化调用。

**打包后 qss 加载**：`app/main.py` 加了 `_resource_path(*parts)` 函数，打包后从 `sys._MEIPASS`（PyInstaller 解压临时目录）读资源，开发模式从源码目录读。`load_stylesheet` 用 `_resource_path("ui", "styles", "light.qss")` 拿到 qss 路径 → 读文本 → `app.setStyleSheet`，确保打包后扁平浅色主题仍生效。

---

## 九、常见问题

**Q：扫码时日志疯狂刷屏？**
A：已修复。pyncm 扫码轮询会狂打 `LoginQrcodeCheck` 的 DEBUG 日志。`app/main.py` 启动时把 `pyncm` logger 调到 WARNING，`GuiLogHandler.emit` 内又对 `pyncm.*` 的 DEBUG/INFO 噪音做过滤（双保险）。ncmp 自身日志（`core.` / `app.`）仍走 DEBUG 不受影响。

**Q：密码登录提示风控 / 安全验证？**
A：频繁密码登录可能触发网易云安全验证。`LoginWorker` 在失败时区分风控：`code` 命中 502/503 或 `msg` 含「频繁/风险/验证/异常」关键词 → 提示「密码登录触发风控，建议改用扫码登录（账号页「扫码登录」Tab）」；其余（501/-501 密码错误、506 参数错误等）保持普通失败文案。扫码走官方流程、风控低，优先推荐。

**Q：Cookie 过期了怎么办？**
A：后台 `ValidateWorker` 每 6 小时（`validate_interval_sec` 可调）跑 `CookieValidator` 三步验证（Cookie 存在 / 用户信息有效 / 任务权限），失效会弹系统托盘通知 + 主窗口 `alert` 闪烁 + 自动跳到登录页，重新扫码即可。网易云 Cookie 约 2 周过期但无精确到期时间，故采用「定期验证 + 失效即提醒」而非倒计时。

**Q：任务栏显示 python.exe 默认图标？**
A：已修复。`app/main.py` 在 QApplication 构造前调 `ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ncmp.desktop.app")`，配合 `MainWindow.setWindowIcon(create_app_icon())`，让窗口 / 任务栏 / 托盘图标统一为品牌图标（圆角蓝底 + 白色音符）。

**Q：打包后 exe 启动报 `QLockFile.tryLock0 takes exactly one argument (0 given)`？**
A：PySide6 的 `QLockFile.tryLock` 在 C++ 签名是 `tryLock(int timeout=0)`，但 PySide6 Python 绑定没暴露默认值，开发模式（`python app/main.py`）容忍零参调用，PyInstaller 打包后绑定严格检查参数个数就报错。`app/main.py` 已改 `_lock.tryLock()` → `_lock.tryLock(0)` 显式传 0（不等待立即返回）。同类坑：其他带 C++ 默认参数的 PySide6 方法在打包后也可能要求显式传参，若遇类似 `takes exactly N arguments` 报错，补上默认参数即可。

**Q：打包后启动报 `No keyring backend found` / keyring 报错？**
A：keyring 在 Windows 用 `importlib` 动态加载后端（Credential Manager），PyInstaller 静态分析发现不了。`build.bat` 已加 `--hidden-import keyring.backends` / `--hidden-import keyring.backends.Windows`，若仍失败可补 `--collect-all keyring`。

**Q：以管理员身份运行后，普通身份运行读不到 Cookie？**
A：keyring Windows 后端走 Credential Manager（DPAPI），凭据按用户身份隔离。请保持同一用户身份运行，不要在管理员 / 普通身份间切换。

**Q：pyncm 装不上 / 装错版本 / API 报错？**
A：必须用 `sakarie9/pyncm`（活跃 fork，1.8.1），不是已删的 `mos9527/pyncm`，也不是 `lmc2007/pyncmfork`。`requirements.txt` 已配 GitHub 安装源：`pip install "pyncm @ git+https://github.com/sakarie9/pyncm.git@master"`。若 github.com 网络不通，可改用 tarball：
```powershell
Invoke-WebRequest "https://api.github.com/repos/sakarie9/pyncm/tarball/master" -OutFile pyncm.tgz
pip install pyncm.tgz --no-build-isolation
```
pyncm 1.8.1 与原版 API 有差异，桌面版已适配：
- `GetCurrentSession` 已移除 → 改为显式 `Session()` 并传 `session=` 关键字参数（`LoginViaCellphone` / `LoginQrcodeUnikey` / `LoginQrcodeCheck` / `GetLoginQRCodeUrl` 均需）。
- 扫码 API 改名：`LoginQrcodeUnikey`（申请令牌）/ `LoginQrcodeCheck`（轮询状态）/ `GetLoginQRCodeUrl`（取含 chainId 的二维码 URL，新版风控需要 chainId）。
- `DumpSessionAsString` 仍可用（调试）。

**Q：「同步 Cookie 到 GitHub Secrets」报 PyNaCl 未安装？**
A：PyNaCl 是可选依赖（deferred import）。`ActionsTrigger.set_secret` 内 `from nacl.public import PublicKey, SealedBox` 失败时返回 `(False, "PyNaCl 未安装，无法加密 Secret（pip install PyNaCl）")`，不崩溃。装上即可：`pip install PyNaCl`。

**Q：GitHub API 报 401/403/404/422？**
A：`ActionsTrigger` 把 HTTP 错误响应拼成用户可读的 msg：
- `401` → 「token 无效或已过期」
- `403` → 「权限不足：token 需 repo + workflow 权限」
- `404` → 「仓库或 workflow 不存在：{url}」
- `422` → 「{prefix}：{message}」（如触发参数错误、分支/workflow 不存在）
- 网络异常 → 「网络请求失败：{e}」

**Q：云端执行触发失败 `ProxyError` / `ConnectionError`？**
A：网络 / 代理不稳定。`ActionsTrigger.trigger` 走 `requests.post`，遇代理切换 / DNS 抖动 / TLS 握手失败会抛 `ProxyError` / `ConnectionError`，`CloudWorker` 把异常 msg 透传到 UI 显示。requests 会自动重试底层连接，多数情况下多试几次（或换网络 / 关代理）最终成功；如稳定复现可在 `actions_trigger.py` 的 `requests.post` 调用处加 `retry=` 参数或 `urllib3.util.Retry` 适配器做显式重试。

**Q：重复启动弹窗提示「已在运行」？**
A：这是单实例锁机制。`app/main.py` 入口在构造 QApplication 前用 `QLockFile` 加锁，锁文件位于 `%TEMP%\ncmp-desktop.lock`，`setStaleLockTime(0)` 让残留锁立即判 stale（防进程崩溃后锁死）。第二个实例 `tryLock()` 失败 → Windows 上用 `MessageBoxW` 弹「ncmp desktop 已在运行，请勿重复启动。」→ 退出。这是正常行为，避免多开相互覆盖 keyring / 定时器；如需强行启动第二个实例，先删 `%TEMP%\ncmp-desktop.lock` 或重启系统。

**Q：云端执行跳设置页（提示 gh_repo 缺失）？**
A：已修复。`core/utils/config.py` 的 `Config` 走 keyring 分支时，原逻辑不读普通配置，导致 `gh_repo` / `workflow_name` / `workflow_branch` 读不到被判 missing，触发跳设置页引导。现在 `gh_repo` 直接走 keyring，`workflow_name` / `workflow_branch` 从 `~/.ncmp_desktop/setting.json` 兜底读取，云端执行能正常拿到仓库信息。

**Q：`gh_repo` 填完整 URL 行不行？**
A：已兼容。`ActionsTrigger.__init__` 加了 URL 解析逻辑：检测到 `github.com/` 子串时，取其后的 `owner/repo` 部分（取前两段），如 `https://github.com/yourname/ncmp` → `yourname/ncmp`。填 `owner/repo` 或完整 URL 都行。

**Q：填了 `gh_repo` 点保存，重启后回显不到（gh_token 还在）？**
A：已修复。`gh_repo`、`notify_email` 已纳入 keyring；普通字段写入用户目录 `~/.ncmp_desktop/setting.json`（兼容旧 `config/setting.json` 迁移），不再依赖打包目录，重新打包后仍能读回。

**Q：打包后点「同步完整 workflow」报 `No such file or directory: '..._internal\app\resources\workflow_example.yml'`？**
A：已修复。原 `_sync_full_workflow` 用 `os.path.dirname(os.path.dirname(os.path.dirname(__file__)))` 定位模板，打包后 `__file__` 在 `_internal/app/ui/pages/`，向上 3 级到 `_internal/app`，拼 `resources/workflow_example.yml` → `_internal/app/resources/...`（错，应为 `_internal/resources/...`）。修复：路径解析改用 `sys._MEIPASS`（打包）或项目根（开发，向上 4 级），并在 `build.bat` 加 `--add-data "resources\workflow_example.yml;resources"` 把 yml 打进 `_internal/resources/`，开发与打包路径都正确。

---

## 十、开发指南

### 启动顺序

`app/main.py` 启动顺序：

1. 设 `AppUserModelID`（Windows 任务栏品牌图标，必须在 QApplication 构造前调用）
2. 构造 `QApplication`，设 `setQuitOnLastWindowClosed(False)`（关主窗口托盘仍在）
3. 加载 `light.qss` 浅色扁平主题
4. 安装 `GuiLogHandler` 到 `logging` root，`pyncm` logger 调 WARNING 防刷屏
5. 构造 `MainWindow` + `TrayIcon`，`install_log_handler` + `start_background_workers`（托盘 + 后台 `ValidateWorker`）
6. `app.exec()` 进入事件循环

### 调试

```bash
# 直接运行（无需打包）
python app/main.py
```

日志会同时输出到任务页 `LogView`（通过 `GuiLogHandler`）。`LogView` 是只读 `QPlainTextEdit`，等宽字体（Consolas / Courier New），`MaximumBlockCount=5000` 防内存无限堆积，自动滚到底。

### 改造 ncmp 的方法

`core/` 层不依赖 `app/` 层：core 通过回调把结果交给上层。改造原则：

- 直接复用不改：`core/validators/cookie.py`（CookieValidator）、`core/utils/logger.py`（Logger）、`core/utils/notification.py`（NotificationService）、`core/utils/auth.py`（AuthService，已适配 pyncm 1.8.1）、`core/tasks/daily.py` / `extra.py` / `base.py`。
- 已改造 4 文件：`core/bot.py` / `core/signer.py` / `core/tasks/cookie_refresh.py` / `core/utils/config.py`（详见「项目架构 → core/ 改造的 4 个文件说明」）。
- 废弃：`core/utils/github.py`（GitHub Secrets 回写），桌面版用 `app/cloud/actions_trigger.py` 触发 Actions 代替回写。

### 添加新任务类型

1. 在 `core/tasks/` 新建任务类，构造函数接 `session` / `logger` / `config` / `on_progress` / `cancel_event`（参考 `daily.py` / `extra.py`）。
2. 在 `core/bot.py` 的 `MusicPartnerBot.run()` 中插入新阶段：调 `self._check_cancel()` + `self._step(name, "running")` → 执行 → `self._step(name, "success")`，异常分支自动标 `failed` / `cancelled`。
3. UI 自动跟进：`TaskWorker.step` 信号已连 `StepList.updateStep`，新步骤会自动出现在步骤视图。

### 日志

- ncmp 自身日志（`core.` / `app.`）走 DEBUG，全部推到 UI。
- pyncm 日志调到 WARNING + `emit` 过滤双保险，避免扫码轮询刷屏。
- 调试 pyncm 时可临时注释 `app/main.py` 的 `logging.getLogger("pyncm").setLevel(logging.WARNING)` 行。

---

## 十一、致谢与许可

- 基于 [ACAne0320/ncmp](https://github.com/ACAne0320/ncmp)（MIT License）改造。
- 网易云 API 封装来自 [sakarie9/pyncm](https://github.com/sakarie9/pyncm)（活跃维护 fork，1.8.1）。
- 图标来自 [qtawesome](https://github.com/spyder-ide/qtawesome)（FontAwesome / Material Design Icons / Phosphor / Remix Icon 等图标集）。
- GUI 框架 [PySide6](https://www.qt.io/)（Qt6 Python 原生绑定，LGPL）。
- 凭据存储 [keyring](https://github.com/jaraco/keyring)（Windows = Credential Manager / DPAPI）。
- 加密 pycryptodome（weapi AES）、[PyNaCl](https://github.com/pyca/pynacl)（GitHub Secrets 加密）。

版权：MIT License。

---

## 十二、后续开发计划

### S7 多账号管理（本地优先）

**现状**：单账号架构——`CookieStore` 固定一组 key（`ncmp-desktop/Cookie_MUSIC_U` / `Cookie___csrf`），登录新账号覆盖旧 Cookie，`Config` / `TaskWorker` / `ValidateWorker` / 定时执行均按单账号设计。

**目标**：支持多账号本地管理与批量执行，云端多账号后续扩展。

#### 存储改造
- `CookieStore` 按账号名分 key：`ncmp-desktop/{account_name}/music_u` + `/csrf`，保持 keyring 加密
- 新增 `app/account_manager.py`：JSON 存账号清单（`config/accounts.json`），每条含 `name` / `last_login` / `cookie_status` / `created_at`
- `Config` 加 `account` 维度：参数可「全局」或「按账号」存（`score` / `wait_time` / `notify_email` 等按账号覆盖全局默认）

#### UI 改造
- **首页 dashboard**：账号下拉切换器（QComboBox）+ 当前账号 Cookie 状态卡；三态卡按选中账号渲染
- **账号页 login**：登录表单加「账号备注名」字段（如「主号」「小号」），扫码/密码成功后绑定该名字存入 accounts.json
- **账号列表 widget**：账号管理弹窗（增/删/改备注名/查看最后登录/Cookie 状态/设为默认）
- **设置页 settings**：参数分组加「全局 / 按账号」切换开关；按账号模式下字段绑定选中账号
- **任务页 task**：执行前选账号下拉 + 「全部账号批量执行」按钮；批量时顺序跑、每账号间留随机间隔避免风控

#### 执行改造
- `TaskWorker.__init__` 加 `account: str` 参数，从对应 keyring key 加载 Cookie 构造 session
- `ValidateWorker` 遍历所有账号逐个验证，失效账号在首页账号下拉标红
- **定时执行**：模式加「全部账号」选项（现有「本地 / 云端 / 两者」基础上扩），到点遍历跑所有账号，每账号间 `random.uniform(30, 60)` 间隔

#### 云端多账号（后续）
- GitHub Actions 单 workflow 一次跑一账号：`workflow_dispatch.inputs.account` 参数指定账号，workflow 从对应 Secret 读（`Cookie_MUSIC_U_{account}` / `Cookie___csrf_{account}`）
- 「同步 Cookie」按钮按账号同步到不同 Secret 名
- workflow 内循环跑所有账号（需 workflow 改造，或桌面多次 dispatch）

#### 工作量
约 1-2 天（本地多账号），云端多账号额外 0.5 天。

#### 风险
- 多账号批量执行若间隔过短可能触发网易云风控（评分行为集中）—— 每账号间留 30-60s 随机间隔
- keyring 多 key 管理需注意账号名规范（只允许字母数字下划线中文，避免 keyring key 转义问题）

### 其他待办（优先级低）
- S8 任务历史可视化图表（成功率趋势）
- S9 开机自启动（Windows 启动项注册）
- S10 自动更新检查（GitHub Releases 比对版本）
