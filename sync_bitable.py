#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从飞书多维表格读取日报数据，写出 data.json（供 HTML 自动加载）。

环境变量:
  FEISHU_APP_ID        飞书应用 App ID
  FEISHU_APP_SECRET    飞书应用 App Secret
  BITABLE_APP_TOKEN    多维表格 app_token（默认 RoylbRWOxagG31snQJQcJ2LLnke）
  TABLE_LOGISTICS      物流揽收 table_id（可选，默认见下）
  TABLE_BALANCE        账户余额 table_id
  TABLE_RENT           仓租情况 table_id
  OUTPUT_PATH          输出路径，默认 data.json

仅用标准库 + 可选 requests；GitHub Actions 会安装 requests。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
FEISHU_BASE = "https://open.feishu.cn/open-apis"

# 当前多维表格（如迁移请改环境变量）
DEFAULT_APP_TOKEN = "RoylbRWOxagG31snQJQcJ2LLnke"
DEFAULT_TABLE_LOGISTICS = "tblTfMs76msYz4EH"
DEFAULT_TABLE_BALANCE = "tblpk4sKhj6we5Uo"
DEFAULT_TABLE_RENT = "tblY2xtlPGsSDk5t"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def http_json(method: str, url: str, payload=None, token: str | None = None):
    data = None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {url}: {detail}") from e
    if body.get("code") not in (0, None):
        raise RuntimeError(f"Feishu error code={body.get('code')} msg={body.get('msg')} url={url}")
    return body


def get_tenant_token(app_id: str, app_secret: str) -> str:
    body = http_json(
        "POST",
        f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
        {"app_id": app_id, "app_secret": app_secret},
    )
    token = body.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"No tenant_access_token: {body}")
    return token


def list_records(token: str, app_token: str, table_id: str) -> list[dict]:
    """分页拉取全部记录。"""
    items: list[dict] = []
    page_token = ""
    while True:
        url = (
            f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
            f"?page_size=100"
        )
        if page_token:
            url += f"&page_token={page_token}"
        body = http_json("GET", url, token=token)
        data = body.get("data") or {}
        items.extend(data.get("items") or [])
        if not data.get("has_more"):
            break
        page_token = data.get("page_token") or ""
        if not page_token:
            break
    return items


def field_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        # rich text: [{"text": "...", "type": "text"}]
        parts = []
        for x in v:
            if isinstance(x, dict):
                parts.append(x.get("text") or x.get("name") or "")
            else:
                parts.append(str(x))
        return "".join(parts).strip()
    if isinstance(v, dict):
        return (v.get("text") or "").strip()
    return str(v).strip()


def field_num(v) -> float:
    if v is None or v == "":
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, list) and v:
        return field_num(v[0])
    if isinstance(v, dict):
        return field_num(v.get("value"))
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return 0


def parse_date_short(v) -> str:
    """返回 MM.DD，用于物流行日期。"""
    if v is None or v == "":
        return ""
    if isinstance(v, (int, float)):
        # ms timestamp
        ms = int(v)
        if ms > 10**12:
            ms = ms // 1000
        dt = datetime.fromtimestamp(ms, tz=TZ)
        return f"{dt.month:02d}.{dt.day:02d}"
    if isinstance(v, str):
        s = v.strip()
        # 2026-11-24
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            try:
                dt = datetime.strptime(s[:10], "%Y-%m-%d")
                return f"{dt.month:02d}.{dt.day:02d}"
            except ValueError:
                pass
        # 11.24 / 11/24
        s2 = s.replace("/", ".")
        if "." in s2:
            return s2
        return s
    return str(v)


def parse_date_iso(v) -> str:
    """返回 YYYY-MM-DD。"""
    if v is None or v == "":
        return ""
    if isinstance(v, (int, float)):
        ms = int(v)
        if ms > 10**12:
            ms = ms // 1000
        return datetime.fromtimestamp(ms, tz=TZ).strftime("%Y-%m-%d")
    if isinstance(v, str):
        s = v.strip()
        if len(s) >= 10 and s[4] == "-":
            return s[:10]
        # MM.DD → 当年
        if "." in s:
            try:
                mm, dd = s.split(".")[:2]
                year = datetime.now(tz=TZ).year
                return f"{year}-{int(mm):02d}-{int(dd):02d}"
            except ValueError:
                return s
        return s
    return str(v)


