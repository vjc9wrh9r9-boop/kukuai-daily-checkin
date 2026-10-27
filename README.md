# 库库AI 每日签到 Skill

> 库库AI（[kuku.baidu.com](https://kuku.baidu.com/app)）每日签到 + 每日任务的自动化。
> 当前适配 **2026-10-21 ~ 2026-12-04** 期活动：**每日签到得网盘SVIP月卡 · 做任务抽好礼 赢苹果笔记本**。

用你自己的登录 Cookie，在无头浏览器里完成签到与任务，输出**接口核验过的**进度 + Markdown 汇总。
不需要本机浏览器常驻，也不需要开 PC 客户端。

## 这期活动是什么

| 项 | 内容 |
| --- | --- |
| 周期 | 2026-10-21 ~ 2026-12-04（以活动页实时展示为准） |
| 核心奖励 | 连签 **30 天必得**百度网盘 SVIP 月卡；连签 3 / 7 / 15 天解锁前置档位 |
| 每日签到 | 积分 +10、抽奖 +1 |
| 断签 | 清零回第 1 天，已发奖品不回收 |
| 多端 | 签到天数各端同步；**每日任务进度不同步**（见下） |

## ⚠️ 最重要的一件事：任务分两套进度

| 渠道 | `task_from` | 任务数 | 谁看得到 |
| --- | --- | --- | --- |
| 网页端 | `kuku_signin_30_web` | 6 | 浏览器打开 kuku.baidu.com |
| PC 客户端 | `kuku_signin_30_pc` | 7（多「导入网盘文件」「上传本地文件」） | 库库AI 桌面客户端的任务中心 |

**网页端做完了，客户端里仍然是 0/3。** 旧版只做网页端，所以会出现「脚本说完成了、界面没动」。
v4 会两个渠道都做、都上报、都核验，结果里分别给出「网页端 x/6」「PC客户端 x/7」。

## 能自动做什么

| 任务 | 上限 | 出现在 | 脚本 |
| --- | --- | --- | --- |
| 每日签到 | 1/天 | 两端 | ✅ 账号级，签一次两端都算 |
| 与库库聊聊热门话题 | 3/天 | 两端 | ✅ 每条一个新会话 + 上报 |
| 召唤任意专家并发起对话 | 1 | 两端 | ✅ 首次需勾协议（`--with-expert`） |
| 浏览 10s 知识广场 | 1 | 两端 | ✅ 停留 14s 后上报 |
| 去上传一次本地文件 | 1 | 仅客户端 | ✅ 传一个占位 txt（`--no-upload` 可关） |
| 去导入一次网盘文件 | 1 | 仅客户端 | ⚠️ 需先授权百度网盘（`--with-netdisk`） |
| 下载并登录库库PC客户端 | 1 | 仅网页端 | ❌ 装一次客户端即可 |
| 邀请类任务（2 个） | — | 两端 | ❌ 必须真人 |

进度以官方接口为准：

- `GET /api/taskscore/tasklist?task_from=<渠道>` → `task_finish_count / task_count_max`
- `POST /api/genflowpro/activity/taskcomplete` → `errno=0` 才算上报成功

## 安装

```bash
git clone https://github.com/vjc9wrh9r9-boop/kukuai-daily-checkin.git \
  ~/.workbuddy/skills/kukuai-checkin-tasks

# Windows：C:\Users\<用户名>\.workbuddy\skills\kukuai-checkin-tasks

pip install playwright
python -m playwright install chromium
```

也可以直接下载 [Release](https://github.com/vjc9wrh9r9-boop/kukuai-daily-checkin/releases) 里的 zip 解压到 skills 目录。

## 拿 Cookie（用自带工具，别按 F12）

双击 `tools/GetCookie.exe`：

1. 点 **① 打开网页登录库库AI，抓取 Cookie** → 用系统默认浏览器打开工作台 → 点左下角签到卡「登录领奖」登录
2. 状态条变绿（工作台已确认登录）→ 点 **② 复制已抓取的 Cookie**
3. 粘贴给 AI，或让脚本自己用（默认存 `~/.kukuai/cookies.json`，只有 `BDUSS` + `STOKEN` 两条）

> 手动 F12 复制经常漏 `STOKEN`，漏了必然登录失败。

## 用法

```bash
# 只读看两端进度（不签到、不动任务）
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --dry-run

# 正式：签到 + 两个渠道的每日任务
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json

# 首次：顺带把专家协议 / 网盘授权也过一次（本人同意后再加）
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --with-expert --with-netdisk

# 只签到 / 只做某个渠道 / 只做某几项
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --only-signin
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --channels pc
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --tasks topic_chat,browse_square
```

| 参数 | 说明 |
| --- | --- |
| `--cookies` | Cookie 文件，默认依次找 `~/.kukuai/cookies.json` 等 |
| `--dry-run` | 只读接口看进度 |
| `--only-signin` / `--no-signin` | 只签到 / 只做任务 |
| `--channels web\|pc` | 只做某个渠道（默认两个都做） |
| `--with-expert` / `--with-netdisk` | 首次代勾专家协议 / 代点网盘授权 |
| `--no-upload` | 不往网盘传占位文件 |
| `--deadline` | 整体硬超时（默认 1200s），超时输出 `stage=timeout` |

输出：`kukuai-summary-<时间>.md` + 截图 + `log/`，JSON 里关键字段是 `task_board`（两端逐项进度）和 `channels`（完成度）。

## 定时跑

- **Agent 自带的定时任务**：让 Agent 每天 09:00 跑一次，把 `task_board` 推给你（电脑/客户端不在线就不跑）
- **GitHub Actions**：见 `references/cloud-mode.md` 里的 Actions 跑法，电脑关机也能跑

## 已知边界

- 邀请类任务需要真实好友点链接，脚本不做，这是能力边界不是 bug
- 「上传本地文件」会往你的网盘传一个几百字节的占位 txt，不需要就加 `--no-upload`
- 「导入网盘文件」要先在网页上点一次「确定授权」，之后 `--with-netdisk` 才能自动导入
- 平台对脚本类工具有限制，是否使用请自行判断并承担风险；遇到验证码/风控脚本会立即停止
