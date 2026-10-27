# 云端签到 · Cookie 与脚本用法

本文件是 SKILL `kukuai-daily-checkin` 的配套参考：导出 Cookie → 跑脚本 → 注册每日定时任务。全程云端执行，**不需要本机浏览器**。

## 1. 适用场景

- 「帮我签到 / 领每日积分」——手动触发一次。
- 「每天定时自动签到」——注册每日定时任务。
- 云端执行，不依赖本机客户端在线，电脑关机也能签到。

## 2. 导出登录 Cookie

Cookie 等于登录凭据，只在本机/云端私有目录保存，不要外传。

### 方式一：浏览器开发者工具（最通用）
1. Chrome / Edge 打开并登录 `https://www.kukuai.cn/`（百度账号）。
2. `F12` → `Application`（应用）→ `Cookies` → `https://www.kukuai.cn`。
3. 复制 `Name` / `Value`（关键是 `BDUSS`、`STOKEN`），整理成 `assets/cookie.example.json` 的数组格式。

### 方式二：浏览器扩展（最快）
用「Cookie-Editor」类扩展一键导出当前站点 Cookie 为 JSON。

> ⚠️ `BDUSS` 通常是 HttpOnly，`document.cookie` 拿不到，必须用开发者工具面板或扩展。

> 💡 活动页面可能挂在 `kuku.baidu.com` 域下。若只导了 `.kukuai.cn` 的 Cookie 而活动页白屏/未登录，再补导一份 `kuku.baidu.com` 的。

## 3. Cookie 文件格式

脚本自动识别三种格式：

```jsonc
// 格式 1：Playwright / Puppeteer 导出的数组（推荐）
[
  {"name": "BDUSS", "value": "xxx", "domain": ".kukuai.cn", "path": "/"}
]

// 格式 2：{"cookies": [...]} 或 {"name": "value", ...} 映射
{"BDUSS": "xxx", "STOKEN": "yyy"}

// 格式 3：原始 Cookie 头字符串
BDUSS=xxx; STOKEN=yyy
```

格式 2/3 未写域名时默认补 `.kukuai.cn`。

## 4. 脚本用法

```bash
# 1) 首次 dry-run：校验登录态 + 打开任务中心解析状态（不签到）
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --out outputs/ --dry-run --probe-entry

# 2) 正式执行：签到 + 清可自动任务
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --out outputs/

# 3) 只签到
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --only-signin

# 4) 指定任务
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --tasks topic_chat,browse_square

# 5) 调试：显示浏览器窗口
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --headful --dry-run --probe-entry
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--cookies` | 自动查找 | 默认依次找 `~/.kukuai/cookies.json`、`~/.kukuai/cookies.txt`、`uploads/kukuai_cookies.json` |
| `--out` | `outputs` | 截图、Summary、日志输出目录 |
| `--log` | `<out>/log` | 日志目录（日志只写文件，stdout 只有 JSON） |
| `--state` | `~/.kukuai/state.json` | 连签状态文件，用于断签预警 |
| `--url` | `https://www.kukuai.cn/` | 入口官网（活动页在 iframe 内，**不能**直接填 iframe 地址） |
| `--dry-run` | 关 | 只探测，不签到不点任务 |
| `--probe-entry` | 关 | dry-run 时额外打开任务中心并解析状态 |
| `--headful` | 关 | 显示浏览器窗口（调试） |
| `--no-signin` | 关 | 只清任务不签到 |
| `--no-tasks` / `--only-signin` | 关 | 只签到不清任务 |
| `--tasks` | 空（全部） | 逗号分隔任务 key：`topic_chat,expert_chat,browse_square` |
| `--with-expert` | 关 | 自动做「召唤任意专家」；会代勾《库库 AI 用户协议》，默认不做 |
| `--timeout` | 30 | 单步超时秒数 |

## 5. 输出

| 产物 | 说明 |
| --- | --- |
| stdout JSON | `ok`、`stage`、`logged_in`、`signed_today`、`streak_days`、`next_node`、`activity`、`points`、`lottery_chances`、`tasks`、`warnings`、`screenshots`、`log` |
| `kukuai-summary-<时间>.md` | 可直接推给用户的 Markdown 汇总 |
| `kukuai-*.png` | 首页 / 活动页 / 签到后 / 最终 全页截图 |
| `log/kukuai_checkin_*.log` | 逐步日志 |
| `~/.kukuai/state.json` | 上次成功签到日期、连签天数、历史，用于断签预警 |

