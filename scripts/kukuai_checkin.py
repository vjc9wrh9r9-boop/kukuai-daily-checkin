#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""库库AI 每日签到 / 每日任务自动化（云端 · 无头模式）· 2026Q4 期。

适配活动：「每日签到得网盘SVIP月卡 · 做任务抽好礼 赢苹果笔记本」
活动周期：2026-10-21 ~ 2026-12-04（连签 30 天必得网盘SVIP月卡）
活动配置：assets/activity.json（换期只改这个文件，脚本无需动）

线上实测结构（2026-10-27 校准）：
    - 签到卡在工作台左下角，[data-testid="signin-promo"]，未登录标题「登录领取网盘SVIP」、CTA「登录领奖」
    - 点签到卡标题会打开「任务中心」弹窗，真正的内容在 iframe 里：
          iframe.signin-center-iframe → kuku.baidu.com/operation/activitys/kukuPcSignAct/main
      iframe 内才有连签日历、立即签到按钮、6 项任务与「去完成」
    - 该 iframe 地址不能直接打开（body 为空），必须从应用内点开
    - 页面加载时会自动弹出活动/会员弹窗遮罩，会拦掉真实鼠标点击，脚本会先关它并退化为 DOM 点击

用法:
    python kukuai_checkin.py --cookies ~/.kukuai/cookies.json --dry-run --probe-entry
    python kukuai_checkin.py --cookies ~/.kukuai/cookies.json
    python kukuai_checkin.py --cookies ~/.kukuai/cookies.json --only-signin
    python kukuai_checkin.py --cookies ~/.kukuai/cookies.json --tasks topic_chat,browse_square

Cookie 支持三种格式（自动识别）:
    1) Playwright/Puppeteer 导出的 JSON 数组: [{"name":"BDUSS","value":"...","domain":".kukuai.cn"}]
    2) {"cookies": [...]} 或 {"name": "value", ...} 映射
    3) 原始 Cookie 头字符串: "BDUSS=xxx; STOKEN=yyy"

注意:
    - 站点是前端渲染 SPA + iframe，按钮文案随时可能改版。首次运行请先 --dry-run 探测结构，
      必要时改 assets/activity.json 的 selectors / signin_texts / tasks。
    - 遇到验证码 / 滑块 / 风控会立即中止并如实报告，不尝试绕过。
    - 进度日志只写文件（<out>/log/），stdout 仅输出最终 JSON 结果。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME_URL = "https://www.kukuai.cn/"
CN_TZ = timezone(timedelta(hours=8))

SKILL_ROOT = Path(__file__).resolve().parent.parent
ACTIVITY_FILE = SKILL_ROOT / "assets" / "activity.json"

DEFAULT_COOKIE_PATHS = [
    "~/.kukuai/cookies.json",
    "~/.kukuai/cookies.txt",
    "uploads/kukuai_cookies.json",
]
DEFAULT_STATE_PATH = "~/.kukuai/state.json"

RISK_KEYWORDS = [
    "验证码", "拖动滑块", "滑块验证", "安全验证", "人机验证",
    "请完成验证", "异常访问", "操作过于频繁", "风险提示", "环境异常",
]
SUCCESS_KEYWORDS = ["签到成功", "领取成功", "已领取", "积分+10", "签到完成", "已签到"]

