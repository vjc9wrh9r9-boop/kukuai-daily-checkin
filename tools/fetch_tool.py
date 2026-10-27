#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按需下载 GetCookie.exe（技能包不再内置这个 11MB 的 exe）。

为什么要这样：
    - Agent 多半跑在云端 Linux 沙箱，下载了也执行不了 Windows GUI，内置纯属占体积；
    - 内置二进制一旦随包分发，很容易在机器上留下多份旧副本，被别的 Agent 捡去用（真实踩过）。

用法：
    python tools/fetch_tool.py            # 下载到 tools/GetCookie.exe
    python tools/fetch_tool.py --print    # 只打印下载地址，不下载
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.request
from pathlib import Path

VERSION = "v4.0.3"
ASSET = "GetCookie.exe"
URL = ("https://github.com/vjc9wrh9r9-boop/kukuai-daily-checkin"
       "/releases/download/%s/%s" % (VERSION, ASSET))


def download(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print("下载 %s" % URL)
    req = urllib.request.Request(URL, headers={"User-Agent": "kukuai-skill/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:
        total = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    print("已保存 %s（%.1f MB）" % (dest, total / 1024 / 1024))
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser(description="下载 GetCookie.exe")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / ASSET),
                    help="保存路径（默认 tools/GetCookie.exe）")
    ap.add_argument("--print", action="store_true", help="只打印地址")
    args = ap.parse_args(argv)

    if args.print:
        print(URL)
        return 0
    if os.name != "nt":
        print("这个 exe 只能在 Windows 上跑。当前系统不是 Windows，直接下载地址给用户即可：")
        print(URL)
        return 0
    try:
        download(Path(args.out).expanduser())
    except Exception as e:
        print("下载失败：%s: %s" % (type(e).__name__, e))
        print("也可以手动下载：%s" % URL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
