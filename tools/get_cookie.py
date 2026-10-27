#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""库库AI Cookie 自动抓取工具。

双击 获取Cookie.exe：
    用你的默认浏览器打开一个独立窗口 → 你用百度账号登录 → 自动保存 + 复制到剪贴板

原理：按系统里登记的默认浏览器启动一个临时配置的窗口，打开远程调试端口，
     登录后通过 DevTools 协议读出 Cookie。不碰日常浏览器数据，不装扩展，不上传。

命令行：
    --port 9222      调试端口
    --no-browser     不自动启动浏览器
    --out <路径>     Cookie 输出路径（默认 ~/.kukuai/cookies.json）
    --timeout 600    等待登录秒数
    --no-clipboard   不复制到剪贴板
    --selftest       只做环境检查
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOST = "127.0.0.1"
TARGET_URL = "https://www.kukuai.cn/"
COOKIE_HOSTS = ["https://www.kukuai.cn/", "https://kuku.baidu.com/", "https://baidu.com/"]
DEFAULT_OUT = "~/.kukuai/cookies.json"

# 默认浏览器拿不到时按顺序退化的候选
FALLBACK_BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

LAUNCH_ARGS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--remote-allow-origins=*",
    "--start-maximized",
]


# ---------------------------------------------------------------- 基础
def _setup_console():
    """打包成 exe 后控制台默认 GBK，中文会乱码，强制切 UTF-8。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def info(msg):
    print(msg, flush=True)


def popup(title, text):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
        return
    except Exception:
        pass
    info("[%s] %s" % (title, text))


def copy_to_clipboard(text) -> bool:
    """Unicode 剪贴板，走 ctypes，避免 clip.exe 的编码坑。"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32
        k32.GlobalAlloc.restype = wintypes.HGLOBAL
        k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        k32.GlobalLock.restype = wintypes.LPVOID
        k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        u32.SetClipboardData.restype = wintypes.HANDLE

        data = text.encode("utf-16-le") + b"\x00\x00"
        if not u32.OpenClipboard(0):
            return False
        try:
            u32.EmptyClipboard()
            h = k32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
            if not h:
                return False
            p = k32.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            k32.GlobalUnlock(h)
            u32.SetClipboardData(13, h)  # CF_UNICODETEXT
            return True
        finally:
            u32.CloseClipboard()
    except Exception:
        return False


# ---------------------------------------------------------------- 浏览器
def default_browser_exe():
    """从注册表读系统的默认浏览器 exe。"""
    if os.name != "nt":
        return None, None
    try:
        import winreg
        key = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            progid = winreg.QueryValueEx(k, "ProgId")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + r"\shell\open\command") as k:
            cmd = winreg.QueryValueEx(k, "")[0]
        m = re.match(r'"([^"]+?\.exe)"', cmd, re.I) or re.match(r"(\S+?\.exe)", cmd, re.I)
        if m:
            p = Path(m.group(1))
            if p.exists():
                return p, progid
    except Exception:
        pass
    return None, None


def fallback_browsers():
    return [Path(p) for p in FALLBACK_BROWSERS if p and Path(p).exists()]


def is_firefox(exe: Path) -> bool:
    return (exe.name or "").lower() in ("firefox.exe",)


# ---------------------------------------------------------------- CDP
def port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, port)) == 0


def cdp_json(port, path):
    url = "http://%s:%d%s" % (HOST, port, path)
    with urllib.request.urlopen(url, timeout=3) as r:
        return json.loads(r.read().decode())


