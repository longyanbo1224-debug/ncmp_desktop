import json
import os
import random
from typing import Any, Dict, Optional

# keyring 为可选依赖：未安装时降级到 env/json
try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False


class Config:
    """配置加载器。

    桌面版优先级：keyring > env > json 文件。
    - 敏感字段（Cookie / 密码 / 邮箱授权码）走 keyring（Windows 上即 Credential Manager / DPAPI）
    - 非敏感字段仍支持 env 与 config/setting.json 兼容
    - keyring 不可用时自动降级到原 env/json 链路
    """

    KEYRING_SERVICE = "ncmp-desktop"

    # 敏感字段在配置字典与 keyring 用户名之间的映射
    _KEYRING_KEY_MAP = {
        "Cookie_MUSIC_U": "MUSIC_U",
        "Cookie___csrf": "__csrf",
        "netease_password": "netease_password",
        "netease_md5_password": "netease_md5_password",
        "email_password": "email_password",
    }

    def __init__(self):
        self.config_data: Dict = self._load_config()

    # ------------------------------------------------------------------
    # 顶层加载策略
    # ------------------------------------------------------------------
    def _load_config(self) -> Dict:
        # 优先级：keyring > env > json 文件
        if KEYRING_AVAILABLE and self._has_keyring_cookies():
            config: Dict = {}
            # 敏感字段来自 keyring
            config.update(self._load_keyring())
            # 非敏感字段从 setting.json 兜底（gh_repo/workflow_name/branch 等）
            config.update(self._load_file_non_sensitive())
            # 非敏感字段仍允许 env 覆盖
            config.update(self._load_env_overrides())
            # env 里的凭据（优先级低于 keyring，仅填补空缺）
            for k, v in self._load_env_credentials().items():
                config.setdefault(k, v)
            # 通知邮箱等同样允许 env 覆盖
            if (notify_email := os.getenv("NOTIFY_EMAIL")):
                config["notify_email"] = notify_email
            self._apply_defaults(config)
            return config
        if self._check_env_variables():
            return self._load_from_env()
        return self._load_from_file()

    # ------------------------------------------------------------------
    # keyring 后端
    # ------------------------------------------------------------------
    def _has_keyring_cookies(self) -> bool:
        """检查 keyring 中是否已有可用 Cookie。"""
        try:
            music_u = keyring.get_password(self.KEYRING_SERVICE, "MUSIC_U")
            csrf = keyring.get_password(self.KEYRING_SERVICE, "__csrf")
            return bool(music_u and csrf)
        except Exception:
            return False

    def _load_keyring(self) -> Dict:
        """从 keyring 读取所有敏感字段。"""
        config: Dict = {}
        if not KEYRING_AVAILABLE:
            return config
        try:
            for cfg_key, kr_key in self._KEYRING_KEY_MAP.items():
                val = keyring.get_password(self.KEYRING_SERVICE, kr_key)
                if val:
                    config[cfg_key] = val
        except Exception:
            pass
        return config

    def _save_keyring(self, config: Dict) -> None:
        """把敏感字段写入 keyring（供上层调用）。"""
        if not KEYRING_AVAILABLE:
            return
        for cfg_key, kr_key in self._KEYRING_KEY_MAP.items():
            val = config.get(cfg_key)
            if not val:
                continue
            try:
                keyring.set_password(self.KEYRING_SERVICE, kr_key, str(val))
            except Exception:
                pass

    def _delete_keyring(self) -> None:
        """清空 keyring 中的所有敏感字段。"""
        if not KEYRING_AVAILABLE:
            return
        for kr_key in self._KEYRING_KEY_MAP.values():
            try:
                keyring.delete_password(self.KEYRING_SERVICE, kr_key)
            except Exception:
                pass

    def _load_file_non_sensitive(self) -> Dict:
        """从 setting.json 读非敏感字段（keyring 模式下兜底 gh_repo 等）。

        敏感字段（Cookie/密码/邮箱授权码）走 keyring，不在此覆盖。
        路径与 _load_from_file 一致：config/setting.json（相对 cwd）。
        """
        config: Dict = {}
        config_path = "config/setting.json"
        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.loads(f.read())
                sensitive = set(self._KEYRING_KEY_MAP.keys()) | {
                    "Cookie_MUSIC_U", "Cookie___csrf"}
                for k, v in data.items():
                    if k not in sensitive:
                        config.setdefault(k, v)
        except Exception:
            pass
        return config

    # ------------------------------------------------------------------
    # env 后端
    # ------------------------------------------------------------------
    def _check_env_variables(self) -> bool:
        required_vars = ["MUSIC_U", "CSRF"]
        return all(os.getenv(var) for var in required_vars)

    def _load_from_env(self) -> Dict:
        config = {}

        # 必需的环境变量
        config["Cookie_MUSIC_U"] = os.getenv("MUSIC_U")
        config["Cookie___csrf"] = os.getenv("CSRF")

        # 可选的非敏感字段
        config.update(self._load_env_overrides())

        # 凭据类（敏感）
        config.update(self._load_env_credentials())

        # GitHub 相关配置（桌面版已废弃，仅为兼容原 Actions 用户保留读取）
        if gh_token := os.getenv("GH_TOKEN"):
            config["gh_token"] = gh_token
        if gh_repo := os.getenv("GH_REPO"):
            config["gh_repo"] = gh_repo

        self._apply_defaults(config)
        return config

    def _load_env_overrides(self) -> Dict:
        """从环境变量加载非敏感字段（keyring 模式下也用作覆盖）。"""
        config: Dict = {}
        if smtp_server := os.getenv("SMTP_SERVER"):
            config["smtp_server"] = smtp_server
        if smtp_port := os.getenv("SMTP_PORT"):
            config["smtp_port"] = int(smtp_port)
        if wait_min := os.getenv("WAIT_TIME_MIN"):
            config["wait_time_min"] = float(wait_min)
        if wait_max := os.getenv("WAIT_TIME_MAX"):
            config["wait_time_max"] = float(wait_max)
        if score := os.getenv("SCORE"):
            config["score"] = int(score)
        if full_extra_tasks := os.getenv("FULL_EXTRA_TASKS"):
            config["full_extra_tasks"] = full_extra_tasks.lower() in ("1", "true", "yes")
        return config

    def _load_env_credentials(self) -> Dict:
        """从环境变量加载凭据类敏感字段。"""
        config: Dict = {}
        if email_password := os.getenv("EMAIL_PASSWORD"):
            config["email_password"] = email_password
        if phone := os.getenv("NETEASE_PHONE"):
            config["netease_phone"] = phone
        if password := os.getenv("NETEASE_PASSWORD"):
            config["netease_password"] = password
        if md5_password := os.getenv("NETEASE_MD5_PASSWORD"):
            config["netease_md5_password"] = md5_password
        return config

    # ------------------------------------------------------------------
    # json 文件后端
    # ------------------------------------------------------------------
    def _load_from_file(self) -> Dict:
        """从 setting.json 加载配置。

        不再因 Cookie 缺失就抛异常——Cookie 等敏感字段走 keyring，
        setting.json 只剩非敏感字段（gh_repo/workflow_name/... 等），
        用户可能在登录前就先填好 GitHub 仓库参数并保存，此时 setting.json
        无 Cookie，应能正常读回 gh_repo 等非敏感字段。
        """
        try:
            config_path = "config/setting.json"
            if not os.path.exists(config_path):
                return {}
            with open(config_path, "r", encoding="utf-8") as file:
                config = json.loads(file.read())
            if not isinstance(config, dict):
                return {}
            self._apply_defaults(config)
            return config
        except Exception:
            return {}

    def _validate_config(self, config: Dict) -> None:
        required_keys = ["Cookie_MUSIC_U", "Cookie___csrf"]
        for key in required_keys:
            if not config.get(key):
                raise ValueError(f"配置文件中缺少必要的配置项: {key}")

        self._apply_defaults(config)

    def _apply_defaults(self, config: Dict) -> None:
        """统一设置默认值。"""
        config.setdefault("wait_time_min", 15)
        config.setdefault("wait_time_max", 20)
        config.setdefault("smtp_server", "smtp.gmail.com")
        config.setdefault("smtp_port", 465)
        config.setdefault("score", 3)  # 默认使用3-4分策略
        config.setdefault("full_extra_tasks", True)
        # 邮件通知开关（默认勾选）
        config.setdefault("notify_on_task_done", True)
        config.setdefault("notify_on_cookie_expired", True)
        config.setdefault("notify_on_schedule", True)

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        return self.config_data.get(key, default)

    def get_wait_time(self) -> float:
        """获取随机等待时间"""
        min_time = float(self.get("wait_time_min", 15))
        max_time = float(self.get("wait_time_max", 20))
        return random.uniform(min_time, max_time)


# 兼容性别名：plan 与验证脚本中以 ConfigManager 命名此类
ConfigManager = Config
