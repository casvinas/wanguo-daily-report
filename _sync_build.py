# -*- coding: utf-8 -*-
import json
from pathlib import Path

base = Path(r"C:\Users\casvi\XiaomiMiMoProjects\.mimo-sessions\2026\11\23\11-23-1-20-23-145")

logistics = [
    {"date": "2026-11-20", "total": 10, "tracked": 10, "untracked": 0, "draft": 0, "canceled": 0},
    {"date": "2026-11-21", "total": 22, "tracked": 22, "untracked": 0, "draft": 0, "canceled": 0},
    {"date": "2026-11-22", "total": 55, "tracked": 54, "untracked": 0, "draft": 0, "canceled": 1},
    {"date": "2026-11-23", "total": 113, "tracked": 107, "untracked": 6, "draft": 0, "canceled": 0},
    {"date": "2026-11-24", "total": 14, "tracked": 0, "untracked": 14, "draft": 0, "canceled": 0},
]
for d in logistics:
    s = d["tracked"] + d["untracked"] + d["draft"] + d["canceled"]
    assert s == d["total"], (d, s)

deductions = [
    {"date": "11.19", "amount": 160},
    {"date": "11.20", "amount": 496},
    {"date": "11.21", "amount": 204},
    {"date": "11.22", "amount": 212},
    {"date": "11.23", "amount": 40},
    {"date": "11.24", "amount": 2618},
]
balance_current = 12726
currency = "MXN"
spent = sum(x["amount"] for x in deductions)
assert spent == 3730


def short(iso):
    p = iso.split("-")
    return "%s.%s" % (p[1], p[2])


days = []
for d in logistics:
    days.append({
        "date": short(d["date"]),
        "total": d["total"],
        "tracked": d["tracked"],
        "untracked": d["untracked"],
        "draft": d["draft"],
        "canceled": d["canceled"],
    })


def cum_spent(up_to_short):
    total = 0
    for x in deductions:
        if x["date"] <= up_to_short:
            total += x["amount"]
    return total


def cum_balance(up_to_short):
    if up_to_short >= "11.24":
        return 12726
    if up_to_short >= "11.23":
        return 4588
    return 4588


history = []
acc = {"total": 0, "tracked": 0, "untracked": 0, "draft": 0, "canceled": 0}
for d in logistics:
    acc = {
        "total": acc["total"] + d["total"],
        "tracked": acc["tracked"] + d["tracked"],
        "untracked": acc["untracked"] + d["untracked"],
        "draft": acc["draft"] + d["draft"],
        "canceled": acc["canceled"] + d["canceled"],
    }
    sd = short(d["date"])
    history.append({
        "date": d["date"],
        "total": acc["total"],
        "tracked": acc["tracked"],
        "untracked": acc["untracked"],
        "draft": acc["draft"],
        "canceled": acc["canceled"],
        "balance": cum_balance(sd),
        "spent": cum_spent(sd),
    })
history.reverse()

balance = {
    "currency": currency,
    "current": balance_current,
    "needRecharge": False,
    "note": "余额充足（11.24 快照，含仓租等扣费后）",
    "deductions": deductions,
}

rent = {
    "startDate": "11.26",
    "planLabel": "60天免租方案 · 合计仓租",
    "totalCost": 0,
    "status": "pending",
    "statusText": "已争取60天免租期，从11.26开始启动",
    "timeline": [
        {"text": "11.7 起租（原按45天免租测算合计4536.14）", "active": False},
        {"text": "已争取60天免租期", "active": False},
        {"text": "11.26 起按60天免租启动（合计仓租暂为0）", "active": True},
    ],
}

sync = {
    "reportDate": "2026-11-24",
    "days": days,
    "balance": balance,
    "rent": rent,
    "history": history,
    "_meta": {
        "source": "feishu_bitable",
        "app_token": "RoylbRWOxagG31snQJQcJ2LLnke",
        "synced_at": "2026-11-24",
        "tables": ["物流揽收", "账户余额", "仓租情况"],
        "note": "物流合计214单/有轨迹193/未轨迹20/取消1；扣费合计3730 MXN；当前余额12726 MXN；仓租60天方案11.26启动",
    },
}

st = sum(d["total"] for d in days)
tr = sum(d["tracked"] for d in days)
un = sum(d["untracked"] for d in days)
dr = sum(d["draft"] for d in days)
cn = sum(d["canceled"] for d in days)
assert tr + un + dr + cn == st

json_path = base / "同步结果-从多维表格.json"
json_path.write_text(json.dumps(sync, ensure_ascii=False, indent=2), encoding="utf-8")

db = {
    "title": "万国一件代发",
    "current": {
        "reportDate": sync["reportDate"],
        "days": days,
        "balance": balance,
        "rent": rent,
    },
    "history": history,
}

html_path = base / "万国一件代发日报.html"
html = html_path.read_text(encoding="utf-8")

key_line = 'const KEY = "wanguo_daily_report_v1";'
preload = "const KEY = \"wanguo_daily_report_v1\";\n  const __PRELOADED_DB__ = " + json.dumps(db, ensure_ascii=False) + ";"
if key_line not in html:
    raise SystemExit("KEY line not found")
html2 = html.replace(key_line, preload, 1)

old_load = """function load() {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) return JSON.parse(raw);
    } catch (e) {}
    return seed();
  }"""
new_load = """function load() {
    return __PRELOADED_DB__;
  }"""
if old_load not in html2:
    raise SystemExit("load() not found")
html2 = html2.replace(old_load, new_load, 1)

# Share version: ignore local localStorage so snapshot stays stable
html2 = html2.replace(
    "localStorage.setItem(KEY, JSON.stringify(db));",
    "/* share: no persist */",
    1,
)

# load() 已改为返回 __PRELOADED_DB__；seed 保持原样仅作兜底

share_path = base / "万国日报_2026-11-24_分享版.html"
share_path.write_text(html2, encoding="utf-8")

print("JSON", json_path)
print("SHARE", share_path)
print("STATS", st, tr, un, dr, cn, spent, balance_current)
print("days", len(days), "history", len(history))
print("json_bytes", json_path.stat().st_size)
print("share_bytes", share_path.stat().st_size)
t = share_path.read_text(encoding="utf-8")
print("preload", "__PRELOADED_DB__" in t, "12726" in t, "return __PRELOADED_DB__" in t)
