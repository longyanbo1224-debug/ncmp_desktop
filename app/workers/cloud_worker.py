"""云端执行工作线程：触发 GitHub Actions workflow 并轮询运行状态。

跨线程通过 Qt 信号把状态/日志推到主线程，复用 task_page 的 step/log 槽。
- step(name, status, elapsed)：与 TaskWorker 同签名，直接接 StepList.updateStep
- log(line)：单行文本，直接接 LogView.appendLog
- finished_sig(ok, conclusion/html_url)：结束信号

cancel() 通过 cancel_event 中断轮询循环；触发阶段已发出的 POST 不可取消，
但停止后 UI 不再跟随状态变化。
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
    # ok, conclusion / html_url
    finished_sig = Signal(bool, str)

    # 轮询间隔（秒）
    POLL_INTERVAL = 5

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
        """请求取消：停止轮询。已发出的 workflow_dispatch 不可撤回。"""
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
        self.step.emit("触发 workflow_dispatch", "running", 0.0)
        ok, msg = trigger.trigger(self._workflow, self._branch)
        if not ok:
            self.step.emit("触发 workflow_dispatch", "failed", time.time() - t0)
            self.log.emit(f"❌ 触发失败：{msg}")
            self._send_email("failed", "")
            self.finished_sig.emit(False, msg)
            return
        self.step.emit("触发 workflow_dispatch", "success", time.time() - t0)
        self.log.emit("✅ 已触发，等待 Actions 排队执行...")

        # 阶段 2：轮询最新 run（每 5s，cancel_event 控制）
        self.step.emit("等待云端执行", "running", time.time() - t0)
        last_id: Optional[int] = None
        last_status: Optional[str] = None
        while not self.cancel_event.is_set():
            r = trigger.get_latest_run()
            if r:
                rid = r.get("id")
                status = r.get("status")
                conclusion = r.get("conclusion")
                if rid != last_id:
                    # 新 run 出现
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
            # 等待 5s，可被 cancel 唤醒
            self.cancel_event.wait(self.POLL_INTERVAL)
        # 取消分支
        self.step.emit("等待云端执行", "cancelled", time.time() - t0)
        self.log.emit("已取消本地轮询（远端 run 仍会继续执行）")
        self.finished_sig.emit(False, "已取消")

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
