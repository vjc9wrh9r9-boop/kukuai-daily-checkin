#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""库库AI 每日签到 / 每日任务自动化（无头 · Cookie 注入）· 2026Q4 期。

适配活动：「每日签到得网盘SVIP月卡 · 做任务抽好礼 赢苹果笔记本」
活动周期：2026-10-21 ~ 2026-12-04（连签 30 天必得网盘SVIP月卡）

════════════════════════════════════════════════════════════════════
v4 关键变更（2026-10-28）
────────────────────────────────────────────────────────────────────
1. 任务进度有两个独立渠道，以前只做了网页端，PC 客户端里仍是 0/3：
       task_from=kuku_signin_30_web  → 网页端（6 张卡）
       task_from=kuku_signin_30_pc   → PC 客户端（7 张卡，多「导入网盘/上传本地」）
   签到是账号级、各端同步；每日任务进度不互通。本版两个渠道都做、都核验。

2. 一切以官方接口为准，不看脚本自述：
       GET  /api/taskscore/tasklist?task_from=<渠道>
            → task_finish_count / task_count_max（真实进度）
       POST /api/genflowpro/activity/taskcomplete?jsToken=...
            → 上报任务事件（errno=0 才算成功）
   动作做完 → 上报 → 重新拉接口核验；没到 max 就如实报「未达成」。

3. 真实动作，不是空转：
   聊天页真发消息、知识广场真停留、专家真召唤、网盘真上传占位文件。

用法:
    python kukuai_checkin.py --cookies ~/.kukuai/cookies.json
    python kukuai_checkin.py --cookies ~/.kukuai/cookies.json --dry-run
    python kukuai_checkin.py --cookies ~/.kukuai/cookies.json --only-signin
    python kukuai_checkin.py --cookies ~/.kukuai/cookies.json --with-expert
    python kukuai_checkin.py --cookies ~/.kukuai/cookies.json --channels web

Cookie 支持三种格式（自动识别）:
    1) Playwright/Puppeteer 导出的 JSON 数组: [{"name":"BDUSS","value":"...","domain":".kukuai.cn"}]
    2) {"cookies": [...]} 或 {"name": "value", ...} 映射
    3) 原始 Cookie 头字符串: "BDUSS=xxx; STOKEN=yyy"

注意:
    - 遇到验证码 / 滑块 / 风控会立即中止并如实报告，不尝试绕过。
    - 进度日志只写文件（<out>/log/），stdout 仅输出最终 JSON 结果。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, parse_qs

HOME_URL = "https://kuku.baidu.com/app"
# 两个前端入口，同一账号、两套 cookie 域：
#   kuku.baidu.com  ← BDUSS@.baidu.com + STOKEN@.kuku.baidu.com
#   www.kukuai.cn   ← BDUSS@.kukuai.cn  + STOKEN@.passport.kukuai.cn 等
# 跑之前先探测哪个域名认这份 cookie，再决定后续所有请求打哪个域。
CANDIDATE_HOSTS = ["https://kuku.baidu.com", "https://www.kukuai.cn"]
ACTIVITY_PATH = "/operation/activitys/kukuPcSignAct/main"
CN_TZ = timezone(timedelta(hours=8))

SKILL_ROOT = Path(__file__).resolve().parent.parent
ACTIVITY_FILE = SKILL_ROOT / "assets" / "activity.json"

DEFAULT_COOKIE_PATHS = [
    "~/.kukuai/cookies.json",
    "~/.kukuai/cookies.txt",
    "uploads/kukuai_cookies.json",
]
DEFAULT_STATE_PATH = "~/.kukuai/state.json"
# 用户同意过《库库AI用户协议》就记一笔，之后每天自动跑不用再带 --with-expert
CONSENT_PATH = "~/.kukuai/consent.json"

RISK_KEYWORDS = [
    "验证码", "拖动滑块", "滑块验证", "安全验证", "人机验证",
    "请完成验证", "异常访问", "操作过于频繁", "风险提示", "环境异常",
]
SUCCESS_KEYWORDS = ["签到成功", "领取成功", "已领取", "积分+10", "签到完成",
                    "已签到", "今日已签", "明天再来", "明日再来", "已签"]

# 热门话题任务要发 3 条，多准备几条避免重复
CHAT_PROMPTS = [
    "最近有哪些值得关注的 AI 行业热门话题？简单说三条就好。",
    "帮我推荐三个适合秋天去的国内旅行目的地，各一句话理由。",
    "用三句话总结一下今年办公类 AI 工具的主要变化。",
    "周末想在家做一顿简单的饭，给个 30 分钟能搞定的菜单。",
    "怎么提高远程会议的效率？给三条可执行的建议。",
]
EXPERT_PROMPT = "帮我用一句话给这个方向列一个三条的待办清单。"


