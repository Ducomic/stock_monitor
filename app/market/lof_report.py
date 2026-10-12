"""
LOF 溢价率报告生成器（HTML 邮件 + 纯文本推送摘要）。
"""
from datetime import datetime
import pandas as pd


def _fmt_amount(v) -> str:
    """成交额转可读格式（亿/万/元）。"""
    try:
        a = float(v or 0)
    except (TypeError, ValueError):
        return "-"
    if a != a:  # NaN
        return "-"
    if a >= 1e8:
        return f"{a / 1e8:.2f}亿"
    if a >= 1e4:
        return f"{a / 1e4:.0f}万"
    return f"{a:.0f}元"


def build_html_table(df) -> str:
    if df is None or df.empty:
        return "<p style='color:#999;text-align:center;padding:20px;'>暂无数据</p>"

    rows = ""
    for _, r in df.iterrows():
        pr = r.get("premium_rate")
        pr_str = f"{'+' if pr and pr > 0 else ''}{pr:.2f}%" if pr is not None else "-"
        pr_color = "#e53e3e" if (pr or 0) > 0 else ("#38a169" if (pr or 0) < 0 else "#999")
        nav = f"{float(r['nav']):.4f}" if r.get("nav") is not None else "-"
        status = r.get("subscribe_status", "-") or "-"
        rows += (
            f"<tr>"
            f"<td>{r.get('symbol','')}</td>"
            f"<td>{r.get('name','')}</td>"
            f"<td style='text-align:right'>{float(r.get('price',0)):.3f}</td>"
            f"<td style='text-align:right'>{nav}</td>"
            f"<td style='text-align:right;font-weight:600;color:{pr_color}'>{pr_str}</td>"
            f"<td style='text-align:center;font-size:11px;'>{status}</td>"
            f"</tr>"
        )

    return (
        f"<table style='width:100%;border-collapse:collapse;font-size:12px;'>"
        f"<thead><tr style='background:#f7fafc;color:#4a5568;'>"
        f"<th style='padding:6px 8px;text-align:left'>代码</th>"
        f"<th style='padding:6px 8px;text-align:left'>名称</th>"
        f"<th style='padding:6px 8px;text-align:right'>价格</th>"
        f"<th style='padding:6px 8px;text-align:right'>净值</th>"
        f"<th style='padding:6px 8px;text-align:right'>溢价率</th>"
        f"<th style='padding:6px 8px;text-align:center'>申赎</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def build_report(df, alerts: list | None = None, premium_threshold: float = 5.0) -> str:
    now = datetime.now().strftime("%m-%d %H:%M")
    total = len(df) if df is not None else 0

    if df is not None and not df.empty and "premium_rate" in df.columns:
        p = int((df["premium_rate"].fillna(0) >= premium_threshold).sum())
        d = int((df["premium_rate"].fillna(0) <= -3).sum())
    else:
        p = d = 0

    # Header stats bar
    stats = f"{total} 只 LOF · 溢价≥{premium_threshold}%: {p} · 折价≤-3%: {d}"

    # Alert card
    alert_html = ""
    if alerts:
        rows = ""
        for a in alerts[:6]:
            rows += (
                f"<tr style='border-bottom:1px solid #fef0c7'>"
                f"<td style='padding:3px 8px;font-family:monospace'>{a['symbol']}</td>"
                f"<td style='padding:3px 8px'>{a['name']}</td>"
                f"<td style='padding:3px 8px;text-align:right;font-weight:600;color:#d97706'>+{a['premium_rate']:.1f}%</td>"
                f"<td style='padding:3px 8px;text-align:right;color:#666'>{a.get('amount',0)/1e8:.2f}亿</td>"
                f"</tr>"
            )
        alert_html = (
            f"<div style='margin:0 0 12px;padding:8px 12px;background:#fffbeb;border-left:3px solid #f59e0b'>"
            f"<p style='margin:0 0 6px;font-size:13px;font-weight:600;color:#92400e'>套利预警 {len(alerts)} 只</p>"
            f"<table style='width:100%;border-collapse:collapse;font-size:12px'>"
            f"<tr style='color:#92400e;font-size:11px'><th style='text-align:left;padding:2px 8px'>代码</th><th style='text-align:left;padding:2px 8px'>名称</th><th style='text-align:right;padding:2px 8px'>溢价</th><th style='text-align:right;padding:2px 8px'>成交</th></tr>"
            f"{rows}</table></div>"
        )
    elif alerts is not None:
        alert_html = (
            f"<div style='margin:0 0 12px;padding:6px 12px;background:#f0fdf4;border-left:3px solid #22c55e;font-size:12px;color:#166534'>"
            f"当前无可套利标的</div>"
        )

    body = (
        f"<html><head><meta charset='utf-8'></head>"
        f"<body style='font-family:system-ui,sans-serif;margin:0;background:#f5f5f5'>"
        f"<div style='max-width:700px;margin:0 auto;background:#fff'>"

        # Filter note (replaces old stats line)
        f"<div style='padding:10px 20px;font-size:12px;color:#64748b;border-bottom:1px solid #e2e8f0'>过滤：价格>0 · 成交额≥1000万 · 申购开放 · 溢价>{premium_threshold}% </div>"

        # Alert
        f"<div style='padding:12px 20px 0'>{alert_html}</div>"

        # Table
        f"<div style='padding:8px 16px 16px'>"
        f"{build_html_table(df)}"
        f"</div>"


        f"</div></body></html>"
    )
    return body


def build_report_text(df, alerts: list | None = None,
                      threshold: float = 5.0, top_n: int = 5) -> str:
    """生成 LOF 日报纯文本摘要（供 Gotify 等移动端推送渠道，完整 HTML 仍走邮件）。

    输出示例::

        42 只 LOF · 溢价≥5%: 3 · 折价≤-3%: 1
        套利预警 2 只
        160105[南方LOF] +8.89% 成交1.25亿
        溢价 Top 4
        1. 160706 嘉实LOF +10.82%
    """
    empty = df is None or df.empty
    lines = []

    # 概览
    if empty:
        lines.append("暂无 LOF 数据")
    else:
        total = len(df)
        if "premium_rate" in df.columns:
            pr = pd.to_numeric(df["premium_rate"], errors="coerce").fillna(0)
            p = int((pr >= threshold).sum())
            d = int((pr <= -3).sum())
        else:
            p = d = 0
        lines.append(f"{total} 只 LOF · 溢价≥{threshold:g}%: {p} · 折价≤-3%: {d}")

    # 套利/预警清单
    if alerts is None:
        pass
    elif not alerts:
        lines.append("当前无可套利标的")
    else:
        lines.append(f"套利预警 {len(alerts)} 只")
        for a in alerts[:top_n]:
            if not isinstance(a, dict):
                continue
            sym, name = a.get("symbol", ""), a.get("name", "")
            pr = a.get("premium_rate")
            pr_s = f"{float(pr):+.2f}%" if pr is not None else "-"
            lines.append(f"{sym}[{name}] {pr_s} 成交{_fmt_amount(a.get('amount'))}")

    # 溢价 Top N
    if not empty and "premium_rate" in df.columns:
        top = df.copy()
        top["premium_rate"] = pd.to_numeric(top["premium_rate"], errors="coerce")
        top = top.dropna(subset=["premium_rate"]).nlargest(top_n, "premium_rate")
        if len(top):
            lines.append("")
            lines.append(f"溢价 Top {len(top)}")
            for i, (_, r) in enumerate(top.iterrows(), 1):
                lines.append(
                    f"{i}. {r.get('symbol', '')} {r.get('name', '')} {float(r['premium_rate']):+.2f}%"
                )

    return "\n".join(lines)
