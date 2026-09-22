"""云端执行工作线程：触发 GitHub Actions workflow 并轮询运行状态。

跨线程通过 Qt 信号把状态/日志推到主线程，复用 task_page 的 step/log 槽。
- step(name, status, elapsed)：与 TaskWorker 同签名，直接接 StepList.updateStep
- log(line)：单行文本，直接接 LogView.appendLog
- finished_sig(ok, conclusion/html_url)：结束信号

cancel() 会先尝试定位本次触发的 run，然后调用 GitHub Actions 的取消接口；
若短时间内定位不到 run（Actions 尚未返回新 run），最多继续轮询 60 秒。
"""
import threading
import time
from typing import Optional

from PySide6.QtCore import QThread, Signal

from app.cloud.actions_trigger import ActionsTrigger
from core.utils.config import Config
from core.utils.logger import Logger
from core.utils.notification import NotificationService


class CloudWorker(QThread):
    """云端执行工作线程。"""

    # name, status, elapsed（秒，float）—— 与 TaskWorker.step 同签名
    step = Signal(str, str, float)
    # 单行日志文本
    log = Signal(str)
    # 云端阶段进度（0-100）：触发/排队/执行中/完成，GitHub 不提供 per-song 数据
    progress = Signal(int)
    # ok, conclusion / html_url
    finished_sig = Signal(bool, str)

    # 轮询间隔（秒）
    POLL_INTERVAL = 5
    # 用户点取消后，最多再花多少秒等待/定位刚触发的 run 去取消
    CANCEL_LOCATE_TIMEOUT = 60

    def __init__(self, token: str, repo: str, workflow: str, branch: str,
                 parent=None) -> None:
        super().__init__(parent)
        self._token = token
        self._repo = repo
        self._workflow = workflow
        self._branch = branch
        self.cancel_event = threading.Event()

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def cancel(self) -> None:
        """请求取消：尝试取消远端 run；若尚未定位到 run，则继续短时间定位。"""
        self.cancel_event.set()

    # ------------------------------------------------------------------
    # QThread.run
    # ------------------------------------------------------------------
    def run(self) -> None:  # noqa: D401
        try:
            self._run_impl()
        except Exception as e:
            # 兜底：保证 finished_sig 总会发出
            try:
                self.log.emit(f"❌ CloudWorker 异常：{e}")
            except Exception:
                pass
            try:
                self.step.emit("等待云端执行", "failed", 0.0)
            except Exception:
                pass
            self.finished_sig.emit(False, f"异常：{e}")

    def _run_impl(self) -> None:
        t0 = time.time()
        trigger = ActionsTrigger(self._token, self._repo)

        # 阶段 1：触发 workflow_dispatch
        self.progress.emit(5)
        self.step.emit("触发 workflow_dispatch", "running", 0.0)
        ok, msg = trigger.trigger(self._workflow, self._branch)
        if not ok:
            self.step.emit("触发 workflow_dispatch", "failed", time.time() - t0)
            self.log.emit(f"❌ 触发失败：{msg}")
            self.progress.emit(0)
            self._send_email("failed", "")
            self.finished_sig.emit(False, msg)
            return
        triggered_at = time.time()
        self.progress.emit(20)
        self.step.emit("触发 workflow_dispatch", "success", time.time() - t0)
        self.log.emit("✅ 已触发，等待 Actions 排队执行...")

        # 阶段 2：轮询最新 run（每 5s，cancel_event 控制）
        self.step.emit("等待云端执行", "running", time.time() - t0)
        last_id: Optional[int] = None
        last_status: Optional[str] = None
        run_id: Optional[int] = None
        poll_ticks = 0
        # GitHub 与本地时钟可能有秒级偏差，留 60s 宽限避免漏掉刚触发的 run
        poll_since = triggered_at - 60
        cancel_deadline: Optional[float] = None
        cancel_notice_emitted = False

        while True:
            r = trigger.get_latest_run(self._workflow, since=poll_since)
            if r:
                rid = r.get("id")
                status = r.get("status")
                conclusion = r.get("conclusion")
                if rid != last_id:
                    # 新 run 出现
                    run_id = rid
                    self.log.emit(
                        f"Run #{rid} status={status} conclusion={conclusion}")
                    last_id = rid
                    last_status = status
                elif status != last_status:
                    # 状态变化（如 queued -> in_progress）
                    self.log.emit(
                        f"Run #{rid} status={status} conclusion={conclusion}")
                    last_status = status
                if status == "completed":
                    success = conclusion == "success"
                    self.progress.emit(100)
                    self.step.emit(
                        "等待云端执行",
                        "success" if success else "failed",
                        time.time() - t0,
                    )
                    url = r.get("html_url", "") or ""
                    if url:
                        self.log.emit(f"Run 详情：{url}")
                    self._send_email("success" if success else "failed", url)
                    self.finished_sig.emit(
                        success, url or (conclusion or "completed"))
                    return
                if self.cancel_event.is_set():
                    # 已经拿到 run id，直接调用 GitHub 取消接口
                    self._cancel_remote_run(trigger, run_id or rid, t0)
                    return
                if status == "queued":
                    self.progress.emit(30)
                elif status == "in_progress":
                    # GitHub 没有 per-song 数据，轮询期间缓慢推进到 90，完成时再置 100
                    self.progress.emit(min(90, 40 + poll_ticks * 2))

            poll_ticks += 1

            # 用户已点取消：优先用已定位的 run id，否则限时继续定位
            if self.cancel_event.is_set():
                if run_id is not None:
                    self._cancel_remote_run(trigger, run_id, t0)
                    return
                if not cancel_notice_emitted:
                    self.log.emit("⏳ 正在定位远端 run 以执行取消…")
                    cancel_notice_emitted = True
                if cancel_deadline is None:
                    cancel_deadline = time.time() + self.CANCEL_LOCATE_TIMEOUT
                if time.time() >= cancel_deadline:
                    self.step.emit(
                        "等待云端执行", "cancelled", time.time() - t0)
                    self.log.emit(
                        "⚠️ 未能在 60 秒内定位到远端 run，"
                        "请到 GitHub Actions 页面手动取消")
                    self.finished_sig.emit(
                        False, "取消远端失败：未能在 60 秒内定位到 run")
                    return

            # 正常轮询等待 5s，可被 cancel 唤醒；取消定位阶段 Event 已 set，
            # wait 会立即返回，因此改用固定 sleep，避免高频请求 GitHub API。
            if self.cancel_event.is_set():
                time.sleep(self.POLL_INTERVAL)
            else:
                self.cancel_event.wait(self.POLL_INTERVAL)

    def _cancel_remote_run(self, trigger: ActionsTrigger, run_id: int,
                           t0: float) -> None:
        """调用 GitHub API 取消远端 run，并把结果通过信号送回 UI。"""
        self.step.emit("等待云端执行", "cancelled", time.time() - t0)
        self.log.emit(f"正在取消远端 Run #{run_id}…")
        ok, msg = trigger.cancel_run(run_id)
        if ok:
            self.log.emit(f"✅ 已请求 GitHub 取消 Run #{run_id}")
            self.finished_sig.emit(False, "已取消（已请求 GitHub 停止远端 run）")
        else:
            self.log.emit(f"⚠️ 取消远端 run 失败：{msg}")
            self.finished_sig.emit(
                False, f"取消远端失败：{msg}")

    def _send_email(self, status: str, url: str = "") -> None:
        """按 notify_on_schedule 开关发邮件；失败不影响主流程。

        云端执行统一走 notify_on_schedule 开关（关机/云端场景）。
        本地取消轮询不发（远端 run 未完成，无结论）。
        """
        try:
            config = Config()
            if not bool(config.get("notify_on_schedule", True)):
                return
            if status == "success":
                subject = "ncmp 云端执行完成"
                content = (f"GitHub Actions 云端任务已成功完成\nRun 详情：{url}"
                           if url else "GitHub Actions 云端任务已成功完成")
            else:
                subject = "ncmp 云端执行失败"
                content = (f"GitHub Actions 云端任务失败，请查看日志\nRun 详情：{url}"
                           if url else "GitHub Actions 云端任务失败，请查看日志")
            NotificationService(config, Logger()).send_notification(subject, content)
        except Exception:
            pass
