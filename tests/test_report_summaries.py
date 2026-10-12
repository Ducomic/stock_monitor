"""纯文本报告摘要生成器测试（收盘小结 / LOF 日报，用于 Gotify 等移动端推送）。"""

import pandas as pd

from app.market.lof_report import build_report_text
from app.scheduler.summary import build_closing_summary_text


def _pos(symbol="601398", cost=4.8, shares=1000, price=5.1,
         pnl=300.0, pnl_pct=6.3):
    return {
        "symbol": symbol, "cost": cost, "shares": shares, "price": price,
        "pnl": pnl, "pnl_pct": pnl_pct,
    }


class TestClosingSummaryText:

    def test_normal_positions_and_signals(self):
        positions = [
            _pos("601398", pnl=300.0, pnl_pct=6.3),
            _pos("510050", cost=2.9, shares=2000, price=2.8, pnl=-200.0, pnl_pct=-3.4),
        ]
        signals = [{"action": "buy"}, {"action": "buy"}, {"action": "sell"}]
        quotes = pd.DataFrame({
            "symbol": ["sh601398", "sh510050"],
            "name": ["工商银行", "上证50ETF"],
        })
        text = build_closing_summary_text(positions, signals, quotes)

        assert "持仓 2 只" in text
        # 总盈亏 = 300 - 200 = +100；总成本 = 4800 + 5800 = 10600 → +0.9%
        assert "总盈亏 +100.00 (+0.9%)" in text
        assert "601398[工商银行]" in text
        assert "510050[上证50ETF]" in text
        assert "成本4.80" in text and "现价5.10" in text
        assert "+6.3%" in text and "(+300.00)" in text
        assert "-3.4%" in text and "(-200.00)" in text
        assert "今日信号 2买 1卖" in text
        # 纯文本，不含 HTML 标签
        assert "<" not in text
        assert len(text.splitlines()) <= 10

    def test_no_positions(self):
        text = build_closing_summary_text([], [])
        assert "无持仓" in text
        assert "今日信号" not in text
        assert "<" not in text

    def test_none_inputs(self):
        text = build_closing_summary_text(None, None)
        assert "无持仓" in text

    def test_positions_without_signals(self):
        text = build_closing_summary_text([_pos()], [])
        assert "持仓 1 只" in text
        assert "今日信号" not in text

    def test_zero_cost_skips_percent(self):
        text = build_closing_summary_text(
            [_pos(cost=0.0, shares=0, pnl=12.0, pnl_pct=0.0)], [])
        header = text.splitlines()[0]
        assert "总盈亏 +12.00" in header
        assert "%" not in header  # 成本为 0 时跳过百分比

    def test_missing_fields_defensive(self):
        text = build_closing_summary_text([{"symbol": "601398"}], [{"action": "buy"}])
        assert "601398" in text
        assert "今日信号 1买 0卖" in text

    def test_many_positions_capped(self):
        positions = [_pos(f"60000{i}") for i in range(9)]
        text = build_closing_summary_text(positions, [{"action": "buy"}])
        assert "持仓 9 只" in text
        assert "...另有 3 只" in text
        assert len(text.splitlines()) <= 10


def _lof_df():
    return pd.DataFrame({
        "symbol": ["160105", "160706", "161005", "160505"],
        "name": ["南方LOF", "嘉实LOF", "富国LOF", "博时LOF"],
        "price": [1.25, 2.10, 0.95, 1.08],
        "nav": [1.148, 1.895, 0.998, 1.095],
        "premium_rate": [8.89, 10.82, -4.81, -1.37],
        "amount": [1.25e8, 6.8e7, 5.4e6, 2.0e7],
    })


def _lof_alerts():
    return [
        {"symbol": "160706", "name": "嘉实LOF", "premium_rate": 10.82,
         "amount": 6.8e7, "direction": "premium"},
        {"symbol": "160105", "name": "南方LOF", "premium_rate": 8.89,
         "amount": 1.25e8, "direction": "premium"},
    ]


class TestLOFReportText:

    def test_overview_alerts_and_top(self):
        text = build_report_text(_lof_df(), _lof_alerts(), 5.0)
        # 概览
        assert "4 只 LOF · 溢价≥5%: 2 · 折价≤-3%: 1" in text
        # 预警清单（含代码/名称/溢价率/成交额，亿/万可读格式）
        assert "套利预警 2 只" in text
        assert "160706[嘉实LOF] +10.82%" in text
        assert "6800万" in text
        assert "160105[南方LOF] +8.89%" in text
        assert "1.25亿" in text
        # 溢价 Top（按溢价率降序）
        assert "溢价 Top 4" in text
        assert "1. 160706 嘉实LOF +10.82%" in text
        assert "2. 160105 南方LOF +8.89%" in text
        # 纯文本，不含 HTML 标签
        assert "<" not in text

    def test_empty_df(self):
        text = build_report_text(pd.DataFrame(), [], 5.0)
        assert "暂无" in text
        assert "无可套利" in text
        assert "<" not in text

    def test_df_none(self):
        text = build_report_text(None, None, 5.0)
        assert "暂无" in text

    def test_empty_alerts(self):
        text = build_report_text(_lof_df(), [], 5.0)
        assert "当前无可套利标的" in text
        assert "套利预警" not in text
        assert "溢价 Top 4" in text

    def test_alerts_none_omits_section(self):
        text = build_report_text(_lof_df(), None, 5.0, top_n=2)
        assert "套利预警" not in text
        assert "无可套利" not in text
        # top_n 限制
        assert "溢价 Top 2" in text
        assert "1. 160706" in text
        assert "2. 160105" in text
        assert "3.16" not in text

    def test_alerts_truncated_to_top_n(self):
        alerts = _lof_alerts() + [
            {"symbol": "161005", "name": "富国LOF", "premium_rate": -4.81,
             "amount": 5.4e6, "direction": "discount"},
        ]
        text = build_report_text(_lof_df(), alerts, 5.0, top_n=2)
        assert "套利预警 3 只" in text
        assert "161005" not in text  # 超出 top_n 的预警不展示