# --------------------------------------------------------------------------- #
# 活动配置
# --------------------------------------------------------------------------- #
def load_activity(path: Path = ACTIVITY_FILE) -> dict:
    if not path.exists():
        raise FileNotFoundError("活动配置缺失: %s" % path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def today_cn():
    return datetime.now(CN_TZ).date()


def parse_iso_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


def activity_meta(act: dict) -> dict:
    start = parse_iso_date(act["start"])
    end = parse_iso_date(act["end"])
    today = today_cn()
    days_left = (end - today).days
    if today < start:
        phase = "not-started"
    elif today > end:
        phase = "ended"
    else:
        phase = "running"
    return {
        "id": act.get("id"),
        "name": act.get("name"),
        "period": "%s ~ %s" % (act["start"], act["end"]),
        "phase": phase,
        "days_left": days_left,
        "running_days": (today - start).days + 1 if phase != "not-started" else 0,
    }


def next_node(act: dict, streak):
    if streak is None:
        return None
    for n in sorted(act.get("nodes", []), key=lambda x: x["day"]):
        if streak < n["day"]:
            return {"day": n["day"], "reward": n.get("reward"), "need": n["day"] - streak}
    return None


# --------------------------------------------------------------------------- #
# Cookie
# --------------------------------------------------------------------------- #
def load_cookies(path: Path):
    """把多种格式的 Cookie 文件统一成 Playwright add_cookies 可用的列表。"""
    text = path.read_text(encoding="utf-8").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    raw = []
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        if isinstance(data.get("cookies"), list):
            raw = data["cookies"]
        else:
            raw = [{"name": k, "value": str(v)} for k, v in data.items()]
    else:
        for part in text.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                raw.append({"name": k.strip(), "value": v.strip()})

    cookies = []
    for c in raw:
        if not isinstance(c, dict) or "name" not in c or "value" not in c:
            continue
        item = {"name": str(c["name"]), "value": str(c["value"])}
        domain = str(c.get("domain") or ".kukuai.cn")
        item["domain"] = domain if domain.startswith(".") else "." + domain.lstrip(".")
        item["path"] = c.get("path") or "/"
        if c.get("expires"):
            try:
                item["expires"] = float(c["expires"])
            except (TypeError, ValueError):
                pass
        if isinstance(c.get("httpOnly"), bool):
            item["httpOnly"] = c["httpOnly"]
        if isinstance(c.get("secure"), bool):
            item["secure"] = c["secure"]
        if c.get("sameSite") in ("Strict", "Lax", "None"):
            item["sameSite"] = c["sameSite"]
        cookies.append(item)
    return cookies


def find_cookie_path(explicit: str) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            raise FileNotFoundError("Cookie 文件不存在: %s" % p)
        return p
    for cand in DEFAULT_COOKIE_PATHS:
        p = Path(cand).expanduser()
        if p.exists():
            return p
    raise FileNotFoundError(
        "未找到 Cookie 文件，请用 --cookies 指定（可选默认路径: %s）"
        % "、".join(DEFAULT_COOKIE_PATHS)
    )


# --------------------------------------------------------------------------- #
# 连签状态（跨天持久化）
# --------------------------------------------------------------------------- #

def read_cookie_meta(cookie_path: Path) -> dict | None:
    """读 GetCookie 写下的 cookies.meta.json（同目录、同名前缀）。

    刻意不猜：旧版工具不写 meta，这里就返回 None，调用方什么都不说。
    绝不能因为「读不到」就推断「已过期」——那是把未知当成已知。
    """
    p = Path(cookie_path)
    mp = p.with_name(p.stem + ".meta.json")
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def cookie_ttl(meta: dict | None) -> dict | None:
    """把 meta 变成可展示的有效期结论。

    known=False 表示「本地没有可靠的到期时间」（没有 meta / 会话级 cookie），
    这时既不说快过期，也不说已过期，只如实标注未知。
    """
    if not isinstance(meta, dict):
        return None
    exp = meta.get("expires_at")
    out = {
        "captured_at": meta.get("captured_at"),
        "captured_at_text": meta.get("captured_at_iso") or "",
        "login_host": meta.get("login_host") or "",
        "expires_at": exp,
        "expires_name": meta.get("expires_name") or "",
        "source": "meta",
    }
    if not isinstance(exp, (int, float)) or exp <= 0:
        out.update(known=False, expired=None, remain_days=None,
                   note="会话级 Cookie 或未记录有效期，无法预测何时过期")
        return out
    now = time.time()
    remain = exp - now
    out.update(known=True, expired=remain <= 0,
               remain_seconds=int(remain), remain_days=round(remain / 86400, 1),
               expires_text=datetime.fromtimestamp(exp, CN_TZ).strftime("%Y-%m-%d"))
    return out

def load_state(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
class Runner:
    def __init__(self, args, activity: dict, log):
        self.args = args
        self.act = activity
        self.sel = activity.get("selectors", {})
        self.api = activity.get("api", {})
        self.channels = activity.get("channels") or [{"key": "kuku_signin_30_web", "label": "网页端"}]
        self.task_by_key = {t["key"]: t for t in activity.get("tasks", [])}
        self.log = log
        self.page = None
        self.ctx = None
        self._pending_upload = None
        self._action_note = ""
        self.boards = {}
        self.base = None          # 解析出来的入口域名，如 https://www.kukuai.cn
        self.cookies = []
        self.stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.out_dir = Path(args.out).expanduser()
        self.result = {
            "ok": False,
            "stage": "init",
            "activity": activity_meta(activity),
            "url": args.url,
            "base_host": None,
            "logged_in": None,
            "cookie": None,          # 本地有效期预测（仅提示用，鉴权仍以服务端为准）
            "dry_run": bool(args.dry_run),
            "signed_today": None,
            "streak_days": None,
            "next_node": None,
            "points": None,
            "lottery_chances": None,
            "channels": [],
            "task_board": [],
            "actions": [],
            "warnings": [],
            "notes": [],
            "screenshots": [],
            "error": None,
        }

    # ---------------- 基础 ----------------
    def shot(self, tag: str):
        path = self.out_dir / ("kukuai-%s-%s.png" % (tag, self.stamp))
        try:
            self.page.screenshot(path=str(path), full_page=True)
            self.result["screenshots"].append(str(path))
            self.log("screenshot -> %s" % path)
        except Exception as e:
            self.log("screenshot failed: %s" % e)

    def body_text(self) -> str:
        try:
            return self.page.inner_text("body") or ""
        except Exception:
            return ""

    def flat(self) -> str:
        return re.sub(r"\s+", " ", self.body_text())

    def dismiss_dialogs(self, rounds=3):
        """关掉活动推广弹窗（只会挡住点击，不影响账号状态）。"""
        for _ in range(rounds):
            try:
                n = self.page.evaluate(
                    """() => { let n = 0;
                        document.querySelectorAll('[data-testid="activity-dialog-close"]').forEach(e => { e.click(); n++; });
                        return n; }"""
                )
            except Exception:
                n = 0
            if not n:
                break
            self.log("closed activity dialog x%d" % n)
            self.page.wait_for_timeout(600)

    def cookie_host_hint(self) -> str:
        """按 cookie 落在哪个域，猜该用哪个入口。"""
        bduss_dom = ""
        for c in self.cookies:
            if str(c.get("name") or "") == "BDUSS":
                bduss_dom = str(c.get("domain") or "").lstrip(".").lower()
                break
        if "kukuai.cn" in bduss_dom:
            return "https://www.kukuai.cn"
        if bduss_dom.endswith("baidu.com"):
            return "https://kuku.baidu.com"
        doms = [str(c.get("domain") or "").lstrip(".").lower() for c in self.cookies]
        if any(d == "kukuai.cn" or d.endswith(".kukuai.cn") for d in doms):
            return "https://www.kukuai.cn"
        return ""

    def resolve_host(self) -> str:
        """两个入口的 cookie 互不相认，跑之前先问出哪个域认这份 cookie。"""
        forced = {"baidu": "https://kuku.baidu.com", "kukuai": "https://www.kukuai.cn"}.get(
            getattr(self.args, "host", "") or "")
        if self.args.url:
            order = [self.args.url.rstrip("/").replace("/app", "")]
        elif forced:
            order = [forced]
        else:
            hint = self.cookie_host_hint()
            order = ([hint] if hint else []) + [h for h in CANDIDATE_HOSTS if h != hint]
        for host in order:
            try:
                self.page.goto(host + "/app", wait_until="domcontentloaded", timeout=45000)
                self.page.wait_for_timeout(3500)
                errno = self.page.evaluate("""async () => {
                    const r = await fetch('/api/genflowpro/common/userreport?clienttype=400&app_id=123971023&web=1&channel=chunlei&version=1.6.32', {credentials: 'include'});
                    try { const d = await r.json(); return d.errno; } catch (e) { return -999; }
                }""")
            except Exception as e:
                self.log("probe %s failed: %s" % (host, str(e)[:60]))
                continue
            self.log("probe %s -> errno=%s" % (host, errno))
            if errno == 0:
                return host
        return ""

    def goto_home(self, timeout_ms=60000, attempts=3) -> bool:
        url = (self.base + "/app") if self.base else (self.args.url or HOME_URL)
        for i in range(attempts):
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                return True
            except Exception as e:
                self.log("goto attempt %d/%d failed: %s" % (i + 1, attempts, str(e)[:90]))
                self.page.wait_for_timeout(3000)
        return False

    def wait_ready(self, timeout_s=15) -> bool:
        for _ in range(timeout_s * 2):
            t = self.flat()
            if ("知识广场" in t or "新建任务" in t) and len(t) > 200:
                return True
            self.page.wait_for_timeout(500)
        return False

    def restore_app(self):
        """回到工作台首页（聊天/广场/网盘路由的起点）。"""
        if not self.goto_home():
            raise RuntimeError("打开工作台失败")
        self.page.wait_for_timeout(4000)
        self.dismiss_dialogs()

    def bind_page_handlers(self):
        def on_filechooser(fc):
            target = self._pending_upload or self.upload_probe_file()
            try:
                fc.set_files(str(target))
                self.log("filechooser handled: %s" % target)
            except Exception as e:
                self.log("filechooser failed: %s" % e)

        def on_dialog(d):
            try:
                self.log("dialog: %s" % (d.message or "")[:80])
                d.accept()
            except Exception:
                pass

        try:
            self.page.on("filechooser", on_filechooser)
            self.page.on("dialog", on_dialog)
        except Exception as e:
            self.log("bind handlers failed: %s" % e)

    def upload_probe_file(self) -> Path:
        path = Path(tempfile.gettempdir()) / ("库库AI每日任务_%s.txt" % datetime.now(CN_TZ).strftime("%Y%m%d"))
        try:
            path.write_text(
                "库库AI 每日任务占位文件\n生成时间：%s\n可自行删除。\n"
                % datetime.now(CN_TZ).isoformat(timespec="seconds"),
                encoding="utf-8",
            )
        except Exception as e:
            self.log("write probe file failed: %s" % e)
        return path

    # ---------------- 登录态 ----------------
    def detect_login(self, body: str = ""):
        flat = re.sub(r"\s+", " ", body or self.body_text())
        pos = self.act.get("login_positive_markers") or []
        neg = self.act.get("login_negative_markers") or []
        if any(k and k in flat for k in pos):
            return True
        if any(k and k in flat for k in neg):
            return False
        return None

    # ---------------- 官方接口（唯一可信来源） ----------------
    def js_token(self) -> str:
        try:
            return self.page.evaluate("() => window.jsToken || ''") or ""
        except Exception:
            return ""

    def fetch_tasks(self, channel: str) -> dict:
        path = (self.api.get("tasklist") or "/api/taskscore/tasklist?task_from=") + channel
        data = self.page.evaluate(
            """async (url) => {
                const r = await fetch(url, {credentials: 'include'});
                try { return await r.json(); } catch (e) { return {errno: -999, errmsg: 'non-json'}; }
            }""",
            path,
        )
        out = {}
        if not data or data.get("errno") != 0:
            self.log("tasklist %s failed: %s" % (channel, str(data)[:160]))
            return out
        for t in (data.get("result") or {}).get("list") or []:
            extra = {}
            try:
                extra = json.loads(t.get("task_extra") or "{}")
            except Exception:
                pass
            ttype = extra.get("task_type")
            try:
                ttype = int(ttype)
            except (TypeError, ValueError):
                ttype = None
            out[ttype] = {
                "type": ttype,
                "name": t.get("task_desc"),
                "id": t.get("task_id_str"),
                "finish": int(t.get("task_finish_count") or 0),
                "max": int(t.get("task_count_max") or 0),
                "class_id": t.get("task_class_id"),
            }
        return out

    def refresh_boards(self) -> dict:
        self.boards = {}
        for ch in self.channels:
            self.boards[ch["key"]] = self.fetch_tasks(ch["key"])
        return self.boards

    def channel_tasks(self, channel: str, key: str):
        t = self.task_by_key.get(key) or {}
        return (self.boards.get(channel) or {}).get(t.get("type_id"))

    def remaining(self, channel: str, key: str) -> int:
        info = self.channel_tasks(channel, key)
        if not info:
            return 0
        return max(0, info["max"] - info["finish"])

    def report_task(self, channel: str, key: str, session_id: str = "") -> dict:
        """上报一次任务事件。返回 {errno, msg}。聊天类任务必须带真实 session_id。"""
        t = self.task_by_key.get(key) or {}
        info = self.channel_tasks(channel, key)
        if not info or not info.get("id") or not t.get("event_type"):
            return {"errno": -1, "msg": "缺少任务ID或事件类型"}
        q = {
            "jsToken": self.js_token(),
            "clienttype": str(self.api.get("clienttype") or 400),
            "version": self.api.get("version") or "1.6.32",
            "app_id": str(self.api.get("app_id") or 123971023),
        }
        url = (self.api.get("complete") or "/api/genflowpro/activity/taskcomplete") + "?" + urlencode(q)
        body = {
            "task_from": channel,
            "event_type": t["event_type"],
            "task_id_str": info["id"],
            "app_id": self.api.get("app_id") or 123971023,
            "clienttype": self.api.get("clienttype") or 400,
            "version": self.api.get("version") or "1.6.32",
        }
        if session_id:
            body["session_id"] = session_id
        res = self.page.evaluate(
            """async ({url, body}) => {
                const r = await fetch(url, {method: 'POST', credentials: 'include',
                    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
                try { return await r.json(); } catch (e) { return {errno: -999, errmsg: 'non-json ' + r.status}; }
            }""",
            {"url": url, "body": body},
        )
        errno = (res or {}).get("errno")
        self.log("report %s/%s -> errno=%s %s" % (channel, key, errno, (res or {}).get("errmsg") or ""))
        return {"errno": errno, "msg": (res or {}).get("errmsg") or "", "raw": res}

    def report_until_done(self, channel: str, key: str, max_times: int = 6, sessions=None) -> int:
        """按当前剩余次数上报，直到接口显示完成或失败。返回成功上报次数。"""
        done = 0
        sessions = list(sessions or [])
        for _ in range(max_times):
            left = self.remaining(channel, key)
            if left <= 0:
                break
            need_sid = bool((self.task_by_key.get(key) or {}).get("event_type", "").endswith("CONVERSATION_TASK")) or \
                key in ("topic_chat", "expert_chat")
            sid = ""
            if need_sid:
                if not sessions:
                    self.result["warnings"].append(
                        "%s · %s 缺少真实会话ID（session_id），接口不接受上报" % (channel, key))
                    break
                sid = sessions.pop(0)
            r = self.report_task(channel, key, sid)
            if r.get("errno") != 0:
                self.result["warnings"].append(
                    "%s · %s 上报失败（errno=%s %s）" % (channel, key, r.get("errno"), r.get("msg")))
                break
            done += 1
            self.page.wait_for_timeout(900)
            self.boards[channel] = self.fetch_tasks(channel)
        return done

    # ---------------- 签到（活动页直连，最稳） ----------------
    def read_streak_points(self) -> dict:
        flat = self.flat()
        st = {}
        m = (re.search(r"已签\s*(\d+)\s*天", flat)
             or re.search(r"已连签\s*(\d+)\s*天", flat)
             or re.search(r"已连续签到\s*(\d+)\s*天", flat))
        if m:
            st["streak"] = int(m.group(1))
        m = re.search(r"再签\s*(\d+)\s*天", flat)
        if m:
            st["need_for_node"] = int(m.group(1))
        m = re.search(r"距离活动结束\s*([0-9]+\s*天[0-9:：\s]*)", flat)
        if m:
            st["countdown"] = m.group(1).strip()
        m = (re.search(r"(?:积分余额|库库积分余额|我的积分|剩余积分)\s*[:：]?\s*([\d,]+)", flat)
             or re.search(r"(?<![\d.+])([\d,]{2,9})\s*积分(?!\s*[\+＋])", flat))
        if m:
            try:
                st["points"] = int(m.group(1).replace(",", ""))
            except ValueError:
                pass
        m = (re.search(r"抽奖次数\s*[:：]?\s*(\d+)", flat)
             or re.search(r"(?<![\d.])(\d+)\s*次抽奖", flat)
             or re.search(r"剩\s*(\d+)\s*次", flat))
        if m:
            try:
                st["lottery"] = int(m.group(1))
            except ValueError:
                pass
        return st

    def sign_api(self, action: str) -> dict:
        """直接调活动接口（homepage / signin），不依赖活动页渲染。

        云端实测：活动页会白屏——JS 从 staticplat.cdn.bcebos.com 拉，
        机房网络拉不动，Vue 起不来，body 是空的。但同域接口一直通。
        所以状态查询与签到动作都优先走这里，页面点击退为兜底。
        """
        base = self.api.get("sign_base") or "/act/v2/kukuai30"
        tid = str(self.api.get("sign_tid") or "")
        if not tid:
            return {"errno": -1, "errmsg": "配置缺少 api.sign_tid"}
        url = "%s/%s?tid=%s" % (base, action, tid)
        try:
            res = self.page.evaluate("""async ({url}) => {
                try {
                    const r = await fetch(url, {method:'POST', credentials:'include',
                        headers:{'Content-Type':'application/json'}, body:'{}'});
                    const t = await r.text();
                    try { return Object.assign({http:r.status}, JSON.parse(t)); }
                    catch(e) { return {http:r.status, errno:-999, errmsg:'non-json', raw:t.slice(0,160)}; }
                } catch(e) { return {errno:-998, errmsg:String(e).slice(0,80)}; }
            }""", {"url": url}) or {}
        except Exception as e:
            return {"errno": -997, "errmsg": str(e)[:80]}
        return res

    def sign_state_api(self) -> dict:
        """接口版签到状态：{signed_today, streak, raw}。失败返回 {}。"""
        res = self.sign_api("homepage")
        if res.get("errno") != 0:
            self.log("sign_state api failed: errno=%s %s" % (res.get("errno"), str(res.get("errmsg"))[:60]))
            return {}
        data = res.get("data") or {}
        if not isinstance(data, dict):
            return {}
        return {
            "signed_today": data.get("signed_today"),
            "streak": data.get("continuous_days"),
            "total_days": data.get("total_days"),
            "next_reward_days": data.get("next_reward_days"),
        }

    def do_signin(self) -> dict:
        self.result["stage"] = "signin"

        # ---- 0) 接口优先：先问「今天签没签」，不依赖页面渲染 ----
        api_st = self.sign_state_api()
        if api_st.get("signed_today") is True:
            self.log("signin via api: already signed (streak=%s)" % api_st.get("streak"))
            self.result["actions"].append({"signin": "api_already"})
            self.page.wait_for_timeout(300)
            self.shot("signed")
            return {"signed_today": True, "streak": api_st.get("streak"),
                    "points": None, "lottery": None, "source": "api"}
        if api_st.get("signed_today") is False:
            res = self.sign_api("signin")
            errno = res.get("errno")
            self.log("signin api: errno=%s %s" % (errno, str(res.get("errmsg"))[:60]))
            if errno == 0:
                self.result["actions"].append({"signin": "api_ok"})
            elif errno == 10152:
                # 重复签到 = 今天已经签过，不是失败
                self.result["actions"].append({"signin": "api_already(10152)"})
            else:
                self.result["notes"].append("接口签到返回 errno=%s（将回退到页面点击）" % errno)
            after = self.sign_state_api()
            if after.get("signed_today") is True:
                self.log("signin confirmed by api after post")
                self.result["actions"].append({"signin": "api_confirmed"})
                self.shot("signed")
                return {"signed_today": True, "streak": after.get("streak"),
                        "points": None, "lottery": None, "source": "api"}
        else:
            self.log("sign_state api unavailable, fallback to page")

        # 先在首页签到卡上点一次（卡片偶尔不渲染，失败不影响后面的活动页直点）
        try:
            cta = self.page.locator(self.sel.get("signin_cta") or '[data-testid="signin-promo-cta"]')
            if cta.count() and cta.first.is_visible():
                txt = (cta.first.inner_text() or "").strip()
                if (any(k in txt for k in ("签到", "领奖", "领取", "立即"))
                        and not any(k in txt for k in ("已签", "明天", "明日"))):
                    cta.first.click(timeout=3000)
                    self.log("home cta clicked: %r" % txt)
                    self.result["actions"].append({"signin": "home_cta(%s)" % txt})
                    self.page.wait_for_timeout(3000)
        except Exception as e:
            self.log("home cta skipped: %s" % str(e)[:60])

        url = (self.base or "https://kuku.baidu.com") + ACTIVITY_PATH
        # 活动页静态资源多，云端实测过 domcontentloaded 60 秒超时。
        # 改成 commit（导航一提交就返回）+ 后面靠按钮轮询等渲染，两次机会。
        opened = False
        last_err = ""
        for attempt, wait_mode in enumerate(("commit", "domcontentloaded")):
            try:
                self.page.goto(url, wait_until=wait_mode, timeout=45000)
                opened = True
                self.log("activity page opened (wait=%s, attempt=%d)" % (wait_mode, attempt + 1))
                break
            except Exception as e:
                last_err = str(e)[:110]
                self.log("open activity page attempt %d (%s) failed: %s"
                         % (attempt + 1, wait_mode, last_err))
        if not opened:
            self.result["warnings"].append("活动页打不开（%s），签到未完成" % last_err[:80])
            self.shot("signin-failed")
            return {}
        self.page.wait_for_timeout(1500)

        btn_sel = self.sel.get("signin_btn") or "button.pc-sign-btn"
        st = self.read_streak_points()

        btn_txt = ""
        diag = {}
        # 等按钮真正就绪：在 DOM 里不算，得有文字或可见尺寸。
        # 云端实测过「按钮已存在但 innerText 还是空」的竞态——那时读空就判成「未签」，
        # 于是去点一个还没渲染完的按钮，最后两头落空。
        waited = 0
        while waited < 50:
            try:
                probe = self.page.locator(btn_sel)
                if probe.count():
                    el = probe.first
                    t = re.sub(r"\s+", " ", el.inner_text() or "").strip()
                    try:
                        vis = el.is_visible()
                    except Exception:
                        vis = False
                    if vis and (t or el.bounding_box()):
                        if t:
                            break
            except Exception:
                pass
            self.page.wait_for_timeout(500)
            waited += 1
        if waited:
            self.log("signin btn ready after %.1fs" % (waited * 0.5))

        try:
            loc = self.page.locator(btn_sel)
            diag["count"] = loc.count()
            if diag["count"]:
                btn_txt = re.sub(r"\s+", " ", loc.first.inner_text() or "").strip()
                try:
                    diag["visible"] = loc.first.is_visible()
                    diag["box"] = list(loc.first.bounding_box() or {})
                except Exception as e:
                    diag["v_err"] = str(e)[:40]
                diag["html"] = (loc.first.evaluate("e => e.outerHTML") or "")[:180]
        except Exception as e:
            diag["err"] = str(e)[:80]
        diag["url"] = self.page.url[-70:]
        diag["text"] = re.sub(r"\s+", " ", self.flat())[:180]
        self.log("signin page: btn=%r streak=%s diag=%s"
                 % (btn_txt, st.get("streak"), json.dumps(diag, ensure_ascii=False)))
        self.shot("signin-page")

        already = any(k in btn_txt for k in ("已签", "明天再来", "明日再来", "已领"))
        if already:
            self.result["actions"].append({"signin": "already(%s)" % btn_txt})
        else:
            hit = False
            try:
                loc = self.page.locator(btn_sel)
                if loc.count() and loc.first.is_visible():
                    try:
                        loc.first.click(timeout=5000)
                    except Exception as ce:
                        self.log("sign btn click blocked (%s), DOM click" % str(ce)[:60])
                        loc.first.evaluate("e => e.click()")
                    hit = True
                    self.log("signin clicked(%r)" % btn_txt)
            except Exception as e:
                self.log("sign btn click failed: %s" % e)
            if not hit:
                for t in self.act.get("signin_texts", []):
                    try:
                        loc = self.page.get_by_role("button", name=t, exact=True)
                        if not loc.count():
                            loc = self.page.get_by_text(t, exact=True)
                        if loc.count() and loc.first.is_visible():
                            loc.first.click(timeout=4000)
                            hit = True
                            self.log("signin clicked via text %s" % t)
                            break
                    except Exception:
                        continue
            if not hit:
                self.result["warnings"].append(
                    "活动页没点到签到按钮（count=%s visible=%s，页面首屏=%r）"
                    % (diag.get("count"), diag.get("visible"), (diag.get("text") or "")[:70]))
                self.result["notes"].append("签到诊断：%s" % json.dumps(diag, ensure_ascii=False)[:400])
                self.shot("signin-failed")
                return st
            self.page.wait_for_timeout(3500)
            self.dismiss_dialogs()
            self.result["actions"].append({"signin_clicked": True})

        # 重新读状态确认
        st2 = self.read_streak_points()
        for k, v in st2.items():
            if v is not None:
                st[k] = v
        cls = ""
        try:
            loc = self.page.locator(btn_sel)
            if loc.count():
                el = loc.first
                st["sign_btn_text"] = re.sub(r"\s+", " ", el.inner_text() or "").strip()
                # 按钮自带状态类：已签时是 `pc-sign-btn is-signed`。
                # 这比读文字稳（文字可能还没渲染），比整页关键词准（页面到处都有「已签2天」）。
                cls = (el.get_attribute("class") or "")
                st["sign_btn_class"] = cls
        except Exception:
            pass
        flat = self.flat()
        st["signed_today"] = (
            "is-signed" in cls
            or any(k in (st.get("sign_btn_text") or "") for k in ("已签", "明天再来", "明日再来", "已领"))
            or any(k in flat for k in SUCCESS_KEYWORDS)
        )
        # 页面读不到 ≠ 没签：白屏/渲染慢时按钮可能永远不出现。
        # 最后问一次接口，接口说签了就是签了（页面只是显示层）。
        if st.get("signed_today") is not True:
            confirm = self.sign_state_api()
            if confirm.get("signed_today") is True:
                st["signed_today"] = True
                st["streak"] = st.get("streak") or confirm.get("streak")
                self.result["actions"].append({"signin": "api_confirmed_after_page"})
                self.log("page looked unsigned, api says signed -> trust api")

        if not st["signed_today"]:
            self.result["warnings"].append(
                "点击签到后未检测到「今日已签」（按钮=%r），请以截图复核" % (st.get("sign_btn_text") or ""))
        self.shot("signed")
        return st

    # ---------------- 真实动作 ----------------
    def chat_input(self):
        sel = self.sel.get("chat_input") or "div.tiptap[contenteditable='true']"
        for s in [sel, "[contenteditable='true']", "textarea"]:
            try:
                loc = self.page.locator(s)
                if loc.count() and loc.first.is_visible():
                    return loc.first
            except Exception:
                continue
        return None

    def chat_rows(self) -> int:
        try:
            return self.page.locator(self.sel.get("chat_row") or ".genflow-message-list-row").count()
        except Exception:
            return 0

    def last_row_text(self) -> str:
        try:
            rows = self.page.locator(self.sel.get("chat_row") or ".genflow-message-list-row")
            n = rows.count()
            if n:
                return rows.nth(n - 1).inner_text() or ""
        except Exception:
            pass
        return ""

    def current_session_id(self) -> str:
        """聊天会话ID在 URL 最后一个 ? 之后（hash 路由的 query 里）。"""
        try:
            u = self.page.url
        except Exception:
            return ""
        if "?" not in u:
            return ""
        try:
            return (parse_qs(u.rsplit("?", 1)[1]).get("session_id") or [""])[0]
        except Exception:
            return ""

    def open_new_chat(self) -> bool:
        """开一个新对话（任务按「会话数」计数，一条消息一个会话最稳）。"""
        clicked = False
        try:
            loc = self.page.get_by_text("新建任务", exact=True)
            if loc.count():
                loc.first.click(timeout=3000)
                clicked = True
        except Exception as e:
            self.log("new chat click failed: %s" % str(e)[:60])
        self.page.wait_for_timeout(2500)
        if not clicked or self.chat_input() is None:
            try:
                self.page.goto((self.base or self.args.url) + "?r=%d#/workbench/new-task" % int(time.time()),
                               wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                self.log("open new chat goto failed: %s" % str(e)[:70])
            self.page.wait_for_timeout(3500)
        self.dismiss_dialogs()
        for _ in range(20):
            if self.chat_input() is not None:
                return True
            self.page.wait_for_timeout(600)
        return False

    def send_chat(self, prompt: str) -> str:
        """发一条消息：等气泡出现 + 回复稳定，返回该会话 session_id（失败返回空串）。"""
        el = self.chat_input()
        if el is None:
            self.log("chat input not found")
            return ""
        before = self.chat_rows()
        try:
            el.click(timeout=5000)
        except Exception:
            self.dismiss_dialogs()
            try:
                el.click(timeout=3000)
            except Exception:
                el.evaluate("e => e.focus()")
        try:
            el.fill(prompt)
        except Exception as e:
            self.log("fill failed: %s" % e)
            try:
                el.evaluate("e => e.focus()")
                self.page.keyboard.insert_text(prompt)
            except Exception:
                return ""
        self.page.wait_for_timeout(350)
        self.page.keyboard.press("Enter")

        appeared = False
        for _ in range(40):
            self.page.wait_for_timeout(500)
            if self.chat_rows() > before:
                appeared = True
                break
            if prompt[:10] in self.flat() and prompt[:10] not in (el.inner_text() or ""):
                appeared = True
                break
        if not appeared:
            self.log("chat send not confirmed: %s" % prompt[:20])
            return ""

        # 等回复稳定（连续 2 秒文本不再变长）
        stable = 0
        last = ""
        for _ in range(60):
            self.page.wait_for_timeout(1000)
            cur = self.last_row_text()
            if cur and len(cur) == len(last):
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
            last = cur

        sid = ""
        for _ in range(10):
            sid = self.current_session_id()
            if sid:
                break
            self.page.wait_for_timeout(600)
        self.log("chat ok sid=%s prompt=%s" % (sid[:10], prompt[:20]))
        return sid

    def act_chat(self, count: int):
        """返回 (成功条数, [session_id...])"""
        self.restore_app()
        sids = []
        for i in range(count):
            if not self.open_new_chat():
                break
            sid = self.send_chat(CHAT_PROMPTS[i % len(CHAT_PROMPTS)])
            if not sid:
                break
            sids.append(sid)
        return len(sids), sids

    def act_square(self, seconds: int = 14):
        self.restore_app()
        try:
            self.page.goto((self.base or self.args.url) + "#/workbench/knowledge-square",
                           wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            self.log("goto square failed: %s" % str(e)[:80])
            return 0, []
        self.page.wait_for_timeout(3000)
        for _ in range(3):
            try:
                self.page.mouse.wheel(0, 700)
            except Exception:
                pass
            self.page.wait_for_timeout(1500)
        left = max(0, seconds - 8)
        if left:
            self.page.wait_for_timeout(left * 1000)
        ok = "知识广场" in self.flat() and "knowledge-square" in self.page.url
        self.log("square visited=%s url=%s" % (ok, self.page.url[-40:]))
        self.shot("square")
        return (1, []) if ok else (0, [])

    def expert_consented(self) -> bool:
        try:
            d = json.loads(Path(CONSENT_PATH).expanduser().read_text(encoding="utf-8"))
            return bool(d.get("expert_agreement"))
        except Exception:
            return False

    def save_expert_consent(self):
        try:
            p = Path(CONSENT_PATH).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"expert_agreement": True,
                                     "at": datetime.now(CN_TZ).isoformat(timespec="seconds")},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self.log("save consent failed: %s" % e)

    def act_expert(self):
        self.restore_app()
        self.page.goto((self.base or self.args.url) + "#/workbench/expert", wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(4500)
        self.dismiss_dialogs()

        clicked = False
        for sel in [self.sel.get("expert_card") or "article.expert-card",
                    "[class*='expert-card']", "[class*='expertCard']"]:
            try:
                card = self.page.locator(sel).first
                if not card.count():
                    continue
                btn = card.get_by_role("button", name=self.sel.get("expert_summon") or "召唤")
                if btn.count():
                    try:
                        btn.first.click(timeout=4000)
                    except Exception:
                        btn.first.evaluate("e => e.click()")
                    clicked = True
                    self.log("summoned expert via %s" % sel)
                    break
            except Exception as e:
                self.log("summon via %s failed: %s" % (sel, e))
        if not clicked:
            try:
                loc = self.page.get_by_role("button", name="召唤")
                if loc.count():
                    loc.first.click(timeout=4000)
                    clicked = True
            except Exception:
                pass
        if not clicked:
            self.log("no 召唤 button found")
            return 0, []

        self.page.wait_for_timeout(2500)
        # 用户协议：只有显式 --with-expert 才代勾
        agreed = False
        for t in ["我已阅读并同意", "我已阅读并同意本协议"]:
            try:
                loc = self.page.get_by_text(t, exact=True)
                if loc.count() and loc.first.is_visible():
                    if not (getattr(self.args, "with_expert", False) or self.expert_consented()):
                        self.log("user agreement dialog requires manual consent")
                        self._action_note = ("首次召唤专家要你本人勾选《库库AI用户协议》；"
                                             "同意过一次后（--with-expert 跑一次），以后每天都会自动完成")
                        self.result["notes"].append(self._action_note)
                        return 0, []
                    loc.first.click(timeout=2500)
                    agreed = True
                    break
            except Exception:
                continue
        if agreed:
            for t in ["继续使用", "确定", "确认"]:
                try:
                    loc = self.page.get_by_text(t, exact=True)
                    if loc.count() and loc.first.is_visible():
                        loc.first.click(timeout=3000)
                        break
                except Exception:
                    continue
            self.page.wait_for_timeout(2500)
            self.save_expert_consent()
            self.result["notes"].append("已代勾《库库AI用户协议》（同意记录已保存，之后自动）")

        self.page.wait_for_timeout(1200)
        sid = self.send_chat(EXPERT_PROMPT)
        return (1, [sid]) if sid else (0, [])

    def act_upload(self):
        self.restore_app()
        self.page.goto((self.base or self.args.url) + "#/workbench/netdisk", wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(5000)
        self.dismiss_dialogs()
        probe = self.upload_probe_file()
        self._pending_upload = probe

        opened = False
        try:
            self.page.locator("button", has_text="上传").first.click(timeout=4000)
            opened = True
        except Exception as e:
            self.log("upload menu click failed: %s" % str(e)[:80])
        if not opened:
            try:
                self.page.get_by_text("上传", exact=True).first.evaluate("e => e.click()")
                opened = True
            except Exception:
                pass
        if not opened:
            return 0, []
        self.page.wait_for_timeout(1200)
        try:
            self.page.get_by_text("上传文件", exact=True).first.click(timeout=4000)
        except Exception:
            try:
                self.page.get_by_text("上传文件", exact=True).first.evaluate("e => e.click()")
            except Exception as e:
                self.log("upload file menu failed: %s" % str(e)[:80])
                return 0, []
        self.page.wait_for_timeout(1500)

        name = probe.name
        for _ in range(30):
            self.page.wait_for_timeout(1000)
            if name in self.flat():
                self.log("uploaded: %s" % name)
                self.shot("upload")
                return 1, []
        self.log("upload not confirmed (file name not in list)")
        return 0, []

    def act_import(self):
        """从百度网盘导入一次文件（需已授权）。默认不做，--with-netdisk 开启。"""
        self.restore_app()
        self.page.goto((self.base or self.args.url) + "#/workbench/netdisk", wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(5000)
        self.dismiss_dialogs()
        before = self.flat()
        try:
            self.page.locator("button", has_text="导入百度网盘文件").first.click(timeout=4000)
        except Exception as e:
            self.log("import click failed: %s" % str(e)[:80])
            return 0, []
        self.page.wait_for_timeout(4000)
        body = self.flat()
        if "确定授权" in body:
            if not getattr(self.args, "with_netdisk", False):
                self._action_note = "导入网盘文件要先授权百度网盘（网页上点一次「确定授权」即可，之后 --with-netdisk 可自动导入）"
                self.result["notes"].append(self._action_note)
                return 0, []
            try:
                self.page.get_by_text("确定授权", exact=True).first.click(timeout=4000)
            except Exception as e:
                self.log("authorize click failed: %s" % str(e)[:80])
                return 0, []
            self.page.wait_for_timeout(6000)
            body = self.flat()
            if "确定授权" in body:
                self.log("netdisk authorization not completed")
                return 0, []
        # 选择第一个文件
        picked = False
        for sel in ["[role='dialog'] li", "[role='dialog'] [class*='file']",
                    "[class*='file-list'] li", "[class*='fileItem']"]:
            try:
                loc = self.page.locator(sel)
                if loc.count():
                    loc.first.click(timeout=3000)
                    picked = True
                    break
            except Exception:
                continue
        if not picked:
            self.log("no netdisk file row found")
            self._action_note = "没找到可导入的百度网盘文件，或授权没走完；先手动点一次「确定授权」再重跑"
            self.result["notes"].append(self._action_note)
            return 0, []
        for t in ["确定", "导入", "开始导入"]:
            try:
                loc = self.page.get_by_text(t, exact=True)
                if loc.count() and loc.first.is_visible():
                    loc.first.click(timeout=3000)
                    break
            except Exception:
                continue
        self.page.wait_for_timeout(6000)
        ok = self.flat() != before
        self.log("import ok=%s" % ok)
        return (1, []) if ok else (0, [])

    # ---------------- 任务编排 ----------------
    def plan_remaining(self, keys) -> dict:
        """{key: {channel: remaining}}"""
        out = {}
        for k in keys:
            out[k] = {ch["key"]: self.remaining(ch["key"], k) for ch in self.channels}
        return out

    def run_tasks(self):
        self.result["stage"] = "tasks"
        wanted = None
        if self.args.tasks:
            wanted = {x.strip() for x in self.args.tasks.split(",") if x.strip()}

        actions = {
            "chat": ("topic_chat", self.act_chat),
            "square": ("browse_square", lambda n: self.act_square()),
            "expert": ("expert_chat", lambda n: self.act_expert()),
            "upload": ("upload_local", lambda n: self.act_upload()),
            "import": ("import_netdisk", lambda n: self.act_import()),
        }

        for mode, (key, fn) in actions.items():
            task = self.task_by_key.get(key) or {}
            need_map = {ch["key"]: self.remaining(ch["key"], key) for ch in self.channels}
            need = max(need_map.values()) if need_map else 0
            label = task.get("name") or key
            entry = {"mode": mode, "key": key, "name": label, "need": need_map, "action_units": 0,
                     "reported": {}, "result": None}

            if wanted is not None and key not in wanted:
                entry["result"] = "跳过（未在 --tasks 中指定）"
                self.result["actions"].append(entry)
                continue
            if need <= 0:
                entry["result"] = "已在各端完成"
                self.result["actions"].append(entry)
                continue
            if mode == "upload" and getattr(self.args, "no_upload", False):
                entry["result"] = "跳过（--no-upload）"
                self.result["actions"].append(entry)
                continue

            self._action_note = ""

            # 两轮：动作 → 上报 → 重新核验，不够再来一轮
            for rnd in range(2):
                left_now = max(self.remaining(ch["key"], key) for ch in self.channels)
                if left_now <= 0:
                    break
                units, sids = fn(left_now) if mode == "chat" else fn(1)
                entry["action_units"] += int(units or 0)
                if not units:
                    self.log("action %s produced 0 unit, stop" % mode)
                    if self._action_note:
                        entry["result"] = "跳过（%s）" % self._action_note
                    break
                for ch in self.channels:
                    ck = ch["key"]
                    left = self.remaining(ck, key)
                    if left <= 0:
                        continue
                    entry["reported"][ck] = self.report_until_done(
                        ck, key, min(left, int(units)), sessions=list(sids))

            if entry.get("result"):
                self.result["actions"].append(entry)
                continue

            # 核验后写结果
            bits = []
            have = []
            for ch in self.channels:
                ck = ch["key"]
                info = self.channel_tasks(ck, key)
                if not info:
                    continue
                have.append(ck)
                bits.append("%s %s/%s" % (ch.get("label"), info.get("finish", 0), info.get("max", 0)))
            all_done = all(self.remaining(ck, key) <= 0 for ck in have) if have else False
            if all_done:
                entry["result"] = "已完成（%s）" % "、".join(bits)
            else:
                extra = ("；%s" % self._action_note) if self._action_note else ""
                entry["result"] = "未达成（%s）%s" % ("、".join(bits), extra)
            self.result["actions"].append(entry)

    # ---------------- 收尾核验 ----------------
    def build_board(self) -> list:
        board = []
        absent = []
        for ch in self.channels:
            ck, label = ch["key"], ch.get("label") or ch["key"]
            tasks = self.boards.get(ck) or {}
            for t in self.act.get("tasks", []):
                info = tasks.get(t.get("type_id"))
                if not info:
                    absent.append("%s无「%s」" % (label, t["name"]))
                    continue
                fin, mx = info["finish"], info["max"]
                state = "已完成" if mx and fin >= mx else ("进行中" if fin else "未完成")
                board.append({"channel": ck, "label": label, "key": t["key"], "name": t["name"],
                              "state": state, "finish": fin, "max": mx or t.get("limit")})
        if absent:
            self.result["notes"].append("该端没有的任务：" + "；".join(absent))
        return board

    def summarize_channels(self) -> list:
        out = []
        for ch in self.channels:
            ck, label = ch["key"], ch.get("label") or ch["key"]
            rows = [b for b in self.result["task_board"] if b["channel"] == ck]
            done = sum(1 for b in rows if b["state"] == "已完成")
            out.append({"key": ck, "label": label, "done": done, "total": len(rows)})
        return out

    def check_warnings(self, state_path: Path, st: dict):
        today = today_cn()
        prev = load_state(state_path)
        prev_date = prev.get("last_signed_date")
        if prev_date:
            try:
                pd = parse_iso_date(prev_date)
            except Exception:
                pd = None
            if pd and (today - pd).days > 1:
                self.result["warnings"].append(
                    "距上次成功签到已 %d 天，连签可能已中断（规则：断签清零）" % (today - pd).days)
        if not st.get("signed_today") and not getattr(self.args, "no_signin", False):
            self.result["warnings"].append("今日尚未确认签到成功，请人工复核截图")
        node = self.result.get("next_node")
        if node and node["need"] <= 1:
            self.result["warnings"].append(
                "再签 %d 天即可解锁「%s」" % (node["need"], node.get("reward") or ("连签%d天" % node["day"])))
        dl = self.result["activity"].get("days_left")
        if dl is not None:
            if dl < 0:
                self.result["warnings"].append("活动已结束，脚本配置需更新为新一期")
            elif dl <= 3:
                self.result["warnings"].append("活动仅剩 %d 天，注意及时领奖" % dl)
        if st.get("signed_today"):
            try:
                save_state(state_path, {
                    "last_signed_date": today.isoformat(),
                    "last_run": datetime.now(CN_TZ).isoformat(timespec="seconds"),
                    "streak_days": st.get("streak"),
                    "points": st.get("points"),
                    "lottery_chances": st.get("lottery"),
                    "activity_id": self.act.get("id"),
                    "history": (prev.get("history") or [])[-29:] + [today.isoformat()],
                })
                self.result["notes"].append("已更新本地连签状态: %s" % state_path)
            except Exception as e:
                self.log("save state failed: %s" % e)

    def write_summary(self) -> str:
        r = self.result
        act = r["activity"]
        lines = ["### 库库AI 每日签到 · %s" % today_cn().isoformat(), ""]
        if r.get("error"):
            lines.append("- 状态：❌ %s" % r["error"])
        elif r.get("dry_run"):
            lines.append("- 状态：ℹ️ dry-run（只读接口，未签到、未做任务）")
        elif r.get("signed_today"):
            lines.append("- 状态：✅ 今日已签到")
        else:
            lines.append("- 状态：⚠️ 未确认签到成功")
        lines.append("- 活动：%s（%s，剩 %s 天）" % (act["name"], act["period"], act["days_left"]))
        if r.get("streak_days") is not None:
            lines.append("- 已连签：%s 天" % r["streak_days"])
        if r.get("next_node"):
            n = r["next_node"]
            lines.append("- 下一节点：连签 %s 天（还差 %s 天，奖励 %s）"
                         % (n["day"], n["need"], n.get("reward") or "以页面为准"))
        if r.get("points") is not None:
            lines.append("- 库库积分：%s" % r["points"])
        ck = r.get("cookie") or {}
        if ck.get("known"):
            if ck.get("expired"):
                lines.append("- 登录态：⚠️ 本地记录显示已于 %s 过期（服务端若仍可用则为误报）" % ck.get("expires_text"))
            else:
                lines.append("- 登录态：有效期至 %s（%s 到期，剩 %.1f 天）"
                             % (ck.get("expires_text"), ck.get("expires_name") or "关键 Cookie",
                                ck.get("remain_days") or 0))
        elif ck:
            lines.append("- 登录态：%s" % (ck.get("note") or "有效期未知"))

        if r.get("task_board"):
            lines.append("")
            lines.append("**任务实际进度（取自官方接口 tasklist，按渠道分开核验）**")
            lines.append("")
            lines.append("| 渠道 | 任务 | 进度 | 状态 |")
            lines.append("| --- | --- | --- | --- |")
            for b in r["task_board"]:
                prog = "%s/%s" % (b["finish"], b["max"]) if b.get("max") is not None else "-"
                mark = {"已完成": "✅", "进行中": "⏳", "未完成": "⬜", "未出现": "—"}.get(b["state"], "?")
                lines.append("| %s | %s | %s | %s %s |" % (b["label"], b["name"], prog, mark, b["state"]))

        if r.get("channels"):
            parts = ["%s %d/%d" % (c["label"], c["done"], c["total"]) for c in r["channels"]]
            lines.append("")
            lines.append("- 渠道完成度：%s" % "；".join(parts))

        # 没做的任务 + 原因（写清楚，别让调用方替我圆场）
        reasons = [a for a in (r.get("actions") or [])
                   if isinstance(a, dict) and a.get("result")
                   and ("跳过" in a["result"] or "未达成" in a["result"])]
        if reasons:
            lines.append("")
            lines.append("**没做的任务及原因**")
            for a in reasons:
                lines.append("- %s：%s" % (a.get("name") or a.get("key"), a.get("result")))

        manual = [t for t in self.act.get("tasks", []) if t.get("auto") == "manual"]
        if manual and not self.args.no_tasks:
            lines.append("")
            lines.append("**手动项（脚本不代做）**")
            for t in manual:
                if "邀请" in t["name"]:
                    lines.append("- %s：需要真实好友点你的邀请链接，脚本做不了" % t["name"])
                elif "下载" in t["name"]:
                    lines.append("- %s：装一次客户端并登录即可（在客户端里本来就没有这张卡）" % t["name"])
                else:
                    lines.append("- %s：需本人操作" % t["name"])

        if r.get("notes"):
            lines.append("")
            for n in r["notes"]:
                if n.startswith("该端没有的任务"):
                    lines.append("- 注：%s" % n)

        if r.get("warnings"):
            lines.append("")
            for w in r["warnings"]:
                lines.append("- ⚠️ %s" % w)
        if r.get("screenshots"):
            lines.append("")
            lines.append("- 截图：`%s`" % r["screenshots"][-1])
        text = "\n".join(lines)
        path = self.out_dir / ("kukuai-summary-%s.md" % self.stamp)
        try:
            path.write_text(text + "\n", encoding="utf-8")
            r["summary"] = str(path)
        except Exception as e:
            self.log("write summary failed: %s" % e)
        return text

    # ---------------- 入口 ----------------
    def run(self):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        state_path = (Path(self.args.state).expanduser()
                      if self.args.state else Path(DEFAULT_STATE_PATH).expanduser())

        meta = self.result["activity"]
        self.log("activity=%s phase=%s days_left=%s" % (meta["id"], meta["phase"], meta["days_left"]))
        if meta["phase"] == "ended":
            self.result["warnings"].append(
                "配置的活动期已结束（%s），请更新 assets/activity.json" % meta["period"])

        try:
            cookie_path = find_cookie_path(self.args.cookies)
        except FileNotFoundError as e:
            self.result["stage"] = "cookies"
            self.result["error"] = str(e)
            return self.result
        cookies = load_cookies(cookie_path)
        self.cookies = cookies
        self.cookie_path = cookie_path
        self.log("loaded %d cookies from %s" % (len(cookies), cookie_path))
        # 本地有效期只用来「提前提醒 / 解释失败原因」，不参与登录判定
        ttl = cookie_ttl(read_cookie_meta(cookie_path))
        self.result["cookie"] = ttl
        if ttl:
            self.log("cookie ttl: known=%s remain_days=%s expires=%s host=%s"
                     % (ttl.get("known"), ttl.get("remain_days"),
                        ttl.get("expires_text"), ttl.get("login_host")))
        if not cookies:
            self.result["stage"] = "cookies"
            self.result["error"] = "Cookie 为空或格式无法识别"
            return self.result

        if Path("/opt/playwright").exists():
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/playwright")
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            launch_kwargs = {
                "headless": not self.args.headful,
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            }
            exe = os.environ.get("CHROME_PATH") or os.environ.get("PUPPETEER_EXECUTABLE_PATH")
            if exe and Path(exe).exists():
                launch_kwargs["executable_path"] = exe
            browser = p.chromium.launch(**launch_kwargs)
            self.ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
            try:
                self.ctx.add_cookies(cookies)
            except Exception as e:
                self.log("add_cookies partially failed: %s" % e)
                self.result["notes"].append("部分 Cookie 注入失败: %s" % e)

            self.page = self.ctx.new_page()
            self.page.set_default_timeout(self.args.timeout * 1000)
            self.bind_page_handlers()
            try:
                self._run_steps(state_path)
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
        return self.result

    def _run_steps(self, state_path: Path):
        self.result["stage"] = "resolve-host"
        host = self.resolve_host()
        if not host:
            self.result["stage"] = "login"
            ttl = self.result.get("cookie") or {}
            if ttl.get("expired"):
                self.result["error"] = (
                    "Cookie 到期了：本地记录显示 %s 已于 %s 过期（%s），两个入口都不认。"
                    "请重新用 GetCookie.exe 抓一次。"
                    % (ttl.get("expires_name") or "关键 Cookie", ttl.get("expires_text"),
                       "已过期 %.0f 天" % abs(ttl.get("remain_days") or 0)))
            elif ttl.get("known") and ttl.get("remain_days") is not None:
                self.result["error"] = (
                    "两个入口都判定未登录（kuku.baidu.com / www.kukuai.cn），"
                    "但本地记录的有效期还没到（%s 到期，还剩 %.0f 天）——"
                    "多半是登录时没落在活动域上，或服务端提前失效。请重新用 GetCookie.exe 抓一次。"
                    % (ttl.get("expires_text"), ttl.get("remain_days")))
            else:
                self.result["error"] = ("两个入口都判定未登录（kuku.baidu.com / www.kukuai.cn）。"
                                        "Cookie 可能过期，或登录时没落在活动域上，请重新用 GetCookie.exe 抓一次。")
            self.result["logged_in"] = False
            try:
                self.page.goto(HOME_URL, wait_until="domcontentloaded", timeout=45000)
                self.page.wait_for_timeout(3000)
                self.shot("logged-out")
            except Exception:
                pass
            return
        self.base = host
        self.result["base_host"] = host
        self.result["url"] = host + "/app"
        self.log("resolved host: %s" % host)

        # 本地预测 vs 服务端结论不一致时，按服务端走，但把矛盾记下来
        ttl = self.result.get("cookie") or {}
        if ttl.get("known"):
            if ttl.get("expired"):
                self.result["notes"].append(
                    "本地记录显示 Cookie 已过期（%s），但服务端仍接受——以服务端为准，建议尽快重抓"
                    % ttl.get("expires_text"))
            elif (ttl.get("remain_days") or 99) <= 3:
                self.result["warnings"].append(
                    "Cookie 还有约 %.1f 天到期（%s 于 %s 到期），建议这几天抽空用 GetCookie.exe 重抓一次，别等跑失败"
                    % (ttl["remain_days"], ttl.get("expires_name") or "关键 Cookie", ttl.get("expires_text")))

        self.result["stage"] = "navigate"
        if not self.goto_home():
            self.result["error"] = "打开页面失败（重试 3 次都超时，检查网络或代理）"
            self.shot("goto-failed")
            return
        self.page.wait_for_timeout(4500)
        self.dismiss_dialogs()

        for attempt in range(3):
            if self.wait_ready(15):
                break
            self.log("page not rendered (attempt %d), reload" % (attempt + 1))
            self.goto_home()
            self.page.wait_for_timeout(6000)
            self.dismiss_dialogs()
        else:
            self.result["stage"] = "render"
            self.result["error"] = "页面多次重载仍未渲染出工作台（网络或 CDN 被拦）"
            self.shot("blank")
            return

        body = self.body_text()
        logged_in = self.detect_login(body)
        if logged_in is not True and self.base:
            # 入口已经用接口证明登录过；页面文案随版本变，不拿它否掉接口结论
            if logged_in is False:
                self.result["notes"].append("页面文案像未登录，但接口校验已登录（以接口为准）")
            logged_in = True
        self.result["logged_in"] = logged_in
        self.log("login state: %s" % logged_in)

        if any(k in body for k in RISK_KEYWORDS):
            self.result["stage"] = "risk"
            self.result["error"] = "页面出现验证码 / 风控提示，已停止自动操作，请手动完成"
            self.shot("risk")
            return
        if logged_in is False:
            self.result["stage"] = "login"
            self.result["error"] = "登录态失效（未检测到已登录），请重新导出 Cookie"
            self.shot("logged-out")
            return

        self.shot("home")

        # dry-run：只读接口，看两端进度
        if self.args.dry_run:
            self.result["stage"] = "dry-run"
            self.refresh_boards()
            if any(self.boards.values()):
                self.result["logged_in"] = True
            self.result["task_board"] = self.build_board()
            self.result["channels"] = self.summarize_channels()
            st = self.read_streak_points()
            self.result["signed_today"] = st.get("signed_today")
            self.result["streak_days"] = st.get("streak")
            self.result["notes"].append("dry-run：仅读取接口，未签到、未做任务")
            self.result["ok"] = True
            return

        # 1) 签到
        st = {}
        if not self.args.no_signin:
            st = self.do_signin()
        self.result["signed_today"] = st.get("signed_today")
        self.result["streak_days"] = st.get("streak")
        self.result["points"] = st.get("points")
        self.result["lottery_chances"] = st.get("lottery")
        self.result["next_node"] = next_node(self.act, st.get("streak"))
        if st.get("countdown"):
            self.result["activity"]["countdown"] = st["countdown"]

        # 2) 读两渠道进度（唯一可信来源）
        if not self.goto_home():
            self.result["warnings"].append("回工作台失败，任务未执行")
        else:
            self.page.wait_for_timeout(3500)
            self.dismiss_dialogs()
            self.refresh_boards()
            if not any(self.boards.values()):
                self.result["warnings"].append("读取任务接口失败，进度无法核验（不建议采信任何完成结论）")
            else:
                self.result["logged_in"] = True

            # 3) 任务
            if self.args.no_tasks:
                self.result["notes"].append("--only-signin：跳过每日任务")
            elif any(self.boards.values()):
                if any(k in self.flat() for k in RISK_KEYWORDS):
                    self.result["stage"] = "risk"
                    self.result["error"] = "出现验证码 / 风控提示，已停止任务"
                    self.shot("risk")
                    return
                self.run_tasks()

        # 4) 收尾：重新核验
        self.result["stage"] = "finalize"
        try:
            if self.page and not self.page.is_closed():
                try:
                    self.page.goto(self.base + "/app", wait_until="domcontentloaded", timeout=45000)
                except Exception as e:
                    self.log("final goto failed: %s" % str(e)[:70])
                try:
                    self.page.wait_for_timeout(2500)
                except Exception:
                    pass
                self.dismiss_dialogs()
                self.refresh_boards()
        except Exception as e:
            self.log("final refresh failed: %s" % e)
        self.result["task_board"] = self.build_board()
        self.result["channels"] = self.summarize_channels()
        if st.get("signed_today") is None and self.result["task_board"]:
            pass
        self.check_warnings(state_path, st)
        self.shot("final")
        signed = st.get("signed_today")
        if signed is True or self.args.dry_run or self.args.no_signin:
            # dry-run / --no-signin 本来就没打算签，不能拿这个判失败
            self.result["stage"] = "done"
            self.result["ok"] = True
        else:
            # 签到是这工具的第一职责。没签成却报 ok=True，就是把「跑完了」当成「做完了」
            self.result["stage"] = "signin-failed"
            self.result["ok"] = False
            self.result["error"] = (
                "签到未确认成功（signed_today=%s）。任务部分已跑完，但签到没落地，不能算完成。"
                "排查：① 活动页是否被风控 ② 看 outputs/ 里 signin-*.png ③ 加 --headful 本地复现"
                % signed)
        self.log("finished signed=%s boards=%s" % (
            st.get("signed_today"),
            {k: len(v) for k, v in (self.boards or {}).items()}))
        self.write_summary()


def main(argv=None):
    ap = argparse.ArgumentParser(description="库库AI 每日签到（无头 · Cookie 注入）· 2026Q4 期")
    ap.add_argument("--cookies", default="", help="Cookie 文件路径；默认依次找 " + "、".join(DEFAULT_COOKIE_PATHS))
    ap.add_argument("--out", default="outputs", help="截图与结果输出目录（默认 outputs）")
    ap.add_argument("--state", default="", help="连签状态文件（默认 ~/.kukuai/state.json）")
    ap.add_argument("--url", default="", help="手动指定入口（默认自动在 kuku.baidu.com / www.kukuai.cn 之间探测）")
    ap.add_argument("--host", default="", choices=["", "baidu", "kukuai"],
                    help="强制入口域名：baidu=kuku.baidu.com，kukuai=www.kukuai.cn")
    ap.add_argument("--headful", action="store_true", help="显示浏览器窗口（默认无头）")
    ap.add_argument("--dry-run", action="store_true", help="只读接口看进度，不签到不点任务")
    ap.add_argument("--no-signin", action="store_true", help="只清任务，不签到")
    ap.add_argument("--no-tasks", "--only-signin", dest="no_tasks", action="store_true",
                    help="只签到，不清任务")
    ap.add_argument("--tasks", default="", help="只跑指定任务: topic_chat,expert_chat,browse_square,upload_local,import_netdisk")
    ap.add_argument("--channels", default="", help="只做指定渠道: web,pc（默认两个都做）")
    ap.add_argument("--with-expert", action="store_true",
                    help="首次召唤专家时代勾《库库 AI 用户协议》并直接完成；不加则首次会提示需你本人勾选一次")
    ap.add_argument("--with-netdisk", action="store_true",
                    help="首次导入网盘文件时代点「确定授权」；不加则首次会跳过并提示需手动授权一次")
    ap.add_argument("--all", action="store_true",
                    help="一次做全：含专家（首次代勾协议）+ 网盘导入（若已授权）+ 上传占位文件")
    ap.add_argument("--no-upload", action="store_true", help="不上传占位文件到网盘")
    ap.add_argument("--timeout", type=int, default=30, help="单步超时秒数（默认 30）")
    ap.add_argument("--deadline", type=int, default=1200, help="整体硬超时秒数（默认 1200）")
    args = ap.parse_args(argv)
    if args.all:
        args.with_expert = True
        args.with_netdisk = True

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = out_dir / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    logfile = log_dir / ("kukuai_checkin_%s.log" % stamp)

    def log(msg: str):
        line = "[%s] %s" % (datetime.now(CN_TZ).isoformat(timespec="seconds"), msg)
        try:
            with open(logfile, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    log("start; out=%s; url=%s; dry_run=%s" % (out_dir, args.url or "auto", args.dry_run))

    # 硬超时：页面卡死时也要把结论吐出来，不能静默挂住
    def _watchdog(seconds, logfile):
        def kill():
            try:
                with open(logfile, "a", encoding="utf-8") as f:
                    f.write("[watchdog] hard timeout after %ds\n" % seconds)
            except Exception:
                pass
            print(json.dumps({
                "ok": False, "stage": "timeout",
                "error": "脚本超过 %d 秒未结束，已强制中止（多为页面卡在加载/网络异常）；日志：%s"
                         % (seconds, logfile),
                "log": str(logfile),
            }, ensure_ascii=False, indent=2))
            try:
                sys.stdout.flush()
            except Exception:
                pass
            os._exit(3)

        t = threading.Timer(seconds, kill)
        t.daemon = True
        t.start()
        return t

    _watchdog(int(getattr(args, "deadline", 1200) or 1200), logfile)

    try:
        act = load_activity()
        # 渠道过滤
        if args.channels:
            wanted = {x.strip().lower() for x in args.channels.split(",") if x.strip()}
            alias = {"web": "kuku_signin_30_web", "网页端": "kuku_signin_30_web",
                     "pc": "kuku_signin_30_pc", "客户端": "kuku_signin_30_pc"}
            keep = {alias.get(w, w) for w in wanted}
            act["channels"] = [c for c in act.get("channels", []) if c["key"] in keep] or act.get("channels")
        runner = Runner(args, act, log)
        result = runner.run()
        if result.get("ok") and not result.get("summary"):
            runner.write_summary()
    except Exception as e:
        result = {"ok": False, "stage": "fatal",
                  "error": "%s: %s" % (type(e).__name__, e)}

    result["log"] = str(logfile)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
