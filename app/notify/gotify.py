"""
Gotify 自托管推送渠道。

通过 Gotify 服务器的 message API 发送通知。
Gotify 为自托管服务，server_url 可能是 http，不做 TLS 特殊处理。
文档：https://gotify.net/docs/msgapi
"""

import html
import logging
import re

import requests

from app.notify.base import BaseNotifier, Notification, NotifyLevel

logger = logging.getLogger(__name__)

# 块级标签转换为换行，避免行内容粘连
_BLOCK_TAG_RE = re.compile(
    r"</?(?:p|div|li|ul|ol|dl|tr|td|th|h[1-6]|section|article|blockquote)\b[^>]*>"
    r"|<br\s*/?>",
    re.IGNORECASE,
)
# style/script 元素连同内容整体删除（属性式 style 由去标签正则处理）
_STYLE_SCRIPT_RE = re.compile(
    r"<(style|script)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
# 剩余所有标签
_TAG_RE = re.compile(r"<[^>]+>")


class GotifyNotifier(BaseNotifier):
    """Gotify 自托管消息推送。

    Usage:
        notifier = GotifyNotifier(config)
        notifier.send(Notification("标题", "内容", NotifyLevel.WARNING))
    """

    # 级别 -> Gotify priority 固定映射
    _LEVEL_PRIORITY = {
        NotifyLevel.INFO: 2,
        NotifyLevel.WARNING: 5,
        NotifyLevel.CRITICAL: 8,
    }

    def __init__(self, config):
        super().__init__(config)
        gotify_cfg = config.gotify_config or {}
        self._server_url = str(gotify_cfg.get("server_url") or "").strip()
        self._app_token = str(gotify_cfg.get("app_token") or "").strip()
        priority = gotify_cfg.get("priority")
        try:
            self._configured_priority = int(priority) if priority is not None else None
        except (TypeError, ValueError):
            self._configured_priority = None

    def send(self, notification: Notification) -> bool:
        """通过 Gotify message API 发送通知。

        如果处于免打扰时段，info 级别消息将跳过。
        """
        if notification.level == NotifyLevel.INFO and self.is_quiet_time():
            logger.debug("免打扰时段，跳过 Gotify 通知")
            return False

        if not self.check_rate_limit():
            logger.warning("推送频率超限，消息被丢弃")
            return False

        if not self._server_url or not self._app_token:
            logger.warning("Gotify 配置不完整（缺少 server_url 或 app_token）")
            return False

        payload = {
            "title": notification.title,
            "message": self._html_to_text(notification.content),
            "priority": self._resolve_priority(notification.level),
        }

        url = f"{self._server_url.rstrip('/')}/message?token={self._app_token}"
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200:
                logger.error(f"Gotify 推送失败: HTTP {resp.status_code}")
                return False
            result = resp.json()
            if "id" not in result:
                logger.error(f"Gotify 推送失败: 响应缺少 id 字段: {result}")
                return False
            logger.info(f"Gotify 推送成功: {notification.title}")
            return True
        except Exception as e:
            # requests 异常消息可能携带完整 URL（含 token），必须脱敏后再入日志
            detail = str(e).replace(self._app_token, "****") if self._app_token else str(e)
            logger.error(f"Gotify 推送异常: {type(e).__name__}: {detail}")
            return False

    def _resolve_priority(self, level: NotifyLevel) -> int:
        """解析消息优先级：配置了 priority 数值则覆盖级别映射。"""
        if self._configured_priority is not None:
            return self._configured_priority
        return self._LEVEL_PRIORITY.get(level, 2)

    def _html_to_text(self, raw: str) -> str:
        """将 HTML 片段清洗为 Gotify 可展示的纯文本。

        块级标签转换行、去除全部标签、解码 HTML 实体、
        压缩 3 个以上连续空行为 2 个。
        """
        if not raw:
            return ""
        text = _STYLE_SCRIPT_RE.sub("", raw)
        text = _BLOCK_TAG_RE.sub("\n", text)
        text = _TAG_RE.sub("", text)
        text = html.unescape(text)
        text = text.replace("\xa0", " ")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
