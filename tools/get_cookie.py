#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""库库AI Cookie 自动抓取工具。

用法（最简单）：
    双击 获取Cookie.exe  → 弹出的浏览器里用百度账号登录库库AI → 自动保存 → 关窗

原理：用本机已有的 Chrome / Edge 开一个独立临时配置的窗口，打开远程调试端口，
     等你登录后通过 DevTools 协议读出该站点 Cookie，写到 ~/.kukuai/cookies.json。
     不读取你日常浏览器的配置，不安装任何浏览器扩展。

命令行可用参数：
    --port 9222      远程调试端口
    --no-browser     不自动启动浏览器（自行用 --remote-debugging-port 打开）
    --out <路径>     Cookie 输出路径
    --timeout 300    等待登录的秒数
"""

from __future__ import annotations

import argparse
import json
import os
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

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _setup_console():
    """打包成 exe 后控制台默认是 GBK，中文会乱码，强制切 UTF-8。"""
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
    """Windows 下弹个消息框；其它平台只打印。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
        return
    except Exception:
        pass
    info("[%s] %s" % (title, text))


def find_browser():
    for p in CHROME_CANDIDATES:
        if p and Path(p).exists():
            return p
    return None


def port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, port)) == 0


def cdp_json(port, path):
    url = "http://%s:%d%s" % (HOST, port, path)
    with urllib.request.urlopen(url, timeout=3) as r:
        return json.loads(r.read().decode())


def wait_port(port, timeout=20):
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
        import websocket  # websocket-client
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


def normalize(cookies):
    """统一成脚本能吃的数组格式，按站点补全 domain。"""
    out = []
    for c in cookies:
        name = c.get("name")
        value = c.get("value")
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
    names = {c.get("name") for c in cookies}
    return "BDUSS" in names


def main(argv=None):
    ap = argparse.ArgumentParser(description="库库AI Cookie 抓取")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--timeout", type=int, default=600, help="等待登录秒数，默认 600")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="只做环境检查后退出")
    args = ap.parse_args(argv)
    _setup_console()

    info("=" * 46)
    info(" 库库AI Cookie 抓取工具")
    info("=" * 46)

    browser = None
    if not args.no_browser:
        browser = find_browser()
        if not browser:
            popup("缺少浏览器", "没找到 Chrome 或 Edge。\n请先装 Microsoft Edge 再运行本工具。")
            return 2
        info("使用浏览器: %s" % browser)

    if args.selftest:
        info("selftest ok; browser=%s" % (browser or "not-required"))
        return 0

    profile = Path(os.environ.get("TEMP", "/tmp")) / "kukuai-cookie-profile"
    proc = None
    if not args.no_browser:
        info("")
        info(">>> 马上会打开一个浏览器窗口")
        info(">>> 请用你的百度账号登录，登录成功后不用管，工具会自动保存并关窗")
        info("")
        # 独立临时配置，不动你日常浏览器的数据
        if profile.exists():
            shutil.rmtree(profile, ignore_errors=True)
        proc = subprocess.Popen([
            browser,
            "--remote-debugging-port=%d" % args.port,
            "--user-data-dir=%s" % profile,
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-allow-origins=*",
            "--start-maximized",
            TARGET_URL,
        ])

    try:
        if not wait_port(args.port, 25):
            popup("启动失败", "浏览器调试端口没起来。\n可能被安全软件拦了，关掉杀软后重试。")
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
                    if "kukuai.cn" in (t.get("url") or "") or page is None:
                        page = t
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
            popup("超时", "等了 %d 秒还没检测到登录。\n再运行一次，登录后别急着关浏览器。" % args.timeout)
            return 4

        data = normalize(cookies)
        out_path = Path(os.path.expanduser(args.out))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        info("已保存 %d 条 Cookie 到 %s" % (len(data), out_path))
        popup("完成", "Cookie 已保存到：\n%s\n\n共 %d 条，现在可以去跑签到了。" % (out_path, len(data)))
        return 0
    finally:
        if proc is not None:
            try:
                proc.terminate()
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
