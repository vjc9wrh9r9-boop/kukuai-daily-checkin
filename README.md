# 库库AI 每日签到 Skill

> 库库AI（[kukuai.cn](https://www.kukuai.cn/)）每日签到 + 每日任务的云端自动化。
> 当前适配 **2026-10-21 ~ 2026-12-04** 期活动：**每日签到得网盘SVIP月卡 · 做任务抽好礼 赢苹果笔记本**。

用自己导出的登录 Cookie，在无头浏览器里完成签到与任务，输出 JSON + Markdown 汇总。不需要本机浏览器常驻，也不需要开 PC 客户端。

## 这期活动是什么

| 项 | 内容 |
| --- | --- |
| 周期 | 2026-10-21 ~ 2026-12-04（以活动页实时展示为准） |
| 核心奖励 | 连签 **30 天必得**百度网盘 SVIP 月卡；连签 3 / 7 / 15 天解锁前置档位 |
| 每日签到 | 积分 +10、抽奖 +1 |
| 断签 | 清零回第 1 天，已发奖品不回收 |
| 多端 | PC 客户端 / 网页版 / 手机端签到天数互通 |

## 能自动做什么

| 任务 | 上限 | 脚本 |
| --- | --- | --- |
| 每日签到 | 1/天 | ✅ |
| 与库库聊聊热门话题 | 3/天 | ✅ 按剩余次数发对话 |
| 召唤任意专家并发起对话 | 1 | ✅ 自动召唤首个专家 |
| 浏览 10s 知识广场 | 1 | ✅ 停留 12 秒 |
| 邀请新用户下载登录库库PC端 | — | ❌ 需真人邀请 |
| 邀请好友与库库对话 | 10 | ❌ 需真人邀请 |

脚本会读任务卡上的 `(1/3)` 进度，只补剩余次数，重复跑不会重复发消息。

## 安装

```bash
# 1. 放到 skills 目录
git clone https://github.com/vjc9wrh9r9-boop/kukuai-daily-checkin.git \
  ~/.workbuddy/skills/kukuai-daily-checkin

# Windows 对应路径：C:\Users\<用户名>\.workbuddy\skills\kukuai-daily-checkin

# 2. 依赖
pip install playwright
python -m playwright install chromium
```

重启 WorkBuddy 后说「帮我签到」即可触发，也可以直接命令行运行。

## 配置 Cookie

签到依赖登录态，**每人用自己的账号**：

1. Chrome / Edge 登录 <https://www.kukuai.cn/>
2. `F12` → Application（应用）→ Cookies → `https://www.kukuai.cn`
3. 复制 `BDUSS`、`STOKEN` 的值（`BDUSS` 是 HttpOnly，必须在面板里复制，`document.cookie` 拿不到）
4. 存成 `~/.kukuai/cookies.json`，最简写法：

```json
{"BDUSS": "你的值", "STOKEN": "你的值"}
```

活动内容在 `kuku.baidu.com` 域下，只导 `.kukuai.cn` 有时会被判成未登录。稳妥做法是两个域各导一份，数组格式见 `assets/cookie.example.json`。

## 用法

```bash
# 首次：只探测，不签到、不点任务
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --dry-run --probe-entry

# 正式：签到 + 清可自动任务
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json

# 只签到
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --only-signin

# 只跑指定任务
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --tasks topic_chat,browse_square
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--cookies` | 自动查找 | `~/.kukuai/cookies.json`、`~/.kukuai/cookies.txt`、`uploads/kukuai_cookies.json` |
| `--out` | `outputs` | 截图、Summary、日志目录 |
| `--state` | `~/.kukuai/state.json` | 连签状态，用于断签预警 |
| `--dry-run` | 关 | 只探测，不签到 |
| `--probe-entry` | 关 | dry-run 时打开任务中心解析状态 |
| `--no-signin` | 关 | 只清任务 |
| `--no-tasks` / `--only-signin` | 关 | 只签到 |
| `--tasks` | 全部 | `topic_chat,expert_chat,browse_square` |
| `--headful` | 关 | 显示浏览器窗口（排查用） |

输出：`kukuai-summary-<时间>.md`（可直接转发给自己）+ `kukuai-*.png` 截图 + `log/`。

## 为什么脚本写成这样

库库AI 这期活动有三处反常规结构，纯按文案点击会全部失败：

1. **真正的活动页在 iframe 里** —— `iframe.signin-center-iframe` → `kuku.baidu.com/operation/activitys/kukuPcSignAct/main`。该地址单独打开 body 为空，必须从工作台点签到卡标题打开弹窗。
2. **「去完成」是图片按钮** —— `<img class="pc-kuku-task-card__btn" src="btn_todo.png">`，DOM 里没有文字节点，只能靠图片名判状态（`btn_todo` / `btn_done` / `btn_invite`）。
3. **会员弹窗遮罩** —— 首页加载弹一次、打开任务中心又弹一次，会拦掉真实鼠标点击（Playwright 报 `click timed out`）。脚本先点 `activity-dialog-close`，仍被拦时退化为 DOM 级 `element.click()`。

另外「召唤任意专家」会弹《库库 AI 用户协议》，需要勾「我已阅读并同意」才会出现输入框。脚本会代点并写进 `notes`；不想让它代点就用 `--tasks` 排除 `expert_chat`。

更多细节见 `references/`。

## 边界

- 只操作用户本人账号的签到与官方公示任务，不涉及代签、刷量、多账号。
- 遇到验证码 / 滑块 / 风控会立即停止，不尝试绕过。
- 平台规则明确禁止脚本、插件、模拟器等自动化工具，**是否使用请自行判断并承担风险**。
- Cookie 等同账号登录凭据，不要提交到仓库、不要发给别人。

## 目录

```
SKILL.md                    Skill 主文件（触发词、工作流、排错表）
安装说明.txt                 给人看的快速上手
assets/activity.json        活动配置：周期、节点、选择器、任务清单（换期只改这里）
assets/cookie.example.json  Cookie 格式示例
references/checkin-rules.md 本期规则与页面结构实测
references/cloud-mode.md    参数、输出、定时任务、实测记录
references/changelog.md     版本变更
scripts/kukuai_checkin.py   主脚本
```