def short_from_iso(iso: str) -> str:
    if not iso or len(iso) < 10:
        return iso
    p = iso.split("-")
    return f"{p[1]}.{p[2]}"


WINDOW_DAYS = 7


def short_to_date(short: str, year: int) -> datetime | None:
    try:
        m, d = short.split(".")
        return datetime(year, int(m), int(d), tzinfo=TZ)
    except Exception:
        return None


def iso_to_date(iso: str) -> datetime | None:
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").replace(tzinfo=TZ)
    except Exception:
        return None


def last_n_days(items: list, date_getter, n: int = WINDOW_DAYS, year: int | None = None) -> list:
    """只保留最近 n 天（含端点）。date_getter 返回 datetime 或 None。"""
    if not items:
        return []
    parsed = []
    for it in items:
        dt = date_getter(it)
        if dt is not None:
            parsed.append((dt, it))
    if not parsed:
        return list(items)
    max_dt = max(p[0] for p in parsed)
    if year is None:
        year = max_dt.year
    cutoff = datetime(max_dt.year, max_dt.month, max_dt.day, tzinfo=TZ) - timedelta(days=n - 1)
    out = [it for dt, it in parsed if dt >= cutoff]
    # 保持原相对顺序：按日期升序
    out.sort(key=lambda it: date_getter(it) or cutoff)
    return out