# 热门话题任务需要 3 次对话
CHAT_PROMPTS = [
    "最近有哪些值得关注的 AI 行业热门话题？简单说三条就好。",
    "帮我推荐三个适合秋天去的国内旅行目的地，各一句话理由。",
    "用三句话总结一下今年办公类 AI 工具的主要变化。",
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
# 连签状态（跨天持久化，用于断签预警与节点提醒）
# --------------------------------------------------------------------------- #
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
    def __init__(self, args, activity: dict, logfile, log):
        self.args = args
        self.act = activity
        self.sel = activity.get("selectors", {})
        self.log = log
        self.logfile = logfile
        self.page = None
        self.ctx = None
        self._pending_upload = None
        self.home_state = {}
        self.stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.out_dir = Path(args.out).expanduser()
        self.result = {
            "ok": False,
            "stage": "init",
            "activity": activity_meta(activity),
            "url": args.url,
            "activity_url": None,
            "logged_in": None,
            "dry_run": bool(args.dry_run),
            "signed_today": None,
            "streak_days": None,
            "next_node": None,
            "points": None,
            "lottery_chances": None,
            "tasks": [],
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

    def task_frame(self):
        """任务中心在 iframe 内；iframe 地址形如 .../activitys/kukuPcSignAct/main"""
        hint = self.act.get("frame_url_hint") or "kukuPcSignAct"
        try:
            for f in self.page.frames:
                if hint in (f.url or ""):
                    return f
        except Exception:
            pass
        return None

    def root(self):
        return self.task_frame() or self.page

    def text(self) -> str:
        chunks = []
        fr = self.task_frame()
        if fr is not None:
            try:
                chunks.append(fr.inner_text("body") or "")
            except Exception:
                pass
        try:
            chunks.append(self.page.inner_text("body") or "")
        except Exception:
            pass
        return "\n".join(chunks)

    def flat(self) -> str:
        return re.sub(r"\s+", " ", self.text())

    def loc_text(self, sel) -> str:
        if not sel:
            return ""
        try:
            loc = self.page.locator(sel)
            if loc.count():
                return re.sub(r"\s+", " ", loc.first.inner_text() or "").strip()
        except Exception:
            pass
        return ""

    def loc_click(self, sel, timeout=4000) -> bool:
        if not sel:
            return False
        try:
            loc = self.page.locator(sel)
            if not loc.count() or not loc.first.is_visible():
                return False
            try:
                loc.first.click(timeout=timeout)
            except Exception as e:
                # 遮罩会吃掉真实鼠标事件，退化为 DOM 级 click
                self.log("normal click blocked (%s), DOM click: %s" % (str(e)[:60], sel))
                self.result["notes"].append("遮罩拦截，改用 DOM 级点击: %s" % sel)
                loc.first.evaluate("e => e.click()")
            return True
        except Exception as e:
            self.log("loc_click %s failed: %s" % (sel, e))
            return False

    def click_texts(self, texts, exact=False, timeout=4000, max_scan=4):
        """先在任务中心 iframe 里找，再找主页面；被遮罩拦住时退化 DOM 点击。"""
        containers = []
        fr = self.task_frame()
        if fr is not None:
            containers.append(fr)
        containers.append(self.page)
        for t in texts:
            for c in containers:
                for by in ("role", "text"):
                    try:
                        loc = (c.get_by_role("button", name=t, exact=exact)
                               if by == "role" else c.get_by_text(t, exact=exact))
                        n = min(loc.count(), max_scan)
                    except Exception:
                        n = 0
                    for i in range(n):
                        el = loc.nth(i)
                        try:
                            if not el.is_visible():
                                continue
                            try:
                                el.click(timeout=timeout)
                            except Exception as ce:
                                self.log("click '%s' blocked (%s), DOM click" % (t, str(ce)[:60]))
                                el.evaluate("e => e.click()")
                            self.log("clicked[%s/%s] %s" % (by, type(c).__name__, t))
                            return t
                        except Exception as e:
                            self.log("click '%s'[%s/%d] failed: %s" % (t, by, i, e))
                            continue
        return None

    def dismiss_blockers(self):
        """关掉挡在页面上的活动/会员弹窗，否则点击会被遮罩吃掉。

        实测：首页加载会弹一次，打开任务中心后可能再弹一次（同一个
        activity-dialog，底部有个圆形 ✕ = activity-dialog-close）。
        这里只点明确的关闭按钮，不发 Escape —— Escape 可能把任务中心一起关掉。
        """
        closed = []
        for sel in [self.sel.get("activity_dialog_close"),
                    '[class*="activity-dialog-close"]']:
            if not sel:
                continue
            try:
                loc = self.page.locator(sel)
                if loc.count() and loc.first.is_visible():
                    try:
                        loc.first.click(timeout=2000)
                    except Exception:
                        loc.first.evaluate("e => e.click()")
                    closed.append(sel)
                    self.page.wait_for_timeout(700)
            except Exception:
                pass
        if closed:
            self.log("dismissed blockers: %s" % closed)
            self.result["actions"].append({"closed_overlays": closed})

    def bind_page_handlers(self):
        """文件选择器自动接管 + 原生 alert 自动确认，避免 headless 卡死。"""
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
        path = Path(tempfile.gettempdir()) / ("kukuai-task-%s.txt" % self.stamp)
        try:
            path.write_text(
                "库库AI 每日任务占位文件\n生成时间：%s\n"
                % datetime.now(CN_TZ).isoformat(timespec="seconds"),
                encoding="utf-8",
            )
        except Exception as e:
            self.log("write probe file failed: %s" % e)
        return path

    # ---------------- 登录态 ----------------
    def detect_login(self, body: str = ""):
        """先判未登录标记，再判已登录标记。

        实测坑：未登录时首页同样存在 [data-testid="user-profile-trigger"]，
        早期版本据此误判为已登录。真实信号是文案「登录领网盘会员」
        「登录领取网盘SVIP」「登录后领取连签奖励」与 CTA「登录领奖」。
        """
        flat = re.sub(r"\s+", " ", body or self.text())
        cta = self.loc_text(self.sel.get("signin_cta"))

        pos = self.act.get("login_positive_markers") or []
        neg = list(self.act.get("login_negative_markers") or [])

        if any(k and k in flat for k in pos):
            return True
        if any(k and k in flat for k in neg):
            return False
        # 已登录时签到卡 CTA 是「去抽会员」这类文案，只有含「登录」才是未登录信号
        if cta and "登录" in cta:
            return False
        if cta:
            return True
        try:
            if self.page.locator('[data-testid="user-profile-trigger"] img').count() > 0:
                return True
        except Exception:
            pass
        return None

    # ---------------- 任务中心 ----------------
    def open_task_center(self) -> bool:
        """点签到卡标题打开任务中心弹窗（内容在 iframe 里）。"""
        if self.task_frame() is not None:
            return True

        # 1) 点签到卡标题（实测可打开任务中心）
        for sel in [self.sel.get("signin_title"), self.sel.get("signin_card")]:
            if self.loc_click(sel, timeout=5000):
                self.page.wait_for_timeout(3500)
                fr = self.task_frame()
                if fr is not None:
                    self.result["activity_url"] = fr.url
                    self.result["actions"].append({"opened_task_center": sel})
                    return True
                self.log("clicked %s but no iframe" % sel)

        # 2) 顶部活动横幅
        if self.loc_click(self.sel.get("activity_banner"), timeout=4000):
            self.page.wait_for_timeout(3500)
            fr = self.task_frame()
            if fr is not None:
                self.result["activity_url"] = fr.url
                self.result["actions"].append({"opened_task_center": "activity_banner"})
                return True

        # 3) 文案兜底
        hit = self.click_texts(self.act.get("entry_texts", []), timeout=4000)
        if hit:
            self.page.wait_for_timeout(3500)
            fr = self.task_frame()
            if fr is not None:
                self.result["activity_url"] = fr.url
                self.result["actions"].append({"opened_task_center": hit})
                return True
        return False

    def ensure_task_center(self) -> bool:
        fr = self.task_frame()
        if fr is not None:
            self.dismiss_blockers()  # 打开后会员弹窗可能又冒出来
            try:
                if "做任务" in (fr.inner_text("body") or ""):
                    return True
            except Exception:
                pass
        self.dismiss_blockers()
        if self.open_task_center():
            self.dismiss_blockers()
            return True
        # 兜底：做完对话/浏览后页面状态不明，回首页重新开一次
        try:
            self.log("reopen failed, fallback to home")
            self.page.goto(self.args.url, wait_until="domcontentloaded")
            self.page.wait_for_timeout(4500)
            self.dismiss_blockers()
            if self.open_task_center():
                self.dismiss_blockers()
                return True
        except Exception as e:
            self.log("home fallback failed: %s" % e)
        return False

    def has_activity_markers(self) -> bool:
        flat = self.flat()
        markers = self.act.get("activity_markers", [])
        return sum(1 for k in markers if k in flat) >= 2

    def discover_links(self):
        found = []
        try:
            hrefs = self.page.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.href).filter(Boolean)"
            )
        except Exception:
            hrefs = []
        for h in hrefs:
            if re.search(r"(comp|activity|sign|checkin|task)", h, re.I) and h not in found:
                found.append(h)
        fr = self.task_frame()
        self.result["notes"].append("任务中心 iframe: %s" % (fr.url if fr else "未打开"))
        self.result["notes"].append("页面候选活动链接: %s" % (found[:8] or "无"))
        return found

    # ---------------- 状态解析 ----------------
    def read_state(self) -> dict:
        flat = self.flat()
        st = {}

        # 注意：任务日历里的节点标签就是「连签3天 / 连签7天」，不能拿它当连签天数
        m = (re.search(r"已连签\s*(\d+)\s*天", flat)
             or re.search(r"已签\s*(\d+)\s*天", flat)
             or re.search(r"已连续签到\s*(\d+)\s*天", flat))
        if m:
            st["streak"] = int(m.group(1))

        m = re.search(r"再签\s*(\d+)\s*天", flat)
        if m:
            st["need_for_node"] = int(m.group(1))

        m = re.search(r"距离活动结束\s*([0-9]+\s*天[0-9:：\s]*)", flat)
        if m:
            st["countdown"] = m.group(1).strip()

        cta = self.loc_text(self.sel.get("signin_cta"))
        title = self.loc_text(self.sel.get("signin_title"))
        btn_txt = self.frame_text(self.sel.get("signin_btn"))
        st["cta_text"] = cta or None
        st["card_title"] = title or None
        st["sign_btn_text"] = btn_txt or None
        st["card_present"] = bool(cta or title)
        st["task_center_open"] = self.task_frame() is not None

        signed = any(k in flat for k in (self.act.get("signed_markers") or []))
        if cta:
            if any(k in cta for k in ["已签", "明天再来", "明日再来", "已领"]):
                signed = True
            elif any(k in cta for k in ["签到", "领奖", "领取", "立即"]):
                signed = False
        # 任务中心里的签到按钮文案最权威
        if btn_txt:
            if any(k in btn_txt for k in ["已签", "明天再来", "明日再来", "已领"]):
                signed = True
            elif any(k in btn_txt for k in ["签到", "领奖", "领取", "立即"]):
                signed = False
        st["signed_today"] = signed

        # 积分：优先显式标签；兜底排除「积分+5」「10.28」这类干扰
        m = (re.search(r"(?:积分余额|库库积分余额|我的积分|剩余积分)\s*[:：]?\s*([\d,]+)", flat)
             or re.search(r"(?<![\d.+])([\d,]{2,9})\s*积分(?!\s*[\+＋])", flat))
        if m:
            try:
                st["points"] = int(m.group(1).replace(",", ""))
            except ValueError:
                pass

        m = (re.search(r"抽奖次数\s*[:：]?\s*(\d+)", flat)
             or re.search(r"(?<![\d.])(\d+)\s*次抽奖", flat)
             or re.search(r"去抽奖\s*[（(]?\s*(\d+)", flat))
        if m:
            try:
                st["lottery"] = int(m.group(1))
            except ValueError:
                pass

        prog = {}
        for m in re.finditer(r"([^\s（(]{2,26})\s*[（(]\s*(\d+)\s*/\s*(\d+)\s*[)）]", flat):
            prog[m.group(1)] = "%s/%s" % (m.group(2), m.group(3))
        tasks = []
        for t in self.act.get("tasks", []):
            name = t["name"]
            hit = None
            # 先精确匹配，避免「邀请新用户下载登录库库PC端」与「下载并登录库库PC客户端」互相串
            for k, v in prog.items():
                if k == name or k.startswith(name):
                    hit = v
                    break
            if hit is None:
                for k, v in prog.items():
                    if name in k:
                        hit = v
                        break
            tasks.append({
                "key": t["key"],
                "name": name,
                "reward": t.get("reward"),
                "progress": hit,
                "present": name in flat,
            })
        st["tasks"] = tasks
        return st

    # ---------------- 签到 ----------------
    def do_signin(self) -> bool:
        self.result["stage"] = "signin"
        self.dismiss_blockers()

        before = self.read_state()
        if before.get("signed_today"):
            self.result["actions"].append({"signin": "already"})
            self.log("already signed today (btn=%s cta=%s)"
                     % (before.get("sign_btn_text"), before.get("cta_text")))
            return True

        # 优先在任务中心里点（button.pc-sign-btn 才是活动签到按钮）
        self.ensure_task_center()
        before = self.read_state()
        if before.get("signed_today"):
            self.result["actions"].append({"signin": "already"})
            self.log("already signed today (btn=%s)" % before.get("sign_btn_text"))
            return True

        hit = None
        fr = self.task_frame()
        btn_sel = self.sel.get("signin_btn")
        if fr is not None and btn_sel:
            try:
                loc = fr.locator(btn_sel)
                if loc.count() and loc.first.is_visible():
                    txt = (loc.first.inner_text() or "").strip()
                    try:
                        loc.first.click(timeout=5000)
                    except Exception as ce:
                        self.log("sign btn click blocked (%s), DOM click" % str(ce)[:60])
                        loc.first.evaluate("e => e.click()")
                    hit = "pc-sign-btn(%s)" % txt
            except Exception as e:
                self.log("sign btn click failed: %s" % e)

        if not hit:
            # 已签到时签到按钮可能整个消失，页面只留「今日已签」文案；
            # 此时不能再按「签到」二字乱点（会点到侧栏导航），直接判已签
            if any(k in self.flat() for k in (self.act.get("signed_markers") or [])):
                self.result["actions"].append({"signin": "already(text)"})
                self.log("sign button absent but signed marker found")
                return True
            hit = self.click_texts(self.act.get("signin_texts", []), timeout=5000)
        if not hit and self.loc_click(self.sel.get("signin_cta"), timeout=5000):
            hit = "signin_cta"
        if not hit:
            self.result["warnings"].append(
                "未找到签到按钮（任务中心按钮、签到卡 CTA 与文案均未命中），页面可能改版，请查看截图")
            return False

        self.result["actions"].append({"signin_clicked": hit})
        self.page.wait_for_timeout(3500)
        self.dismiss_blockers()

        after = self.read_state()
        flat = self.flat()
        ok = bool(after.get("signed_today")) or any(k in flat for k in SUCCESS_KEYWORDS)
        if not ok:
            self.result["warnings"].append(
                "点击签到后未检测到成功标记（按钮=%s），请以截图为准确认"
                % (after.get("sign_btn_text") or after.get("cta_text") or "未知"))
        return ok

    def frame_text(self, sel) -> str:
        fr = self.task_frame()
        if fr is None or not sel:
            return ""
        try:
            loc = fr.locator(sel)
            if loc.count():
                return re.sub(r"\s+", " ", loc.first.inner_text() or "").strip()
        except Exception:
            pass
        return ""

    def task_card(self, name: str):
        """按任务名找卡片：.pc-kuku-task-card > .pc-kuku-task-card__title"""
        fr = self.task_frame()
        if fr is None:
            return None
        sel = self.sel.get("task_card") or ".pc-kuku-task-card"
        title_sel = self.sel.get("task_card_title") or ".pc-kuku-task-card__title"
        try:
            cards = fr.locator(sel)
            for i in range(cards.count()):
                card = cards.nth(i)
                try:
                    t = (card.locator(title_sel).first.inner_text() or "").strip()
                except Exception:
                    continue
                if name in t or t in name:
                    return card
        except Exception as e:
            self.log("task_card '%s' failed: %s" % (name, e))
        return None

    def card_state(self, card) -> str:
        """任务卡右侧是图片按钮：btn_todo=去完成 / btn_invite=邀请好友 / 其它多为已完成。"""
        btn_sel = self.sel.get("task_card_btn") or ".pc-kuku-task-card__btn"
        try:
            img = card.locator(btn_sel).first
            src = (img.get_attribute("src") or "").lower()
        except Exception:
            return "unknown"
        if not src:
            return "unknown"
        if "todo" in src:
            return "todo"
        if "invite" in src:
            return "invite"
        if any(k in src for k in ("done", "finish", "complete", "received", "signed")):
            return "done"
        return "unknown"

    # ---------------- 任务 ----------------
    def task_action(self, name: str, actions=None):
        """点任务卡的图片按钮。返回 todo 表示已点，invite/done/unknown 表示跳过。"""
        card = self.task_card(name)
        if card is None:
            self.log("task card not found: %s" % name)
            return None
        state = self.card_state(card)
        self.log("task '%s' card state=%s" % (name, state))
        if state in ("invite", "done"):
            return state
        action_sel = self.sel.get("task_card_action") or ".pc-kuku-task-card__action"
        for sel in [action_sel, self.sel.get("task_card_btn")]:
            if not sel:
                continue
            try:
                el = card.locator(sel).first
                try:
                    el.click(timeout=4000)
                except Exception as ce:
                    self.log("task btn click blocked (%s), DOM click" % str(ce)[:60])
                    el.evaluate("e => e.click()")
                self.page.wait_for_timeout(1800)
                self.log("task action clicked for '%s'" % name)
                return "clicked"
            except Exception as e:
                self.log("task action '%s' via %s failed: %s" % (name, sel, e))
        return None

    def chat_input(self):
        for sel in ["textarea", "[contenteditable='true']", "div[role='textbox']",
                    "input[type='text']"]:
            try:
                loc = self.page.locator(sel)
                if not loc.count():
                    continue
                if loc.first.is_visible():
                    return loc.first
            except Exception:
                continue
        return None

    def send_chat(self, prompt: str, wait_ms: int = 12000) -> bool:
        el = self.chat_input()
        if el is None:
            self.log("chat input not found")
            return False
        try:
            el.click(timeout=4000)
            el.fill(prompt)
            self.page.wait_for_timeout(400)
            self.page.keyboard.press("Enter")
            self.page.wait_for_timeout(wait_ms)
            self.result["actions"].append({"chat_sent": prompt[:28]})
            self.log("chat sent: %s" % prompt[:28])
            return True
        except Exception as e:
            self.log("send_chat failed: %s" % e)
            return False

    def task_chat(self, task) -> str:
        """点一次「去完成」进对话页，按任务进度剩余次数连发（不要每条都重开任务中心）。"""
        if not self.ensure_task_center():
            return "skipped"
        limit = task.get("limit") or 1
        remaining = limit
        prog = None
        for t in self.read_state().get("tasks", []):
            if t.get("key") == task.get("key") and t.get("progress"):
                prog = t["progress"]
                break
        if prog:
            try:
                n, m = [int(x) for x in prog.split("/")]
                remaining = max(0, m - n)
            except ValueError:
                remaining = limit
        if remaining == 0:
            return "今日已完成(%s)" % prog

        res = self.task_action(task["name"])
        if res == "done":
            return "今日已完成"
        if res == "invite":
            return "需邀请好友，跳过"
        self.page.wait_for_timeout(2500)
        done = 0
        for i in range(remaining):
            if self.send_chat(CHAT_PROMPTS[i % len(CHAT_PROMPTS)]):
                done += 1
            else:
                break
        if not done:
            return "skipped"
        return "对话 %d 条（原进度 %s）" % (done, prog or "0/%d" % limit)

    def task_expert(self, task) -> str:
        """点「去完成」→ 跳 #/workbench/expert 专家页 → 点第一张卡的「召唤」→ 发第一句话。"""
        if not self.ensure_task_center():
            return "skipped"
        res = self.task_action(task["name"])
        if res == "done":
            return "今日已完成"
        if res == "invite":
            return "需邀请好友，跳过"
        self.page.wait_for_timeout(3500)

        summoned = False
        card_sel = self.sel.get("expert_card") or "article.expert-card"
        for sel in [card_sel, "[class*='expert-card']", "[class*='expertCard']"]:
            try:
                card = self.page.locator(sel).first
                if not card.count():
                    continue
                btn = card.get_by_role("button", name="召唤")
                if btn.count():
                    try:
                        btn.first.click(timeout=4000)
                    except Exception:
                        btn.first.evaluate("e => e.click()")
                    summoned = True
                    self.log("summoned expert via %s" % sel)
                    break
            except Exception as e:
                self.log("summon via %s failed: %s" % (sel, e))
        if not summoned:
            if self.click_texts(["召唤"], exact=True, timeout=4000):
                summoned = True
        if not summoned:
            return "未找到「召唤」按钮"

        self.page.wait_for_timeout(2500)
        # 召唤会弹「使用提醒 / 用户协议」确认框：勾同意 → 继续使用
        agreed = False
        for t in ["我已阅读并同意", "我已阅读并同意本协议", "同意"]:
            try:
                loc = self.page.get_by_text(t, exact=True)
                if loc.count() and loc.first.is_visible():
                    loc.first.click(timeout=2500)
                    agreed = True
                    self.log("agreed expert disclaimer via '%s'" % t)
                    break
            except Exception:
                continue
        if agreed:
            self.click_texts(["继续使用", "确定", "确认"], exact=True, timeout=3000)
            self.page.wait_for_timeout(3000)
            self.result["notes"].append("已代点专家使用协议的「我已阅读并同意」")

        self.page.wait_for_timeout(1500)
        ok = self.send_chat(EXPERT_PROMPT)
        return "已召唤专家并发起对话" if ok else "召唤成功但未找到输入框"

    def task_square(self, task) -> str:
        if not self.ensure_task_center():
            return "skipped"
        before_url = self.page.url
        res = self.task_action(task["name"])
        if res == "done":
            return "今日已完成"
        if res == "invite":
            return "需邀请好友，跳过"
        self.page.wait_for_timeout(2500)
        navigated = self.page.url != before_url
        if res is None or (not navigated and "知识广场" not in self.flat()):
            self.click_texts(["知识广场"], timeout=3500)
            self.page.wait_for_timeout(2500)
            navigated = self.page.url != before_url
        self.page.wait_for_timeout(12000)  # 任务要求停留 10s
        self.log("stayed 12s, navigated=%s" % navigated)
        return "已停留 12s" if navigated else "已等待 12s（未确认已进入知识广场）"

    def run_tasks(self):
        self.result["stage"] = "tasks"
        wanted = None
        if self.args.tasks:
            wanted = {x.strip() for x in self.args.tasks.split(",") if x.strip()}
        handlers = {
            "chat": self.task_chat,
            "expert": self.task_expert,
            "square": self.task_square,
        }
        results = []
        for task in self.act.get("tasks", []):
            key = task["key"]
            mode = task.get("auto", "manual")
            item = {"key": key, "name": task["name"], "auto": mode, "result": None}
            if mode == "manual":
                item["result"] = "手动（需真人操作，跳过）"
            elif wanted is not None and key not in wanted:
                item["result"] = "跳过（未在 --tasks 中指定）"
            else:
                fn = handlers.get(mode)
                try:
                    item["result"] = fn(task) if fn else "无处理器"
                except Exception as e:
                    item["result"] = "异常: %s" % e
                    self.log("task %s error: %s" % (key, e))
                self.result["actions"].append({"task": key, "result": item["result"]})
            results.append(item)
        self.result["tasks"] = results

    # ---------------- 收尾 ----------------
    def finish_state(self):
        st = self.read_state()
        home = self.home_state or {}
        # 签到是既成事实：只要任一阶段读到已签，就不能因为后来页面跳走而报未签
        if home.get("signed_today") or st.get("signed_today"):
            st["signed_today"] = True
        if st.get("streak") is None and home.get("streak") is not None:
            st["streak"] = home["streak"]
        if st.get("points") is None and home.get("points") is not None:
            st["points"] = home["points"]
        self.result["signed_today"] = st.get("signed_today")
        self.result["streak_days"] = st.get("streak")
        self.result["points"] = st.get("points")
        self.result["lottery_chances"] = st.get("lottery")
        self.result["next_node"] = next_node(self.act, st.get("streak"))
        if st.get("countdown"):
            self.result["activity"]["countdown"] = st["countdown"]
        return st

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
                    "距上次成功签到已 %d 天，连签可能已中断（规则：断签清零）" % (today - pd).days
                )

        if not st.get("signed_today"):
            self.result["warnings"].append("今日尚未确认签到成功，请人工复核截图")

        node = self.result.get("next_node")
        if node and node["need"] <= 1:
            self.result["warnings"].append(
                "再签 %d 天即可解锁「%s」"
                % (node["need"], node.get("reward") or ("连签%d天" % node["day"]))
            )

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
        if r.get("lottery_chances") is not None:
            lines.append("- 抽奖次数：%s" % r["lottery_chances"])
        if r.get("tasks"):
            lines.append("")
            lines.append("| 任务 | 结果 |")
            lines.append("| --- | --- |")
            for t in r["tasks"]:
                lines.append("| %s | %s |" % (t["name"], t.get("result") or "-"))
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
            self.result["summary"] = str(path)
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
        self.log("loaded %d cookies from %s" % (len(cookies), cookie_path))
        if not cookies:
            self.result["stage"] = "cookies"
            self.result["error"] = "Cookie 为空或格式无法识别"
            return self.result

        # 云端镜像常用 /opt/playwright；本机没有该目录时交给 Playwright 默认路径
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
        self.result["stage"] = "navigate"
        try:
            self.page.goto(self.args.url, wait_until="domcontentloaded")
        except Exception as e:
            self.result["error"] = "打开页面失败: %s" % e
            self.log("goto failed: %s" % e)
            return
        self.page.wait_for_timeout(4500)
        self.dismiss_blockers()
        self.page.wait_for_timeout(800)

        body = self.text()
        logged_in = self.detect_login(body)
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

        if self.args.dry_run:
            self.result["stage"] = "dry-run"
            st = self.read_state()
            self.result["dry_run_state"] = st
            self.result["signed_today"] = st.get("signed_today")
            self.result["notes"].append(
                "签到卡：标题=%s / CTA=%s / 已签=%s"
                % (st.get("card_title") or "未找到", st.get("cta_text") or "未找到",
                   st.get("signed_today")))
            if self.args.probe_entry:
                if self.open_task_center():
                    self.page.wait_for_timeout(1500)
                    st2 = self.read_state()
                    self.result["dry_run_state"] = st2
                    self.result["notes"].append(
                        "任务中心已打开，识别到任务 %d/%d"
                        % (sum(1 for t in st2["tasks"] if t["present"]), len(st2["tasks"])))
                    self.shot("dry-run-task-center")
                else:
                    self.result["notes"].append("任务中心未能打开")
            self.discover_links()
            self.result["ok"] = True
            self.result["notes"].append("dry-run：仅探测，未签到、未点任务")
            self.result["notes"].append("页面文本片段: " + self.flat()[:300])
            return

        # 1) 签到（优先在任务中心内点，卡片 CTA 兜底）
        if not self.args.no_signin:
            self.do_signin()
            self.shot("signed")
        self.home_state = self.read_state()
        self.log("state after signin: %s" % json.dumps(
            {k: v for k, v in self.home_state.items() if k != "tasks"}, ensure_ascii=False))

        # 2) 任务
        if not self.args.no_tasks:
            if not self.ensure_task_center():
                self.result["warnings"].append(
                    "未能打开任务中心，任务全部跳过（签到不受影响）")
                self.shot("no-task-center")
            else:
                self.shot("task-center")
                if any(k in self.flat() for k in RISK_KEYWORDS):
                    self.result["stage"] = "risk"
                    self.result["error"] = "任务中心出现验证码 / 风控提示，已停止"
                    self.shot("risk")
                    return
                self.run_tasks()

        # 3) 收尾
        self.result["stage"] = "finalize"
        if not self.ensure_task_center():
            try:
                self.page.goto(self.args.url, wait_until="domcontentloaded")
                self.page.wait_for_timeout(4000)
            except Exception:
                pass
        st = self.finish_state()
        self.check_warnings(state_path, st)
        self.shot("final")
        self.result["stage"] = "done"
        self.result["ok"] = True
        self.log("finished ok=True signed=%s streak=%s" % (st.get("signed_today"), st.get("streak")))
        self.write_summary()


