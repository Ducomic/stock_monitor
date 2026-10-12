"""Gotify 推送渠道测试。

网络全部通过 mock patch("app.notify.gotify.requests.post")，
配置使用本地 stub，不依赖 config.yaml 中是否存在 gotify 块。
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.notify.base import Notification, NotifyLevel
from app.notify.gotify import GotifyNotifier
from app.notify.manager import NotificationManager

SERVER_URL = "http://gotify.local:8080"
APP_TOKEN = "test-token"

SAMPLE_HTML = (
    '<div style="color: red; font-size: 14px;">'
    '<b>ETF 溢价套利</b>：510050&nbsp;溢价率 &gt; 2%<br>'
    "</div>"
    '<p>操作：申购套利，费率 0.5% &amp; T+2 赎回</p>'
)
SAMPLE_HTML_TEXT = (
    "ETF 溢价套利：510050 溢价率 > 2%\n\n"
    "操作：申购套利，费率 0.5% & T+2 赎回"
)


class StubConfig:
    """最小化 AppConfig 桩，仅提供 GotifyNotifier 所需属性。"""

    def __init__(self, gotify_cfg=None, rate_limit: int = 0):
        if gotify_cfg is None:
            gotify_cfg = {
                "server_url": SERVER_URL,
                "app_token": APP_TOKEN,
            }
        self.gotify_config = gotify_cfg
        self.notification_quiet_start = "00:00"
        self.notification_quiet_end = "23:59"
        self.notification_rate_limit = rate_limit


class ManagerStubConfig(StubConfig):
    """NotificationManager 所需的最小化配置桩。"""

    def __init__(self, gotify_enabled: bool = True):
        super().__init__()
        self.notification_enabled = True
        self.notification_quiet_enabled = False
        self.notification_quiet_start_hour = 23
        self.notification_quiet_end_hour = 7
        self.notification_min_interval_minutes = 10
        self.notification_held_interval_minutes = 10
        self.notification_watch_interval_minutes = 60
        self.notification_max_per_hour = 0
        self.notification_history_retention = 500
        self.wecom_enabled = False
        self.email_enabled = False
        self.gotify_enabled = gotify_enabled
        self._raw_notification = {
            "enabled": True,
            "channels": {
                "gotify": {
                    "enabled": gotify_enabled,
                    "name": "Gotify",
                    "server_url": SERVER_URL,
                    "app_token": APP_TOKEN,
                }
            },
        }


def make_notifier(gotify_cfg=None, rate_limit: int = 0) -> GotifyNotifier:
    return GotifyNotifier(StubConfig(gotify_cfg, rate_limit))


def mock_response(status_code: int = 200, json_data=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"id": 1} if json_data is None else json_data
    return resp


class TestSend:
    """发送流程测试。"""

    def test_send_success(self):
        """发送成功：HTTP 200 且响应含 id 返回 True，URL/payload 正确。"""
        notifier = make_notifier()
        with patch.object(GotifyNotifier, "is_quiet_time", return_value=False), \
                patch("app.notify.gotify.requests.post", return_value=mock_response()) as mock_post:
            ok = notifier.send(Notification("买入信号", "510050 溢价 2.1%", NotifyLevel.WARNING))

        assert ok is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == f"{SERVER_URL}/message?token={APP_TOKEN}"
        assert kwargs["timeout"] == 10
        assert kwargs["json"] == {
            "title": "买入信号",
            "message": "510050 溢价 2.1%",
            "priority": 5,
        }

    def test_send_trailing_slash_server_url(self):
        """server_url 带尾部斜杠时不应产生双斜杠。"""
        notifier = make_notifier({"server_url": f"{SERVER_URL}/", "app_token": APP_TOKEN})
        with patch.object(GotifyNotifier, "is_quiet_time", return_value=False), \
                patch("app.notify.gotify.requests.post", return_value=mock_response()) as mock_post:
            notifier.send(Notification("T", "C", NotifyLevel.WARNING))
        assert mock_post.call_args[0][0] == f"{SERVER_URL}/message?token={APP_TOKEN}"

    def test_http_non_200_returns_false(self):
        notifier = make_notifier()
        with patch.object(GotifyNotifier, "is_quiet_time", return_value=False), \
                patch("app.notify.gotify.requests.post",
                      return_value=mock_response(status_code=500)) as mock_post:
            assert notifier.send(Notification("T", "C", NotifyLevel.WARNING)) is False

    def test_response_missing_id_returns_false(self):
        """响应 JSON 无 id 字段视为失败。"""
        notifier = make_notifier()
        with patch.object(GotifyNotifier, "is_quiet_time", return_value=False), \
                patch("app.notify.gotify.requests.post",
                      return_value=mock_response(json_data={"token": "x"})):
            assert notifier.send(Notification("T", "C", NotifyLevel.WARNING)) is False

    def test_request_exception_returns_false(self):
        notifier = make_notifier()
        with patch.object(GotifyNotifier, "is_quiet_time", return_value=False), \
                patch("app.notify.gotify.requests.post",
                      side_effect=requests.exceptions.ConnectionError("boom")):
            assert notifier.send(Notification("T", "C", NotifyLevel.WARNING)) is False


class TestHtmlToText:
    """HTML 清洗测试。"""

    def test_typical_signal_html(self):
        """典型信号 HTML：块级标签转行、去标签、解码实体、无残留。"""
        text = make_notifier()._html_to_text(SAMPLE_HTML)
        assert text == SAMPLE_HTML_TEXT
        for residue in ("<div", "</div>", "<p", "<br", "<b", "&gt;", "&amp;", "&nbsp;"):
            assert residue not in text

    def test_extra_blank_lines_collapsed(self):
        """3 个以上连续空行压缩为 2 个（即一个空行）。"""
        text = make_notifier()._html_to_text("<p>a</p><div></div><div></div><div>b</div>")
        assert text == "a\n\nb"

    def test_plain_text_untouched(self):
        """纯文本内容原样保留（strip 后）。"""
        text = make_notifier()._html_to_text("  普通文本内容  ")
        assert text == "普通文本内容"

    def test_empty_content(self):
        assert make_notifier()._html_to_text("") == ""


class TestPriority:
    """优先级映射测试。"""

    @pytest.mark.parametrize("level,expected", [
        (NotifyLevel.INFO, 2),
        (NotifyLevel.WARNING, 5),
        (NotifyLevel.CRITICAL, 8),
    ])
    def test_level_mapping(self, level, expected):
        notifier = make_notifier()
        with patch.object(GotifyNotifier, "is_quiet_time", return_value=False), \
                patch("app.notify.gotify.requests.post", return_value=mock_response()) as mock_post:
            assert notifier.send(Notification("T", "C", level)) is True
        assert mock_post.call_args[1]["json"]["priority"] == expected

    def test_configured_priority_overrides_mapping(self):
        """配置了 priority 数值则覆盖级别映射。"""
        notifier = make_notifier({"server_url": SERVER_URL, "app_token": APP_TOKEN,
                                  "priority": 10})
        with patch.object(GotifyNotifier, "is_quiet_time", return_value=False), \
                patch("app.notify.gotify.requests.post", return_value=mock_response()) as mock_post:
            notifier.send(Notification("T", "C", NotifyLevel.INFO))
        assert mock_post.call_args[1]["json"]["priority"] == 10


class TestConfigMissing:
    """配置缺失测试。"""

    @pytest.mark.parametrize("gotify_cfg", [
        {"server_url": "", "app_token": APP_TOKEN},
        {"server_url": SERVER_URL, "app_token": ""},
        {"server_url": None, "app_token": None},
    ])
    def test_incomplete_config_returns_false(self, gotify_cfg):
        notifier = make_notifier(gotify_cfg)
        with patch.object(GotifyNotifier, "is_quiet_time", return_value=False), \
                patch("app.notify.gotify.requests.post") as mock_post:
            assert notifier.send(Notification("T", "C", NotifyLevel.WARNING)) is False
        mock_post.assert_not_called()


class TestQuietHours:
    """免打扰时段测试。"""

    def test_info_skipped_in_quiet_time(self):
        notifier = make_notifier()
        with patch.object(GotifyNotifier, "is_quiet_time", return_value=True), \
                patch("app.notify.gotify.requests.post") as mock_post:
            assert notifier.send(Notification("T", "C", NotifyLevel.INFO)) is False
        mock_post.assert_not_called()

    def test_warning_sent_in_quiet_time(self):
        notifier = make_notifier()
        with patch.object(GotifyNotifier, "is_quiet_time", return_value=True), \
                patch("app.notify.gotify.requests.post", return_value=mock_response()) as mock_post:
            assert notifier.send(Notification("T", "C", NotifyLevel.WARNING)) is True
        mock_post.assert_called_once()


class TestManagerIntegration:
    """NotificationManager 集成测试。"""

    def test_init_channels_registers_gotify(self):
        mgr = NotificationManager(ManagerStubConfig(gotify_enabled=True))
        assert "gotify" in mgr._channels
        assert isinstance(mgr._channels["gotify"], GotifyNotifier)

    def test_init_channels_skips_disabled_gotify(self):
        mgr = NotificationManager(ManagerStubConfig(gotify_enabled=False))
        assert "gotify" not in mgr._channels

    def test_channel_status_masks_app_token(self):
        """API 响应中不出现 app_token，server_url 保留展示。"""
        mgr = NotificationManager(ManagerStubConfig())
        status = mgr.get_channel_status()
        gotify_cfg = status["gotify"]["config"]
        assert "app_token" not in gotify_cfg
        assert gotify_cfg.get("server_url") == SERVER_URL

    def test_send_report_summary_skips_email(self):
        """摘要只发非 email 渠道，WARNING 级别，内容为纯文本。"""
        mgr = NotificationManager(ManagerStubConfig())
        email_m = MagicMock()
        email_m.send.return_value = True
        wecom_m = MagicMock()
        wecom_m.send.return_value = True
        gotify_m = MagicMock()
        gotify_m.send.return_value = True
        mgr._channels = {"email": email_m, "wecom_bot": wecom_m, "gotify": gotify_m}

        results = mgr.send_report_summary("每日报告摘要", "今日无新信号")

        assert set(results) == {"wecom_bot", "gotify"}
        assert results["wecom_bot"] is True
        assert results["gotify"] is True
        email_m.send.assert_not_called()
        for m in (wecom_m, gotify_m):
            notification = m.send.call_args[0][0]
            assert notification.level == NotifyLevel.WARNING
            assert notification.title == "每日报告摘要"
            assert notification.content == "今日无新信号"
