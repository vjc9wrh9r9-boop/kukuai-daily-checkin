#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按需下载 GetCookie.exe（技能包不内置这个 11MB 的 exe）。

为什么不在包里带：
    - 云端 Agent 跑的是 Linux，Windows GUI 下载了也执行不了；
    - 11MB 的 zip 传到聊天里很费劲；
    - 内置二进制会在机器上留多份副本，被别的 Agent 捡去当「最新版」（真实踩过）。

这个脚本做的事：按顺序试「GitHub 直链 → 国内镜像」，谁通用谁，存到 tools/GetCookie.exe。
公开 Release，**不需要 GitHub 账号、不需要登录**。

用法：
    python tools/fetch_tool.py                 # 下载（自动选最快可用的源）
    python tools/fetch_tool.py --print         # 只打印所有可用地址
    python tools/fetch_tool.py --force         # 已存在也重下
    python tools/fetch_tool.py --out D:\\x.exe  # 指定保存位置
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "v4.0.3"
ASSET = "GetCookie.exe"
PATH_PART = ("vjc9wrh9r9-boop/kukuai-daily-checkin"
             "/releases/download/%s/%s" % (VERSION, ASSET))

# 直链优先；国内网络打不开 github.com 时自动退到镜像（都是公开前缀，不用登录）
SOURCES = [
    ("GitHub", "https://github.com/" + PATH_PART),
    ("gh-proxy", "https://gh-proxy.com/https://github.com/" + PATH_PART),
    ("ghfast", "https://ghfast.top/https://github.com/" + PATH_PART),
    ("ghproxy.net", "https://ghproxy.net/https://github.com/" + PATH_PART),
]
MIN_SIZE = 5 * 1024 * 1024   # 正常约 11MB，明显偏小说明下到的是错误页


def human(n: int) -> str:
    return "%.1f MB" % (n / 1024 / 1024)


def try_download(url: str, dest: Path, timeout: int = 240) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "kukuai-skill/1.0"})
    total = 0
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    if total < MIN_SIZE:
        tmp.unlink(missing_ok=True)
        raise IOError("文件只有 %s，可能是错误页/被拦截" % human(total))
    os.replace(tmp, dest)
    return total


def main(argv=None):
    ap = argparse.ArgumentParser(description="下载 GetCookie.exe（自动换源）")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / ASSET),
                    help="保存路径（默认 tools/GetCookie.exe）")
    ap.add_argument("--print", action="store_true", help="只打印地址")
    ap.add_argument("--force", action="store_true", help="已存在也重新下载")
    args = ap.parse_args(argv)

    if args.print:
        for name, url in SOURCES:
            print("%-12s %s" % (name, url))
        return 0

    dest = Path(args.out).expanduser()
    if dest.exists() and not args.force:
        print("已存在：%s（%s）。要重下加 --force" % (dest, human(dest.stat().st_size)))
        return 0

    if os.name != "nt":
        print("当前不是 Windows，这个 exe 跑不了。把下面的地址发给用户即可（不需要 GitHub 账号）：")
        for name, url in SOURCES:
            print("  %-12s %s" % (name, url))
        return 0

    errors = []
    for name, url in SOURCES:
        try:
            print("尝试 %s …" % name, flush=True)
            size = try_download(url, dest)
            print("完成：%s（%s，来自 %s）" % (dest, human(size), name))
            return 0
        except Exception as e:
            errors.append("%s: %s" % (name, str(e)[:80]))
            print("  %s 失败：%s" % (name, str(e)[:80]))
            time.sleep(1)

    print("\n全部源都失败了：")
    for e in errors:
        print("  -", e)
    print("\n可以让用户自己在浏览器打开下面任一链接下载（公开 Release，不用登录）：")
    for name, url in SOURCES:
        print("  %-12s %s" % (name, url))
    return 1


if __name__ == "__main__":
    sys.exit(main())