def wait_port(port, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        if port_open(port):
            try:
                cdp_json(port, "/json/version")
                return True
            except Exception:
                pass
        time.sleep(0.4)
    return False


class CDP:
    def __init__(self, ws_url):
        import websocket
        self.ws = websocket.create_connection(ws_url, timeout=15, suppress_origin=True)
        self.mid = 0

    def send(self, method, params=None):
        self.mid += 1
        self.ws.send(json.dumps({"id": self.mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.mid:
                return msg

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------- 主流程
def normalize(cookies):
    out = []
    for c in cookies:
        name, value = c.get("name"), c.get("value")
        if not name or value is None:
            continue
        dom = c.get("domain") or ".kukuai.cn"
        if not dom.startswith("."):
            dom = "." + dom.lstrip(".")
        item = {"name": name, "value": value, "domain": dom, "path": c.get("path") or "/"}
        if c.get("httpOnly"):
            item["httpOnly"] = True
        if c.get("secure"):
            item["secure"] = True
        out.append(item)
    return out


def has_login(cookies):
    return "BDUSS" in {c.get("name") for c in cookies}


def launch(exe: Path, port: int, profile: Path):
    return subprocess.Popen([str(exe), "--remote-debugging-port=%d" % port,
                             "--user-data-dir=%s" % profile] + LAUNCH_ARGS + [TARGET_URL])


def main(argv=None):
    ap = argparse.ArgumentParser(description="库库AI Cookie 抓取")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-clipboard", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    _setup_console()

    info("=" * 52)
    info("  库库AI Cookie 抓取")
    info("=" * 52)

    if args.selftest:
        db, prog = default_browser_exe()
        info("默认浏览器: %s (%s)" % (db or "未读到", prog or "-"))
        info("候选兜底: %s" % [str(p) for p in fallback_browsers()])
        info("selftest ok")
        return 0

    profile = Path(os.environ.get("TEMP", "/tmp")) / "kukuai-cookie-profile"
    shutil.rmtree(profile, ignore_errors=True)

    procs = []
    if not args.no_browser:
        db, prog = default_browser_exe()
        order = []
        if db and not is_firefox(db):
            order.append(db)
        order += [b for b in fallback_browsers() if b not in order]

        if not order:
            popup("没有可用浏览器",
                  "没读到默认浏览器，也没找到 Chrome / Edge。\n先装一个浏览器再运行本工具。")
            return 2

        info("")
        info(">>> 将用你的默认浏览器打开窗口：%s" % (str(db) if db else order[0]))
        info(">>> 请用百度账号登录库库AI，登录成功后不用管，工具会自动保存")
        info("")

        ok = False
        for exe in order:
            info("启动: %s" % exe)
            procs.append(launch(exe, args.port, profile))
            if wait_port(args.port, 18):
                ok = True
                break
            info("这个浏览器没起来调试端口，换下一个……")
            try:
                procs[-1].terminate()
            except Exception:
                pass
            shutil.rmtree(profile, ignore_errors=True)
        if not ok:
            popup("启动失败",
                  "浏览器调试端口没起来。\n可能被安全软件拦了，关掉杀软后重试。")
            return 3

    try:
        if args.no_browser and not wait_port(args.port, 5):
            popup("没连上浏览器", "指定端口 %d 上没有浏览器在调试模式运行。" % args.port)
            return 3

        info("浏览器已就绪，等待登录……")
        deadline = time.time() + args.timeout
        cookies = []
        while time.time() < deadline:
            try:
                targets = cdp_json(args.port, "/json/list")
            except Exception:
                time.sleep(1)
                continue
            page = None
            for t in targets:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    if "kukuai.cn" in (t.get("url") or ""):
                        page = t
                        break
                    page = page or t
            if not page:
                time.sleep(1)
                continue
            try:
                cdp = CDP(page["webSocketDebuggerUrl"])
                res = cdp.send("Network.getCookies", {"urls": COOKIE_HOSTS})
                cdp.close()
                cookies = (res.get("result") or {}).get("cookies") or []
            except Exception:
                time.sleep(1)
                continue
            if has_login(cookies):
                info("检测到登录态，正在保存……")
                break
            time.sleep(2)
        else:
            popup("超时", "等了 %d 秒还没检测到登录。\n重新运行一次，登录后别急着关浏览器。" % args.timeout)
            return 4

        data = normalize(cookies)
        out_path = Path(os.path.expanduser(args.out))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        copied = False if args.no_clipboard else copy_to_clipboard(payload)

        info("")
        info("已保存 %d 条 Cookie → %s" % (len(data), out_path))
        if copied:
            info("已复制到剪贴板 ✅  直接粘贴到 Agent 对话里发过去即可")
        else:
            info("（剪贴板写入失败，可从上面的文件里复制）")
        popup("完成",
              ("Cookie 已保存并复制到剪贴板 ✅\n\n"
               if copied else "Cookie 已保存 ✅\n\n")
              + "文件：%s\n条数：%d\n\n" % (out_path, len(data))
              + "现在直接粘贴到 Agent 对话里发过去即可。")
        return 0
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(1)
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        popup("出错", "%s: %s" % (type(e).__name__, e))
        sys.exit(1)
