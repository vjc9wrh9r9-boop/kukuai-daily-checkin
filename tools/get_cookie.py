#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""库库AI Cookie 抓取工具（图形界面版）。

打开后是一个小窗口，两个按钮：
    ① 打开网页登录库库AI，抓取 Cookie
    ② 复制已抓取的 Cookie

原理：按系统登记的默认浏览器启动一个临时配置的窗口，打开远程调试端口，
     登录后通过 DevTools 协议读出 Cookie。不碰日常浏览器数据，不装扩展，不上传。

零第三方依赖：WebSocket 客户端用标准库自己实现，打包体积小、不易被杀软误判。

命令行（自动化用）：
    --cli            命令行模式（不弹界面）
    --port 9222      调试端口
    --no-browser     不自动启动浏览器
    --out <路径>     Cookie 输出路径（默认 ~/.kukuai/cookies.json）
    --timeout 600    等待登录秒数
    --no-clipboard   不复制到剪贴板
    --selftest       只做环境检查
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOST = "127.0.0.1"
# 登录入口。用 kuku.baidu.com 的 home 页而不是 www.kukuai.cn：
# 实测 360 浏览器加载 kukuai.cn 会在 8 秒左右整个进程退出，导致调试端口断掉、
# 抓不到 Cookie；这个地址在 360 / Chrome / Edge 上都稳定。
# 带 invite_code 等参数是用户自己的邀请链接，可用 --url 覆盖。
TARGET_URL = ("https://kuku.baidu.com/home?invite_code=XUU5A9AB&task_type=252"
              "&task_id_str=5259635171792479&task_from=kuku_signin_30_pc")
DEFAULT_URL = TARGET_URL
COOKIE_HOSTS = ["https://kuku.baidu.com/", "https://www.kukuai.cn/", "https://baidu.com/"]
DEFAULT_OUT = "~/.kukuai/cookies.json"

APP_TITLE = "库库AI Cookie 抓取工具"
APP_VERSION = "2.0"

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


def browser_candidates():
    """默认浏览器优先（Firefox 不支持 CDP，跳过），后面接 Chrome / Edge 兜底。"""
    db, prog = default_browser_exe()
    order = []
    if db and not is_firefox(db):
        order.append(db)
    for b in fallback_browsers():
        if b not in order:
            order.append(b)
    return order, db


