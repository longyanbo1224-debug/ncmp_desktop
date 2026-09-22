"""GitHub Actions 触发与轮询 API 封装（基于 requests，无新依赖）。

封装以下调用：
    - trigger(workflow, branch) -> (ok, msg)：POST workflow_dispatch
    - get_latest_run(workflow=None, since=None) -> dict | None：取最近一次 workflow_dispatch run
    - get_run(run_id) -> dict：查指定 run 状态
    - cancel_run(run_id) -> (ok, msg)：取消指定 run
    - test_auth() -> (ok, msg)：验证 token + repo 可访问

workflow cron 与 Actions Secrets：
    - get_workflow_file(workflow, branch) -> (ok, content_b64_or_err, sha)
    - update_workflow_cron(workflow, branch, new_cron) -> (ok, msg)
    - get_repo_public_key() -> (ok, key_b64_or_err, key_id)
    - set_secret(name, value) -> (ok, msg)：PyNaCl SealedBox 加密后 PUT
    - sync_cookies(music_u, csrf) -> (ok, msg)：写 Cookie_MUSIC_U + Cookie___csrf

错误处理统一返回 (False, msg)，不抛异常，便于上层直接 emit。
状态码映射：
    401 -> token 无效
    403 -> 权限不足（需 repo + workflow）
    404 -> repo 或 workflow 不存在
    422 -> 触发参数错误（如分支/workflow 不存在）
    网络异常 -> 网络请求失败：{e}
"""
from typing import Any, Dict, Optional, Tuple

import requests