def main(argv=None):
    ap = argparse.ArgumentParser(description="库库AI 每日签到（云端/无头，Cookie 注入）· 2026Q4 期")
    ap.add_argument("--cookies", default="", help="Cookie 文件路径；默认依次找 " + "、".join(DEFAULT_COOKIE_PATHS))
    ap.add_argument("--out", default="outputs", help="截图与结果输出目录（默认 outputs）")
    ap.add_argument("--log", default="", help="日志目录（默认 <out>/log）")
    ap.add_argument("--state", default="", help="连签状态文件（默认 ~/.kukuai/state.json）")
    ap.add_argument("--url", default=HOME_URL, help="入口地址，默认库库AI 官网（活动页在 iframe 内，不能直接填 iframe 地址）")
    ap.add_argument("--headful", action="store_true", help="显示浏览器窗口（默认无头）")
    ap.add_argument("--dry-run", action="store_true", help="只校验登录态并探测结构，不签到不点任务")
    ap.add_argument("--probe-entry", action="store_true", help="dry-run 时额外打开任务中心并解析状态")
    ap.add_argument("--no-signin", action="store_true", help="只清任务，不签到")
    ap.add_argument("--no-tasks", "--only-signin", dest="no_tasks", action="store_true",
                    help="只签到，不清任务")
    ap.add_argument("--tasks", default="", help="只跑指定任务，逗号分隔: topic_chat,expert_chat,browse_square")
    ap.add_argument("--timeout", type=int, default=30, help="单步超时秒数（默认 30）")
    args = ap.parse_args(argv)

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = Path(args.log).expanduser() if args.log else (out_dir / "log")
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

    log("start; out=%s; url=%s; dry_run=%s" % (out_dir, args.url, args.dry_run))

    try:
        act = load_activity()
        runner = Runner(args, act, logfile, log)
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