def build_db(logistics, balances, rents, app_token: str) -> dict:
    # --- logistics days ---
    days = []
    for rec in logistics:
        f = rec.get("fields") or {}
        total = int(field_num(f.get("运单总数")))
        tracked = int(field_num(f.get("有轨迹")))
        untracked = int(field_num(f.get("未轨迹")))
        draft = int(field_num(f.get("草稿待提交")))
        canceled = int(field_num(f.get("已取消")))
        # 校验：若总数与分项和不一致，以分项和为准（防手滑）
        s = tracked + untracked + draft + canceled
        if total <= 0:
            total = s
        date_s = parse_date_short(f.get("日期"))
        if not date_s:
            continue
        days.append(
            {
                "date": date_s,
                "total": total,
                "tracked": tracked,
                "untracked": untracked,
                "draft": draft,
                "canceled": canceled,
            }
        )
    # sort by MM.DD within same year window (string ok for same year)
    def day_key(d):
        try:
            m, dd = d["date"].split(".")
            return (int(m), int(dd))
        except Exception:
            return (0, 0)

    days.sort(key=day_key)

    # 7 天窗口：只保留最近 7 天物流
    year_guess = datetime.now(tz=TZ).year
    days = last_n_days(
        days,
        lambda d: short_to_date(d.get("date") or "", year_guess),
        n=WINDOW_DAYS,
    )

    # --- balance ---
    snapshots = []  # (iso, amount, currency, note, needRecharge)
    deductions = []
    for rec in balances:
        f = rec.get("fields") or {}
        typ = field_text(f.get("类型"))
        amount = field_num(f.get("金额"))
        iso = parse_date_iso(f.get("日期"))
        cur = field_text(f.get("货币")) or "MXN"
        note = field_text(f.get("备注"))
        need = bool(f.get("需要充值"))
        if "扣费" in typ or (typ == "" and amount):
            # type 出库扣费
            if "扣费" in typ or typ == "出库扣费":
                deductions.append({"date": short_from_iso(iso) or parse_date_short(f.get("日期")), "amount": amount})
            elif "余额" in typ or typ == "余额快照":
                snapshots.append((iso, amount, cur, note, need))
            else:
                # fallback by name
                if "快照" in typ or "余额" in typ:
                    snapshots.append((iso, amount, cur, note, need))
                else:
                    deductions.append({"date": short_from_iso(iso), "amount": amount})
        elif "余额" in typ or typ == "余额快照":
            snapshots.append((iso, amount, cur, note, need))
        elif "扣费" in typ:
            deductions.append({"date": short_from_iso(iso) or parse_date_short(f.get("日期")), "amount": amount})
        else:
            # unknown: if 需要充值 or looks like balance snapshot default
            if need or "快照" in typ:
                snapshots.append((iso, amount, cur, note, need))
            else:
                deductions.append({"date": short_from_iso(iso), "amount": amount})

    # re-classify more carefully
    snapshots = []
    deductions = []
    for rec in balances:
        f = rec.get("fields") or {}
        typ = field_text(f.get("类型"))
        amount = field_num(f.get("金额"))
        iso = parse_date_iso(f.get("日期"))
        short = short_from_iso(iso) if iso else parse_date_short(f.get("日期"))
        cur = field_text(f.get("货币")) or "MXN"
        note = field_text(f.get("备注"))
        need = bool(f.get("需要充值"))
        if "扣费" in typ:
            deductions.append({"date": short, "amount": amount})
        else:
            # 余额快照 / empty type with amount treated as snapshot if 备注 or default
            if typ == "" and not note and not need:
                # ambiguous: prefer snapshot only if no 出库 keyword
                snapshots.append((iso, amount, cur, note, need))
            else:
                snapshots.append((iso, amount, cur, note, need))

    # Fix: 出库扣费 already handled. For empty type rows that are deductions - check amount patterns
    # Re-read: user table uses 类型 SingleSelect 余额快照/出库扣费 - good.

    snapshots.sort(key=lambda x: x[0] or "")
    deductions.sort(key=lambda x: (x.get("date") or ""))

    # 扣费也只保留最近 7 天（锚点：物流最新日 或 扣费最新日）
    anchor_short = days[-1]["date"] if days else (deductions[-1]["date"] if deductions else "")
    if anchor_short:
        year_a = datetime.now(tz=TZ).year
        anchor_dt = short_to_date(anchor_short, year_a)
        if anchor_dt:
            cut = datetime(anchor_dt.year, anchor_dt.month, anchor_dt.day, tzinfo=TZ) - timedelta(
                days=WINDOW_DAYS - 1
            )
            deductions = [
                x
                for x in deductions
                if (short_to_date(x.get("date") or "", year_a) or cut) >= cut
            ]

    if snapshots:
        latest = snapshots[-1]
        balance_current = latest[1]
        currency = latest[2] or "MXN"
        note = latest[3] or ("余额充足" if balance_current > 0 else "请关注余额")
        need_recharge = latest[4]
    else:
        balance_current = 0
        currency = "MXN"
        note = "暂无余额快照"
        need_recharge = True

    # dedupe deductions by (date, amount)
    seen = set()
    uniq_ded = []
    for d in deductions:
        key = (d["date"], d["amount"])
        if key in seen:
            continue
        seen.add(key)
        uniq_ded.append(d)
    deductions = uniq_ded

    balance = {
        "currency": currency,
        "current": balance_current,
        "needRecharge": need_recharge,
        "note": note,
        "deductions": deductions,
    }

    # --- rent: prefer 是否当前有效=true ---
    rent = {
        "startDate": "",
        "planLabel": "仓租",
        "totalCost": 0,
        "status": "pending",
        "statusText": "",
        "timeline": [],
    }
    rent_rows = []
    for rec in rents:
        f = rec.get("fields") or {}
        if not f:
            continue
        rent_rows.append(f)

    def rent_iso(f):
        return parse_date_iso(f.get("更新日期"))

    active = None
    for f in rent_rows:
        if f.get("是否当前有效") is True or f.get("是否当前有效") == True:
            active = f
            break
    if active is None and rent_rows:
        rent_rows_sorted = sorted(rent_rows, key=rent_iso)
        active = rent_rows_sorted[-1]

    if active:
        days_free = int(field_num(active.get("免租方案天数")))
        total_cost = field_num(active.get("合计仓租"))
        status_cn = field_text(active.get("状态"))
        status_map = {"谈判中": "negotiating", "已谈妥": "done", "待启动": "pending"}
        status = status_map.get(status_cn, "pending")
        start = field_text(active.get("起租日"))
        progress = field_text(active.get("进展说明"))
        rent = {
            "startDate": start,
            "planLabel": f"{days_free}天免租方案 · 合计仓租" if days_free else "合计仓租",
            "totalCost": total_cost,
            "status": status,
            "statusText": progress or status_cn,
            "timeline": [
                {"text": f"起租日 {start}" if start else "起租日待填", "active": False},
                {"text": f"免租方案 {days_free} 天" if days_free else "免租天数待填", "active": False},
                {"text": progress or status_cn or "进行中", "active": True},
            ],
        }

    # --- history: 当日运单量 = 物流表该日「运单总数」，不做跨日累加 ---
    history = []
    for d in days:
        short = d["date"]
        # spent: 截至该日的扣费累计（仅扣费列，不影响运单）
        spent = sum(x["amount"] for x in deductions if x["date"] and x["date"] <= short)
        # balance: 截至该日最近一次快照
        bal = balance_current
        for iso, amt, cur, note, need in snapshots:
            s = short_from_iso(iso) if iso else ""
            if s and s <= short:
                bal = amt
        try:
            mm, dd = short.split(".")
            iso_d = f"{datetime.now(tz=TZ).year}-{int(mm):02d}-{int(dd):02d}"
        except Exception:
            iso_d = short
        history.append(
            {
                "date": iso_d,
                # 与多维表【运单总数】一致：仅当天，不累计
                "total": d["total"],
                "tracked": d["tracked"],
                "untracked": d["untracked"],
                "draft": d["draft"],
                "canceled": d["canceled"],
                "balance": bal,
                "spent": int(spent) if abs(spent - int(spent)) < 1e-6 else spent,
            }
        )
    history.reverse()
    # 历史日报只保留最近 7 天
    history = history[:WINDOW_DAYS]

    report_date = history[0]["date"] if history else datetime.now(tz=TZ).strftime("%Y-%m-%d")

    return {
        "title": "万国一件代发",
        "current": {
            "reportDate": report_date,
            "days": days,
            "balance": balance,
            "rent": rent,
        },
        "history": history,
        "_meta": {
            "source": "feishu_bitable_auto",
            "app_token": app_token,
            "synced_at": datetime.now(tz=TZ).strftime("%Y-%m-%d %H:%M:%S%z"),
            "days_count": len(days),
            "deduction_count": len(deductions),
        },
    }


