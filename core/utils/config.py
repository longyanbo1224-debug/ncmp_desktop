import json
import os
import random
from typing import Any, Dict, Optional


def _default_config_file() -> str:
    """业务配置写入用户目录固定路径，重新打包/更换启动目录也不会丢失。"""
    base = os.path.join(os.path.expanduser("~"), ".ncmp_desktop")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "setting.json")

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
    - 非敏感字段写入用户目录固定路径，重新打包后仍保留
    - keyring 不可用时自动降级到原 env/json 链路
    """

    KEYRING_SERVICE = "ncmp-desktop"

    # 走 keyring 持久化的字段：配置键 -> keyring 用户名
    _KEYRING_KEY_MAP = {
        "Cookie_MUSIC_U": "MUSIC_U",
        "Cookie___csrf": "__csrf",
        "netease_password": "netease_password",
        "netease_md5_password": "netease_md5_password",
        "email_password": "email_password",
        "gh_token": "gh_token",
        "notify_email": "notify_email",
        "gh_repo": "gh_repo",
    }

    def __init__(self):
        self.config_data: Dict = self._load_config()

    # ------------------------------------------------------------------
    # 顶层加载策略
    # ------------------------------------------------------------------
    def _load_config(self) -> Dict:
        # 优先级：keyring > env > json 文件
        if KEYRING_AVAILABLE and self._has_keyring_data():
            config: Dict = {}
            # 敏感字段来自 keyring
            config.update(self._load_keyring())
            # 非敏感字段从 setting.json 兜底（workflow_name/branch 等）
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
    def _has_keyring_data(self) -> bool:
        """检查 keyring 中是否已有任一已保存配置。"""
        try:
            for kr_key in self._KEYRING_KEY_MAP.values():
                if keyring.get_password(self.KEYRING_SERVICE, kr_key):
                    return True
            return False
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
        """从稳定路径的 setting.json 读非敏感字段，keyring 字段不在此覆盖。"""
        config: Dict = {}
        data = self._load_json_config()
        sensitive = set(self._KEYRING_KEY_MAP.keys())
        for k, v in data.items():
            if k not in sensitive:
                config.setdefault(k, v)
        return config

    @classmethod
    def _load_json_config(cls) -> Dict:
        """读取稳定路径 setting.json；兼容迁移旧的 config/setting.json。"""
        paths = (cls.config_file(), os.path.join("config", "setting.json"))
        for path in paths:
            try:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.loads(f.read())
                    if isinstance(data, dict):
                        return data
            except Exception:
                continue
        return {}

    @classmethod
    def config_file(cls) -> str:
        """返回业务配置的稳定 JSON 路径。"""
        return _default_config_file()

    @classmethod
    def write_file_config(cls, config: Dict) -> None:
        """把非敏感业务配置写入稳定 JSON 路径。"""
        path = cls.config_file()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

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
        普通字段写入用户目录固定路径，重新打包后仍能读回。
        """
        try:
            config = self._load_json_config()
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
        config.setdefault("smtp_server", "smtp.qq.com")
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
