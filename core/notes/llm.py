"""可选：用用户自己的 LLM 生成批注（OpenAI 兼容接口）。

**默认不启用**，只有用户在设置里填了 endpoint / 模型 / key 并显式选择
``note_source = "llm"`` 时才会走到这里。本项目不内置、也不代管任何 key。

失败一律返回 ``None``，由 :class:`~core.notes.generator.NoteGenerator`
回落到本地模板——批注是锦上添花，绝不能因为它把评分流程搞挂。

配置项::

    note_llm_base_url  如 https://api.example.com/v1（不带 /chat/completions）
    note_llm_model     模型名
    note_llm_key       API key（建议放 keyring，写入 setting.json 也可）
    note_llm_timeout   秒，默认 20
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

#: 提示词：三段式骨架 + 明确禁止编造听觉细节（模型同样没有听过这首歌）。
def _system_prompt(max_chars: int) -> str:
    """按设置里的字数上限生成提示词：上限是 120，就让模型写到 72–120 字。"""
    upper = max(20, int(max_chars))
    lower = max(12, int(upper * 0.6))
    return (
        "你在替用户给网易云音乐「音乐合伙人」的作品写一句中文短评，"
        "这句话会公开显示在用户账号下。要求："
        f"1) {lower}~{upper} 个汉字，一到三句；"
        "2) 你并没有听过这首歌，禁止描述具体的旋律、编曲、乐器、段落实排，"
        "只允许谈听歌场景、整体完成度的判断和处置方式；"
        "3) 不用感叹号堆砌，不用 emoji，不用话题标签，不写「强烈推荐」这类刷屏语；"
        "4) 语气克制、像唱片内页上的一句手写批注；"
        "5) 只输出这句话本身，不要加引号、不要解释。"
    )


def _get(config: Optional[Any], key: str, default: Any = None) -> Any:
    if config is None:
        return default
    try:
        return config.get(key, default)
    except Exception:
        return default


def _api_key(config: Optional[Any]) -> str:
    """取 key：优先 keyring，其次配置项。都取不到就返回空。"""
    try:
        import keyring
        value = keyring.get_password("ncmp desktop", "note_llm_key")
        if value:
            return str(value)
    except Exception:
        pass
    return str(_get(config, "note_llm_key", "") or "")


def generate_with_llm(work: Dict[str, Any], score: str,
                      config: Optional[Any] = None) -> Optional[str]:
    """调 LLM 生成一句批注；任何失败都返回 ``None``（调用方回落模板）。"""
    base_url = str(_get(config, "note_llm_base_url", "") or "").strip().rstrip("/")
    model = str(_get(config, "note_llm_model", "") or "").strip()
    key = _api_key(config)
    if not (base_url and model and key):
        return None
    try:
        timeout = float(_get(config, "note_llm_timeout", 20) or 20)
    except (TypeError, ValueError):
        timeout = 20.0

    user_prompt = (
        f"歌名：{work.get('name', '')}\n"
        f"歌手：{work.get('authorName', '')}\n"
        f"我给这首作品的评分：{score} 分（满分 5 分）"
    )
    try:
        max_chars = int(_get(config, "note_max_chars", 80) or 80)
    except (TypeError, ValueError):
        max_chars = 80
    max_chars = max(10, min(200, max_chars))
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_prompt(max_chars)},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,
        # 中文按 ~2.5 token/字估算，留足余量
        "max_tokens": max(200, max_chars * 4),
    }
    try:
        import requests

        response = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=timeout,
        )
        if response.status_code != 200:
            return None
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        text = str(content or "").strip().strip('"“”')
        return text or None
    except Exception:
        return None