class ActionsTrigger:
    """触发 GitHub Actions workflow 并轮询运行状态。"""

    API = "https://api.github.com"

    def __init__(self, token: str, repo: str) -> None:
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ncmp-desktop",
        })
        # repo 兼容完整 URL：https://github.com/owner/repo -> owner/repo
        repo = (repo or "").strip()
        if "github.com/" in repo.lower():
            repo = repo.split("github.com/", 1)[-1]
            parts = repo.split("/")
            if len(parts) >= 2:
                repo = f"{parts[0]}/{parts[1]}"
        self.repo = repo.strip().strip("/")

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------
    def trigger(self, workflow: str, branch: str) -> Tuple[bool, str]:
        """触发 workflow_dispatch。

        :param workflow: workflow 文件名（如 refresh_cookie.yml）或 id
        :param branch: 触发分支（如 main）
        :return: (ok, msg)；成功 msg="已触发"
        """
        workflow = (workflow or "").strip()
        branch = (branch or "").strip()
        if not workflow or not branch:
            return False, "workflow 或 branch 为空"
        url = (f"{self.API}/repos/{self.repo}/"
               f"actions/workflows/{workflow}/dispatches")
        try:
            r = self.s.post(url, json={"ref": branch}, timeout=15)
        except requests.RequestException as e:
            return False, f"网络请求失败：{e}"
        if r.status_code == 204:
            return True, "已触发"
        return False, self._fmt_err(r, "触发失败")

    def get_latest_run(self, workflow: Optional[str] = None,
                       since: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """取最近一次 workflow_dispatch run。

        :param workflow: 可选 workflow 文件名（GitHub 不支持按文件名直接过滤，
            这里仅在响应里校验 workflow_id/path 是否匹配）
        :param since: 可选 epoch 秒时间戳；仅返回创建时间晚于该值（严格大于）的 run，
            用于把轮询绑定到「刚触发的那次 run」，避免拿到历史 run 误判完成。
        :return: dict(id, status, conclusion, html_url, created_at, head_branch) 或 None
        """
        url = f"{self.API}/repos/{self.repo}/actions/runs"
        params = {"per_page": 5, "event": "workflow_dispatch"}
        try:
            r = self.s.get(url, params=params, timeout=15)
        except requests.RequestException:
            return None
        if r.status_code != 200:
            return None
        try:
            data = r.json()
            runs = data.get("workflow_runs") or []
        except Exception:
            return None
        for run in runs:
            # 如指定 workflow 名，过滤匹配 path（如 .github/workflows/refresh_cookie.yml）
            if workflow:
                path = (run.get("path") or "").split("/")[-1]
                if path != workflow:
                    continue
            if since is not None:
                created_ts = self._parse_iso8601(run.get("created_at") or "")
                if created_ts is not None and created_ts <= since:
                    continue
            return self._pick_run(run)
        return None

    def get_run(self, run_id: int) -> Dict[str, Any]:
        """查指定 run 的状态。失败时返回 {"error": msg}。"""
        try:
            url = f"{self.API}/repos/{self.repo}/actions/runs/{run_id}"
            r = self.s.get(url, timeout=15)
        except requests.RequestException as e:
            return {"error": f"网络请求失败：{e}"}
        if r.status_code != 200:
            return {"error": self._fmt_err(r, "查询失败")}
        try:
            return self._pick_run(r.json())
        except Exception:
            return {"error": "响应解析失败"}

    def cancel_run(self, run_id: int) -> Tuple[bool, str]:
        """取消指定 workflow run。

        POST /repos/{repo}/actions/runs/{run_id}/cancel
        - 202：已接受取消请求（GitHub 会异步把 run 标记为 cancelled）
        - 404：run 不存在
        - 409：run 已完成，无法取消

        :param run_id: workflow run id
        :return: (ok, msg)
        """
        try:
            run_id = int(run_id)
        except (TypeError, ValueError):
            return False, "run_id 无效"
        url = f"{self.API}/repos/{self.repo}/actions/runs/{run_id}/cancel"
        try:
            r = self.s.post(url, timeout=15)
        except requests.RequestException as e:
            return False, f"网络请求失败：{e}"
        if r.status_code == 202:
            return True, "已请求取消远端 run"
        if r.status_code == 404:
            return False, "run 不存在"
        if r.status_code == 409:
            return False, "run 已完成，无需取消"
        return False, self._fmt_err(r, "取消 run 失败")

    def test_auth(self) -> Tuple[bool, str]:
        """验证 token + repo 可访问。

        返回 (ok, msg)；成功 msg 含 full_name。
        """
        if not self.s.headers.get("Authorization") or self.s.headers["Authorization"] == "Bearer ":
            return False, "未配置 token"
        if not self.repo:
            return False, "未配置仓库"
        url = f"{self.API}/repos/{self.repo}"
        try:
            r = self.s.get(url, timeout=15)
        except requests.RequestException as e:
            return False, f"网络请求失败：{e}"
        if r.status_code == 401:
            return False, "token 无效或已过期"
        if r.status_code == 403:
            return False, "权限不足：token 需 repo 权限"
        if r.status_code == 404:
            return False, f"仓库不存在或无权访问：{self.repo}"
        if r.status_code == 200:
            try:
                data = r.json()
                full = data.get("full_name", self.repo)
                return True, f"连接成功，仓库：{full}"
            except Exception:
                return True, "连接成功"
        return False, self._fmt_err(r, "未知响应")

    # ------------------------------------------------------------------
    # workflow cron 修改
    # ------------------------------------------------------------------
    def get_workflow_file(self, workflow: str, branch: str) -> Tuple[bool, str, str]:
        """读取 workflow 文件内容。

        GET /repos/{repo}/contents/.github/workflows/{workflow}?ref={branch}

        :param workflow: workflow 文件名（如 refresh_cookie.yml）
        :param branch: 分支名（如 main）
        :return: (ok, content_base64_or_error, sha)
            - 成功：content_base64 为 GitHub 返回的 base64 文件内容；sha 用于 PUT 更新
            - 失败：content_base64_or_error 为错误说明，sha 为空串
        """
        workflow = (workflow or "").strip()
        branch = (branch or "").strip()
        if not workflow or not branch:
            return False, "workflow 或 branch 为空", ""
        url = (f"{self.API}/repos/{self.repo}/contents/"
               f".github/workflows/{workflow}")
        try:
            r = self.s.get(url, params={"ref": branch}, timeout=15)
        except requests.RequestException as e:
            return False, f"网络请求失败：{e}", ""
        if r.status_code != 200:
            return False, self._fmt_err(r, "读取 workflow 失败"), ""
        try:
            data = r.json()
            content_b64 = data.get("content") or ""
            sha = data.get("sha") or ""
            if not content_b64 or not sha:
                return False, "响应缺少 content 或 sha 字段", ""
            return True, content_b64, sha
        except Exception as e:
            return False, f"响应解析失败：{e}", ""

    def sync_full_workflow(self, workflow: str, branch: str,
                           content: str) -> Tuple[bool, str]:
        """把完整 workflow 内容覆盖写入 fork 仓库。

        先 GET 拿 sha（文件存在则 PUT 更新，不存在则 PUT 创建），
        直接用传入的 content 覆盖远端文件，不做任何正则替换。

        :param workflow: workflow 文件名（如 refresh_cookie.yml）
        :param branch: 分支名
        :param content: workflow 文件完整内容（UTF-8 文本）
        :return: (ok, msg)；成功 msg="workflow 已同步：{workflow}"
        """
        import base64

        workflow = (workflow or "").strip()
        branch = (branch or "").strip()
        content = content or ""
        if not workflow or not branch:
            return False, "workflow 或 branch 为空"
        if not content.strip():
            return False, "workflow 内容为空"

        # 1. 先 GET 拿 sha（存在则更新；404 不存在则 sha="" 创建）
        sha = ""
        ok_get, _content_b64, sha = self.get_workflow_file(workflow, branch)
        # get_workflow_file 失败可能是 404（文件不存在，正常创建）或真错误（401/403）
        # 404 时 _fmt_err 返回"仓库或 workflow 不存在"，含"不存在"
        if not ok_get and "不存在" not in _content_b64:
            return False, _content_b64  # 真 API 错误（权限/token）

        # 2. base64 编码 + PUT 覆盖
        try:
            new_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        except Exception as e:
            return False, f"workflow 内容编码失败：{e}"

        url = (f"{self.API}/repos/{self.repo}/contents/"
               f".github/workflows/{workflow}")
        body: Dict[str, Any] = {
            "message": "chore: sync full workflow from ncmp-desktop",
            "content": new_b64,
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        try:
            r = self.s.put(url, json=body, timeout=15)
        except requests.RequestException as e:
            return False, f"网络请求失败：{e}"
        if r.status_code in (200, 201):
            return True, f"workflow 已同步：{workflow}"
        return False, self._fmt_err(r, "同步 workflow 失败")

    def update_workflow_cron(self, workflow: str, branch: str,
                             new_cron: str) -> Tuple[bool, str]:
        """修改 workflow 的 cron schedule 表达式。

        步骤：
            1. GET contents 拿当前内容 + sha
            2. base64 decode 内容，正则替换 `cron:` 行为 new_cron
            3. base64 encode，PUT 回仓库

        :param workflow: workflow 文件名（如 refresh_cookie.yml）
        :param branch: 分支名
        :param new_cron: 新的 cron 表达式（如 "0 9 * * *"）
        :return: (ok, msg)；成功 msg="已更新 cron：{new_cron}"
        """
        import base64
        import re

        workflow = (workflow or "").strip()
        branch = (branch or "").strip()
        new_cron = (new_cron or "").strip()
        if not workflow or not branch:
            return False, "workflow 或 branch 为空"
        if not new_cron:
            return False, "cron 表达式为空"

        # 1. 读 workflow
        ok, content_b64, sha = self.get_workflow_file(workflow, branch)
        if not ok:
            return False, content_b64  # content_b64 此时是错误说明

        # 2. decode + 替换 cron 行
        try:
            raw = base64.b64decode(content_b64).decode("utf-8")
        except Exception as e:
            return False, f"workflow 内容解码失败：{e}"

        # 匹配 `cron: 'xxx'` / `cron: "xxx"` / `cron: xxx` 行
        # 允许前导空白 + 可选的 YAML list-item 短横线（`- cron: ...`）
        pattern = re.compile(
            r'^([ \t]*(?:-[ \t]+)?cron[ \t]*:[ \t]*)([\'"]?)([^\'"\n#]+)([\'"]?)([ \t]*(?:#.*)?)$',
            re.MULTILINE,
        )
        if not pattern.search(raw):
            return False, "未在 workflow 中找到 cron: 行"
        new_raw = pattern.sub(
            lambda m: f"{m.group(1)}'{new_cron}'{m.group(5)}", raw, count=1)

        # 3. 编码 + PUT
        try:
            new_b64 = base64.b64encode(new_raw.encode("utf-8")).decode("ascii")
        except Exception as e:
            return False, f"workflow 内容编码失败：{e}"

        url = (f"{self.API}/repos/{self.repo}/contents/"
               f".github/workflows/{workflow}")
        body = {
            "message": f"chore: update cron schedule -> {new_cron}",
            "content": new_b64,
            "sha": sha,
            "branch": branch,
        }
        try:
            r = self.s.put(url, json=body, timeout=15)
        except requests.RequestException as e:
            return False, f"网络请求失败：{e}"
        if r.status_code in (200, 201):
            return True, f"已更新 cron：{new_cron}"
        return False, self._fmt_err(r, "更新 cron 失败")

    # ------------------------------------------------------------------
    # GitHub Actions Secrets
    # ------------------------------------------------------------------
    def get_repo_public_key(self) -> Tuple[bool, str, str]:
        """获取仓库的 Actions 公钥。

        GET /repos/{repo}/actions/secrets/public-key

        :return: (ok, key_b64_or_err, key_id)
            - 成功：key_b64_or_err 为 base64 编码的公钥；key_id 用于 PUT Secret
            - 失败：key_b64_or_err 为错误说明，key_id 为空串
        """
        url = f"{self.API}/repos/{self.repo}/actions/secrets/public-key"
        try:
            r = self.s.get(url, timeout=15)
        except requests.RequestException as e:
            return False, f"网络请求失败：{e}", ""
        if r.status_code != 200:
            return False, self._fmt_err(r, "获取公钥失败"), ""
        try:
            data = r.json()
            key = data.get("key") or ""
            key_id = data.get("key_id") or ""
            if not key or not key_id:
                return False, "响应缺少 key 或 key_id 字段", ""
            return True, key, str(key_id)
        except Exception as e:
            return False, f"响应解析失败：{e}", ""

    def set_secret(self, name: str, value: str) -> Tuple[bool, str]:
        """写入/更新一个 GitHub Actions Secret。

        用 PyNaCl SealedBox 加密 value 后 PUT 到
        /repos/{repo}/actions/secrets/{name}。

        :param name: Secret 名（GitHub 大小写不敏感，习惯用下划线）
        :param value: 明文值
        :return: (ok, msg)
        """
        import base64

        name = (name or "").strip()
        value = value or ""
        if not name or not value:
            return False, "name 或 value 为空"

        # 1. 获取公钥
        ok, key_b64, key_id = self.get_repo_public_key()
        if not ok:
            return False, key_b64  # 此时是错误说明

        # 2. PyNaCl 加密（deferred import：未安装时降级返回 (False, msg)）
        try:
            from nacl.public import PublicKey, SealedBox
        except ImportError:
            return False, "PyNaCl 未安装，无法加密 Secret（pip install PyNaCl）"
        try:
            box = SealedBox(PublicKey(base64.b64decode(key_b64)))
            encrypted = box.encrypt(value.encode("utf-8"))
            secret_b64 = base64.b64encode(encrypted).decode("ascii")
        except Exception as e:
            return False, f"加密失败：{e}"

        # 3. PUT Secret
        url = f"{self.API}/repos/{self.repo}/actions/secrets/{name}"
        body = {"encrypted_value": secret_b64, "key_id": key_id}
        try:
            r = self.s.put(url, json=body, timeout=15)
        except requests.RequestException as e:
            return False, f"网络请求失败：{e}"
        if r.status_code in (201, 204):
            return True, f"Secret {name} 已写入"
        return False, self._fmt_err(r, f"写入 Secret {name} 失败")

    def sync_cookies(self, music_u: str, csrf: str) -> Tuple[bool, str]:
        """把 MUSIC_U 与 __csrf 同步到 GitHub Secrets。

        分别写入 ``Cookie_MUSIC_U`` 与 ``Cookie___csrf`` 两个 Secret。

        :param music_u: 网易云 MUSIC_U
        :param csrf: 网易云 __csrf
        :return: (ok, msg)；两个都成功才返回 True
        """
        music_u = music_u or ""
        csrf = csrf or ""
        if not music_u or not csrf:
            return False, "MUSIC_U 或 __csrf 为空"
        ok1, msg1 = self.set_secret("Cookie_MUSIC_U", music_u)
        if not ok1:
            return False, f"同步 MUSIC_U 失败：{msg1}"
        ok2, msg2 = self.set_secret("Cookie___csrf", csrf)
        if not ok2:
            return False, f"同步 __csrf 失败：{msg2}"
        return True, "Cookie 已同步到 GitHub Secrets（Cookie_MUSIC_U + Cookie___csrf）"

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    @staticmethod
    def _pick_run(run: Dict[str, Any]) -> Dict[str, Any]:
        """从 raw run 抽取 UI 关心的字段。"""
        return {
            "id": run.get("id"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "html_url": run.get("html_url", ""),
            "created_at": run.get("created_at", ""),
            "head_branch": run.get("head_branch", ""),
        }

    @staticmethod
    def _parse_iso8601(value: str) -> Optional[float]:
        """把 GitHub 返回的 ISO-8601 时间解析为 epoch 秒；失败返回 None。"""
        if not value:
            return None
        try:
            from datetime import datetime, timezone
            text = value.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return None

    @staticmethod
    def _fmt_err(r: requests.Response, prefix: str) -> str:
        """把 HTTP 错误响应拼成用户可读的 msg。"""
        if r.status_code == 401:
            return "token 无效或已过期"
        if r.status_code == 403:
            return "权限不足：token 需 repo + workflow 权限"
        if r.status_code == 404:
            return f"仓库或 workflow 不存在：{r.url}"
        if r.status_code == 422:
            try:
                msg = r.json().get("message", "参数错误")
            except Exception:
                msg = "参数错误"
            return f"{prefix}：{msg}"
        try:
            msg = r.json().get("message")
        except Exception:
            msg = ""
        return f"{prefix}：{msg or f'HTTP {r.status_code}'}"