## 6. 注册每日定时任务

用「创建定时 / 自动化任务」建**每天固定时间**的周期任务，描述示例：

> 执行库库AI 每日签到：运行本 Skill 的 `scripts/kukuai_checkin.py`（Cookie 路径 `~/.kukuai/cookies.json`），完成后把 `kukuai-summary-*.md` 的内容推给我；若报登录态失效，提醒我重新导出 Cookie；若 warnings 里有断签或活动临期提示，单独提醒。

时间建议 09:00 前后，便于 Cookie 失效当天就能处理。

## 7. 安全与合规

- Cookie 等同账号登录态，**只存私有目录、勿外传、勿写入公开仓库**。
- 自动化仅用于用户本人账号的日常签到；遇到验证码 / 风控立即停止，不尝试绕过。
- 平台规则明确禁止脚本/插件/模拟器等自动化工具，是否使用请用户自行判断。

## 8. 实测记录（2026-10-27 校准）

用真实无头 Chromium 打开线上站点逐项验证过，改动都据此落地：

| 验证项 | 结果 |
| --- | --- |
| 未登录判定 | 未登录时首页**也有** `[data-testid="user-profile-trigger"]`，旧逻辑会误判为已登录；现改用「登录领网盘会员」「登录领取网盘SVIP」「登录后领取连签奖励」判负 |
| 签到卡位置 | 工作台左下角，`[data-testid="signin-promo"]`，未登录标题「登录领取网盘SVIP」、CTA「登录领奖」 |
| 每日奖励 | 卡片与日历均显示 **「积分+10」「抽奖+1」**（旧期 50，已修正） |
| 签到按钮真身 | 在 iframe 里：`button.pc-sign-btn`；主页面那个 CTA 只是入口 |
| 任务中心 | `iframe.signin-center-iframe` → `kuku.baidu.com/operation/activitys/kukuPcSignAct/main`，直连 body 为空 |
| 任务按钮 | `<img class="pc-kuku-task-card__btn">`，`btn_todo.png`=去完成、`btn_invite.png`=邀请好友，**无文字节点** |
| 任务清单 | 6 项（热门话题 / 下载登录PC端 / 邀请新用户 / 邀请好友对话 / 召唤专家 / 浏览知识广场） |
| 遮罩拦截 | 会员弹窗会让 Playwright 报 `click timed out`；先关 `activity-dialog-close`，再不行退化 DOM 点击 |
| 积分误匹配 | 「10.28 积分+10」曾被解析成 28 分，已加负向断言 |
| 连签误匹配 | 「连签3天」是节点标签，已限定只认「已连签/已签N天」 |
| SPA 链接 | 页面只有一个备案 `<a href>`，没有活动链接可扫，必须靠选择器/文案点击 |
| 已登录态（真实账号） | `button.pc-sign-btn` 显示「今日已签」；签到卡 CTA 变成「去抽会员」——**不能**再拿 CTA 当未登录信号，只有含「登录」时才算 |
| 任务按钮三态 | `btn_todo` 未完成 / `btn_done` 已完成 / `btn_invite` 需邀请，实测同一账号 5 张卡（3 todo、2 invite），跑完后 3 张变 done |
| 任务进度 | 标题里带 `(1/3)`、`(0/10)`，脚本按剩余次数补发，避免重复 |
| 专家任务 | 点「召唤」弹《库库 AI 用户协议》，勾「我已阅读并同意」→「继续使用」后才出现输入框 |
| 补签 | 日历历史日期带「补」，点击可补签；脚本不自动补签 |
| 积分 | 任务中心打开时主页面被遮挡，`points` 可能读不到；未遮挡时能读到（实测 2000） |

复验命令（无需真实 Cookie，验证到「登录态失效」即说明浏览器链路正常）：

```bash
python scripts/kukuai_checkin.py --cookies <任意假cookie> --dry-run
# 期望输出: {"stage": "login", "logged_in": false, "error": "登录态失效..."}
```

有真实 Cookie 时先跑：

```bash
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --dry-run --probe-entry
# 期望 notes 里出现「任务中心已打开，识别到任务 6/6」，dry_run_state.sign_btn_text 是真实按钮文案
```