def free_port(preferred=9222):
    """优先用 9222，被占用就往后找。"""
    for p in [preferred] + list(range(9223, 9300)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((HOST, p)) != 0:
                return p
    return preferred


# ---------------------------------------------------------------- 极简 WebSocket（标准库）
class WS:
    """够用就好的 WebSocket 客户端：只支持 CDP 需要的文本帧。"""

    def __init__(self, url, timeout=15):
        m = re.match(r"wss?://([^/:]+):(\d+)(/.*)?$", url)
        if not m:
            raise ValueError("ws url 不合法: %r" % url)
        host, port, path = m.group(1), int(m.group(2)), m.group(3) or "/"
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.buf = b""
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"
               % (path, host, port, key))
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise IOError("WebSocket 握手被关闭")
            head += chunk
        header, _, rest = head.partition(b"\r\n\r\n")
        self.buf = rest
        status = header.split(b"\r\n")[0]
        if b"101" not in status:
            raise IOError("WebSocket 握手失败: %s" % status[:120].decode("latin-1"))

    # --- 底层读写 ---
    def _exact(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise IOError("连接已断开")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send_frame(self, payload: bytes, opcode=0x1):
        mask = os.urandom(4)
        n = len(payload)
        header = bytearray([0x80 | opcode])
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def _read_message(self):
        chunks = []
        while True:
            b1, b2 = self._exact(2)
            fin = b1 & 0x80
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._exact(8))[0]
            mask = self._exact(4) if masked else None
            data = self._exact(length) if length else b""
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x8:          # close
                raise IOError("浏览器关闭了调试连接")
            if opcode == 0x9:          # ping
                self._send_frame(data, 0xA)
                continue
            if opcode == 0xA:          # pong
                continue
            chunks.append(data)
            if fin:
                return b"".join(chunks)

    # --- 对外 ---
    def send(self, text: str):
        self._send_frame(text.encode("utf-8"))

    def recv(self) -> str:
        return self._read_message().decode("utf-8", "replace")

    def close(self):
        try:
            self._send_frame(b"", 0x8)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


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
        self.ws = WS(ws_url)
        self.mid = 0

    def send(self, method, params=None):
        self.mid += 1
        self.ws.send(json.dumps({"id": self.mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.mid:
                return msg

    def close(self):
        self.ws.close()


# ---------------------------------------------------------------- Cookie
def normalize(cookies):
    out = []
    seen = set()
    for c in cookies:
        name, value = c.get("name"), c.get("value")
        if not name or value is None:
            continue
        dom = c.get("domain") or ".kukuai.cn"
        if not dom.startswith("."):
            dom = "." + dom.lstrip(".")
        key = (name, dom, c.get("path") or "/")
        if key in seen:          # 同一 cookie 被多个 URL 查询重复返回时只留一份
            continue
        seen.add(key)
        item = {"name": name, "value": value, "domain": dom, "path": c.get("path") or "/"}
        if c.get("httpOnly"):
            item["httpOnly"] = True
        if c.get("secure"):
            item["secure"] = True
        out.append(item)
    return out


def has_login(cookies):
    return "BDUSS" in {c.get("name") for c in cookies}


def read_cookies(port):
    """从调试端口读出 cookie，失败返回 None。"""
    try:
        targets = cdp_json(port, "/json/list")
    except Exception:
        return None
    page = None
    for t in targets:
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            u = t.get("url") or ""
            if "kukuai.cn" in u or "kuku.baidu.com" in u or "baidu.com" in u:
                page = t
                break
            page = page or t
    if not page:
        return None
    try:
        cdp = CDP(page["webSocketDebuggerUrl"])
        try:
            res = cdp.send("Network.getCookies", {"urls": COOKIE_HOSTS})
        finally:
            cdp.close()
        return (res.get("result") or {}).get("cookies") or []
    except Exception:
        return None


def save_cookies(cookies, out_path):
    data = normalize(cookies)
    if not data:
        return None, None
    path = Path(os.path.expanduser(str(out_path)))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data, payload


def launch(exe: Path, port: int, profile: Path, url=None):
    return subprocess.Popen([str(exe), "--remote-debugging-port=%d" % port,
                             "--user-data-dir=%s" % profile] + LAUNCH_ARGS + [url or DEFAULT_URL],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_procs(procs):
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    time.sleep(1)
    for p in procs:
        try:
            if p.poll() is None:
                p.kill()
        except Exception:
            pass


# ---------------------------------------------------------------- 命令行模式
def cli_main(args):
    _setup_console()
    info("=" * 52)
    info("  库库AI Cookie 抓取（命令行）")
    info("=" * 52)

    if args.selftest:
        db, prog = default_browser_exe()
        info("默认浏览器: %s (%s)" % (db or "未读到", prog or "-"))
        info("候选兜底: %s" % [str(p) for p in fallback_browsers()])
        info("selftest ok")
        return 0

    port = args.port or free_port()
    profile = Path(os.environ.get("TEMP", "/tmp")) / "kukuai-cookie-profile"
    shutil.rmtree(profile, ignore_errors=True)

    procs = []
    if not args.no_browser:
        order, db = browser_candidates()
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
            procs.append(launch(exe, port, profile, args.url))
            if wait_port(port, 18):
                ok = True
                break
            info("这个浏览器没起来调试端口，换下一个……")
            stop_procs(procs[-1:])
            shutil.rmtree(profile, ignore_errors=True)
        if not ok:
            popup("启动失败",
                  "浏览器调试端口没起来。\n可能被安全软件拦了，关掉杀软后重试。")
            return 3

    try:
        if args.no_browser and not wait_port(port, 5):
            popup("没连上浏览器", "端口 %d 上没有浏览器在调试模式运行。" % port)
            return 3

        info("浏览器已就绪，等待登录……")
        deadline = time.time() + args.timeout
        cookies = []
        while time.time() < deadline:
            cookies = read_cookies(port)
            if cookies and has_login(cookies):
                info("检测到登录态，正在保存……")
                break
            time.sleep(2)
        else:
            popup("超时", "等了 %d 秒还没检测到登录。\n重新运行一次，登录后别急着关浏览器。"
                  % args.timeout)
            return 4

        data, payload = save_cookies(cookies, args.out)
        if not data:
            popup("没有抓到 Cookie", "读到了空列表，请重试。")
            return 5
        copied = False if args.no_clipboard else copy_to_clipboard(payload)
        info("")
        info("已保存 %d 条 Cookie → %s" % (len(data), os.path.expanduser(args.out)))
        info("已复制到剪贴板 ✅" if copied else "（剪贴板写入失败）")
        return 0
    finally:
        stop_procs(procs)
        shutil.rmtree(profile, ignore_errors=True)


# ---------------------------------------------------------------- 图形界面
COLORS = {
    "bg": "#ffffff",
    "card": "#f5f7fa",
    "line": "#e3e8ef",
    "text": "#1a1f2e",
    "sub": "#6b7280",
    "accent": "#1a73e8",
    "accent_dark": "#1557b0",
    "ok_bg": "#e8f6ee",
    "ok_fg": "#137333",
    "work_bg": "#e8f0fe",
    "work_fg": "#1a56c4",
    "fail_bg": "#fdecea",
    "fail_fg": "#b3261e",
    "idle_bg": "#f1f3f5",
    "idle_fg": "#5f6368",
}


class CookieApp:
    def __init__(self, root, out_path=None, port=None, timeout=600, url=None):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.root = root
        self.out_path = os.path.expanduser(out_path or DEFAULT_OUT)
        self.port = port or free_port()
        self.timeout = timeout
        self.url = url or DEFAULT_URL

        self.payload = None
        self.cookie_count = 0
        self.busy = False
        self.stop_flag = False
        self.procs = []
        self.worker = None

        root.title("%s v%s" % (APP_TITLE, APP_VERSION))
        root.configure(bg=COLORS["bg"])
        root.geometry("600x560")
        root.minsize(560, 520)
        self._center(root, 600, 560)
        self._dpi_aware()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.style = ttk.Style(root)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        font = "Microsoft YaHei UI"

        self._build_widgets(font)

    # --- 窗口基础 ---
    @staticmethod
    def _center(win, w, h):
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        win.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, max(0, (sh - h) // 2 - 30)))

    @staticmethod
    def _dpi_aware():
        if os.name != "nt":
            return
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    # --- 布局 ---
    def _build_widgets(self, font):
        tk, ttk = self.tk, self.style
        root = self.root

        wrap = tk.Frame(root, bg=COLORS["bg"])
        wrap.pack(fill="both", expand=True, padx=22, pady=18)

        # 标题
        tk.Label(wrap, text="库库AI Cookie 抓取工具", bg=COLORS["bg"], fg=COLORS["text"],
                 font=(font, 17, "bold"), anchor="w").pack(fill="x")
        tk.Label(wrap, text="点按钮打开网页登录一次，抓到后复制给 Agent 即可。不装扩展、不上传、不碰你日常浏览器数据。",
                 bg=COLORS["bg"], fg=COLORS["sub"], font=(font, 9), anchor="w",
                 justify="left", wraplength=540).pack(fill="x", pady=(4, 14))

        # 按钮 1
        self.btn_run = tk.Button(
            wrap, text="①  打开网页登录库库AI，抓取 Cookie",
            font=(font, 11, "bold"), bg=COLORS["accent"], fg="#ffffff",
            activebackground=COLORS["accent_dark"], activeforeground="#ffffff",
            relief="flat", bd=0, cursor="hand2", pady=13,
            command=self.on_run)
        self.btn_run.pack(fill="x")

        # 按钮 2
        self.btn_copy = tk.Button(
            wrap, text="②  复制已抓取的 Cookie",
            font=(font, 11, "bold"), bg=COLORS["idle_bg"], fg=COLORS["sub"],
            activebackground="#e6e9ed", activeforeground=COLORS["sub"],
            relief="flat", bd=0, cursor="hand2", pady=13,
            state="disabled", command=self.on_copy)
        self.btn_copy.pack(fill="x", pady=(10, 14))

        # 状态条
        self.status_box = tk.Frame(wrap, bg=COLORS["idle_bg"], height=68)
        self.status_box.pack(fill="x")
        self.status_box.pack_propagate(False)
        self.status_label = tk.Label(
            self.status_box, text="● 未抓取。点上面第 ① 个按钮开始。",
            bg=COLORS["idle_bg"], fg=COLORS["idle_fg"], font=(font, 10, "bold"),
            anchor="w", justify="left", wraplength=505, padx=14)
        self.status_label.pack(fill="both", expand=True)

        # 日志
        tk.Label(wrap, text="运行记录", bg=COLORS["bg"], fg=COLORS["sub"],
                 font=(font, 9), anchor="w").pack(fill="x", pady=(14, 4))
        box = tk.Frame(wrap, bg=COLORS["line"], bd=0)
        box.pack(fill="both", expand=True)
        self.log_text = tk.Text(box, height=6, bg=COLORS["card"], fg=COLORS["text"],
                                font=("Consolas", 9), relief="flat", bd=0,
                                wrap="word", padx=10, pady=8, state="disabled")
        sb = tk.Scrollbar(box, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log("窗口已就绪，等待操作")

        # 底部：保存位置
        foot = tk.Frame(wrap, bg=COLORS["bg"])
        foot.pack(fill="x", pady=(10, 0))
        tk.Label(foot, text="保存位置：%s" % self.out_path, bg=COLORS["bg"],
                 fg=COLORS["sub"], font=(font, 8), anchor="w").pack(side="left")
        self.link_folder = tk.Label(foot, text="打开文件夹", bg=COLORS["bg"],
                                    fg=COLORS["accent"], font=(font, 8, "underline"),
                                    cursor="hand2")
        self.link_folder.pack(side="right")
        self.link_folder.bind("<Button-1>", lambda e: self.open_folder())

    # --- UI 更新（线程安全） ---
    def _ui(self, fn, *a):
        try:
            self.root.after(0, lambda: fn(*a))
        except Exception:
            pass

    def set_status(self, text, level="idle"):
        bg = COLORS["%s_bg" % level]
        fg = COLORS["%s_fg" % level]
        self.status_box.configure(bg=bg)
        self.status_label.configure(text=text, bg=bg, fg=fg)

    def log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", "%s  %s\n" % (time.strftime("%H:%M:%S"), msg))
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # --- 按钮状态 ---
    def _set_busy(self, busy):
        self.busy = busy
        if busy:
            self.btn_run.configure(state="disabled", bg="#9db8e6", cursor="watch",
                                   text="正在抓取…（登录后自动完成）")
            self.btn_copy.configure(state="disabled", bg=COLORS["idle_bg"], fg=COLORS["sub"])
        else:
            text = ("重新抓取（会覆盖旧 Cookie）" if self.payload
                    else "①  打开网页登录库库AI，抓取 Cookie")
            self.btn_run.configure(state="normal", bg=COLORS["accent"], cursor="hand2",
                                   text=text)
            if self.payload:
                self.btn_copy.configure(state="normal", bg="#d2e3fc", fg=COLORS["accent_dark"],
                                        cursor="hand2")

    # --- 动作 1：抓取 ---
    def on_run(self):
        if self.busy:
            return
        self.stop_flag = False
        self._set_busy(True)
        self.log("开始：准备启动浏览器")
        self.set_status("正在启动浏览器…", "work")
        import threading
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    def _worker(self):
        profile = Path(os.environ.get("TEMP", "/tmp")) / "kukuai-cookie-profile"
        shutil.rmtree(profile, ignore_errors=True)
        try:
            order, db = browser_candidates()
            if not order:
                self._ui(self._fail, "没找到可用浏览器。请先安装 Chrome / Edge 再试。")
                return
            self._ui(self.log, "浏览器：%s" % (db or order[0]))

            # 启动浏览器，直到调试端口起来
            started = False
            for exe in order:
                if self.stop_flag:
                    return
                self._ui(self.log, "启动 %s" % exe.name)
                try:
                    self.procs.append(launch(exe, self.port, profile, self.url))
                except Exception as e:
                    self._ui(self.log, "启动失败：%s" % e)
                    continue
                if wait_port(self.port, 20):
                    started = True
                    break
                self._ui(self.log, "%s 没起来调试端口，换下一个" % exe.name)
                stop_procs(self.procs[-1:])
                shutil.rmtree(profile, ignore_errors=True)
            if not started:
                self._ui(self._fail,
                         "浏览器调试端口没起来（可能被安全软件拦了）。关掉杀软后重试。")
                return

            self._ui(self.set_status,
                     "浏览器已打开，请用百度账号登录库库AI —— 登录成功后会自动抓取，不用管。", "work")
            self._ui(self.log, "浏览器已就绪，等待登录…")

            # 轮询 cookie
            start = time.time()
            deadline = start + self.timeout
            lost = 0
            next_tick = 0
            while time.time() < deadline:
                if self.stop_flag:
                    return
                if not port_open(self.port):
                    lost += 1
                    if lost >= 3:
                        self._ui(self._fail, "浏览器窗口被关掉了，Cookie 没抓到。重新点第 ① 个按钮。")
                        return
                else:
                    lost = 0
                cookies = read_cookies(self.port)
                if cookies and has_login(cookies):
                    data, payload = save_cookies(cookies, self.out_path)
                    if not data:
                        self._ui(self._fail, "读到了 Cookie 但没有 BDUSS，可能还没登录完成，重试一次。")
                        return
                    self.payload = payload
                    self.cookie_count = len(data)
                    self._ui(self._success, len(data))
                    return
                elapsed = int(time.time() - start)
                if elapsed >= next_tick:
                    next_tick = elapsed + 3
                    self._ui(self.set_status,
                             "已等待 %d 秒 —— 请在上面的浏览器窗口里用百度账号登录库库AI，"
                             "登录成功后会自动抓取。" % elapsed, "work")
                time.sleep(1.5)

            self._ui(self._fail, "等了 %d 分钟还没检测到登录。重新点第 ① 个按钮，登录后别急着关窗口。"
                     % max(1, self.timeout // 60))
        except Exception as e:
            self._ui(self._fail, "出错了：%s: %s" % (type(e).__name__, e))
        finally:
            stop_procs(self.procs)
            self.procs = []
            shutil.rmtree(profile, ignore_errors=True)
            self._ui(self._set_busy, False)

    def _success(self, count):
        self.set_status("✅ 抓取成功！已保存 %d 条 Cookie。点第 ② 个按钮复制，然后粘贴到 Agent 对话里。"
                        % count, "ok")
        self.log("抓取成功：%d 条，已写入 %s" % (count, self.out_path))
        self.log("临时浏览器窗口已关闭")
        self.btn_run.configure(text="重新抓取（会覆盖旧 Cookie）")

    def _fail(self, reason):
        tip = "（上次抓到的 Cookie 仍可点第 ② 个按钮复制）" if self.payload else ""
        self.set_status("❌ 抓取失败：%s%s" % (reason, tip), "fail")
        self.log("失败：%s" % reason)

    # --- 动作 2：复制 ---
    def on_copy(self):
        if not self.payload:
            self.set_status("还没有抓到 Cookie，先点第 ① 个按钮。", "fail")
            return
        if copy_to_clipboard(self.payload):
            self.set_status("✅ 已复制 %d 条 Cookie 到剪贴板。现在去 Agent 对话里 Ctrl+V 粘贴发送。"
                            % self.cookie_count, "ok")
            self.log("已复制到剪贴板（%d 条，%d 字符）" % (self.cookie_count, len(self.payload)))
        else:
            self.set_status("复制失败（剪贴板被占用）。请点右下角「打开文件夹」手动复制。", "fail")

    def open_folder(self):
        path = Path(self.out_path)
        try:
            if path.exists():
                subprocess.Popen(["explorer", "/select,", str(path)])
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                subprocess.Popen(["explorer", str(path.parent)])
        except Exception as e:
            self.log("打开文件夹失败：%s" % e)

    # --- 关闭 ---
    def on_close(self):
        if self.busy:
            if not self._ask_quit():
                return
            self.stop_flag = True
        try:
            stop_procs(self.procs)
        except Exception:
            pass
        self.root.destroy()

    def _ask_quit(self):
        from tkinter import messagebox
        return messagebox.askyesno("正在抓取中", "还在等登录，确定要关闭吗？", parent=self.root)


def gui_main(args):
    import tkinter as tk
    root = tk.Tk()
    try:
        root.iconbitmap(default="")
    except Exception:
        pass
    CookieApp(root, out_path=args.out, port=args.port, timeout=args.timeout, url=args.url)
    root.mainloop()
    return 0


# ---------------------------------------------------------------- 入口
def build_parser():
    ap = argparse.ArgumentParser(description="库库AI Cookie 抓取")
    ap.add_argument("--cli", action="store_true", help="命令行模式（不弹界面）")
    ap.add_argument("--port", type=int, default=None, help="调试端口（默认自动挑）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="Cookie 输出路径")
    ap.add_argument("--timeout", type=int, default=600, help="等待登录秒数")
    ap.add_argument("--url", default=DEFAULT_URL, help="登录入口地址（默认库库AI 邀请页）")
    ap.add_argument("--no-browser", action="store_true", help="命令行模式下不自动启动浏览器")
    ap.add_argument("--no-clipboard", action="store_true", help="不复制到剪贴板")
    ap.add_argument("--selftest", action="store_true", help="只做环境检查")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    cli = args.cli or args.selftest or args.no_browser or args.no_clipboard
    return cli_main(args) if cli else gui_main(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        popup("出错", "%s: %s" % (type(e).__name__, e))
        sys.exit(1)