def main() -> int:
    app_id = env("FEISHU_APP_ID")
    app_secret = env("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        print("ERROR: set FEISHU_APP_ID and FEISHU_APP_SECRET", file=sys.stderr)
        return 2

    app_token = env("BITABLE_APP_TOKEN", DEFAULT_APP_TOKEN)
    t_log = env("TABLE_LOGISTICS", DEFAULT_TABLE_LOGISTICS)
    t_bal = env("TABLE_BALANCE", DEFAULT_TABLE_BALANCE)
    t_rent = env("TABLE_RENT", DEFAULT_TABLE_RENT)
    out = Path(env("OUTPUT_PATH", "data.json"))

    print(f"App token: {app_token}")
    token = get_tenant_token(app_id, app_secret)
    print("Got tenant_access_token")

    logistics = list_records(token, app_token, t_log)
    balances = list_records(token, app_token, t_bal)
    rents = list_records(token, app_token, t_rent)
    print(f"Records: logistics={len(logistics)} balance={len(balances)} rent={len(rents)}")

    if not logistics:
        print("WARN: logistics table empty", file=sys.stderr)

    db = build_db(logistics, balances, rents, app_token)
    out.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out.resolve()}")
    cur = db["current"]
    print(
        f"reportDate={cur['reportDate']} days={len(cur['days'])} "
        f"balance={cur['balance']['current']} {cur['balance']['currency']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
