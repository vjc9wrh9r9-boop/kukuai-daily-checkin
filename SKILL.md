---
name: kukuai-checkin-tasks
display_name: "库库AI 签到 + 每日任务"
version: "3.6.0"
updated: "2026-10-27"
activity: "每日签到得网盘SVIP月卡 · 做任务抽好礼 赢苹果笔记本（2026-10-21 ~ 2026-12-04）"
description: "库库AI（kukuai.cn / kuku.baidu.com，百度文库与百度网盘联合推出的 AI 办公智能体平台）每日签到与每日任务的云端自动化。当前适配 2026-10-21 起的新一期活动「每日签到得网盘SVIP月卡」，连签 3/7/15/30 天解锁网盘 SVIP，做任务攒积分与抽奖次数。当用户提出「帮我签到」「自动签到」「领一下库库AI的每日积分」「完成库库AI每日任务」「每天定时自动签到」「今天签到成功没 / 连签几天了」等诉求时使用。用导出的登录 Cookie 在云端跑脚本完成签到与任务，无需本机浏览器。"
---

# 库库AI 签到 + 每日任务（v3.0.0 · 2026Q4 期）

## 当前活动（2026-10-21 ~ 2026-12-04）

| 项 | 内容 |
| --- | --- |
| 活动名 | 每日签到得网盘SVIP月卡 · 做任务抽好礼 赢苹果笔记本 |
| 周期 | 2026-10-21 至 2026-12-04（以活动页实时展示为准） |
| 核心奖励 | 连签 **30 天必得**百度网盘 SVIP 月卡；连签 3 / 7 / 15 天解锁前置档位 |
| 每日签到 | 首页签到卡每格显示「积分+10」（实测），另给抽奖次数，以页面为准 |
| 断签 | **清零回第 1 天**，已发奖品不回收 |
| 多端 | 库库PC客户端 / 网页版 / 手机端签到天数互通，同账号同一份记录 |
| 签到入口 | 工作台**左下角签到卡**（`data-testid="signin-promo"`，标题「登录领取网盘SVIP」→ CTA「登录领奖 / 立即签到」） |
| 活动页 | 顶部活动横幅 `button.activity-banner`（规则 / 奖品 / 去抽奖 / 任务清单都在这里） |

> 上个月那期（9.29–10.31，点头像菜单领「领取50」、7 天循环）的入口与按钮已全部失效。旧版流程别再用，见 `references/changelog.md`。

## 概述

用**云端脚本**完成每日签到与每日任务，并把结果（是否签到成功、连签天数、下一节点还差几天、积分、抽奖次数、各任务状态、截图）回报给用户。全程在云端无头浏览器里用登录 Cookie 完成，**不依赖本机浏览器，也不需要本机客户端在线**。

签到本身在首页就能完成（左下角签到卡），任务清单需要再进活动页，因此脚本分两段执行。

## 交给其他 Agent / 朋友使用时的边界

这个 Skill 只做下面这些动作，超出的都不做。别人接手时按这张表核对即可：

| 会做 | 不会做 |
| --- | --- |
| 打开 kukuai.cn，用**你自己的** Cookie 登录态 | 不索取账号密码、要验证码 |
| 点一次签到 | 不发邀请、不分享链接、不加好友 |
| 「与库库聊聊热门话题」发 3 条行业类问题 | 不发任何隐私内容、不上传本地文件 |
| 「浏览10s知识广场」停留 12 秒 | 不浏览与任务无关的页面 |
| 截图 + 写一份结果摘要到本地 `outputs/` | 不把 Cookie 写进日志、不回传任何数据到外部服务 |

两项默认关闭，要本人确认才开：

| 任务 | 为什么默认关 | 怎么开 |
| --- | --- | --- |
| 召唤任意专家 | 会弹《库库 AI 用户协议》，勾同意是本人行为 | `--with-expert` |
| 邀请类任务 | 必须真人 | 不支持自动化 |

前置动作一律先 `--dry-run`：只校验登录态和页面结构，不签到、不点任务，确认没问题再正式跑。

## 🔰 快速上手

1. **拿到 Cookie**：双击 `tools/GetCookie.exe` → 弹出的窗口里登录 → 自动存到 `~/.kukuai/cookies.json`。三种方式见下节。
2. **首次务必 dry-run**：`python scripts/kukuai_checkin.py --cookies <路径> --out outputs/ --dry-run --probe-entry`
3. **正式签到**：`python scripts/kukuai_checkin.py --cookies <路径> --out outputs/`
4. **要每天自动**：说「帮我建每天自动签到」，让 Agent 建一个**它自己的定时任务 / 自动化任务**（见「定时任务」）。注意是 Agent 内置的自动化，不是 Windows 计划任务 / crontab。

> 🔒 本 Skill 不内置任何账号或登录态。每个人用自己的百度账号、自己导出的 Cookie，不要往 Skill 里写别人的真实 Cookie。

## 适用场景

- 「帮我签到 / 自动签到 / 领一下库库AI的每日积分」
- 「每天定时自动签到，我不用管」
- 「今天签到成功没？连签几天了？还差几天拿月卡？」
- 「把库库AI的每日任务也顺手清一下」

## 拿到 Cookie（三种方式，推荐 A）

### A. 让 Agent 拉起 exe（推荐，最省事）

**当用户选择「用 Cookie 抓取 exe」这种方式时，Agent 直接打开 exe 让用户自己登录，不要代填账号密码、不要索要密码。**

```bash
explorer.exe "C:\Users\<用户名>\.workbuddy\skills\kukuai-checkin-tasks\tools\GetCookie.exe"
```

> 必须用 `explorer.exe` 拉起：Agent 工具会话里直接 exec 的进程会随命令结束被回收，用 explorer 启动才不会被杀。

exe 打开后是一个小窗口，**不会自己开网页**，只有两个按钮：

| 按钮 | 行为 |
| --- | --- |
| ① 打开网页登录库库AI，抓取 Cookie | 用**系统默认浏览器**开独立窗口（临时配置，不碰日常数据）→ 打开**网页版工作台** `https://kuku.baidu.com/app`（签到活动就在这个域，邀请页另开标签）→ 用户点**左下角签到卡上的「登录领奖」**（或右上角头像）用百度账号登录 → 判定以 `kuku.baidu.com` 的 `userreport` 接口为准，`errno=0` 才算成功，随即保存到 `~/.kukuai/cookies.json`，状态条变绿「抓取成功（工作台已确认登录）」 |
| ② 复制已抓取的 Cookie | 把已保存的 Cookie 复制到剪贴板，状态条显示「已复制 N 条，去 Agent 对话里 Ctrl+V」 |

失败也会在状态条变红说明原因（浏览器被关掉 / 超时未登录 / 没找到可用浏览器 / 调试端口被拦）。

**Agent 的正确做法**：拉起 exe → 告诉用户「点第 ① 个按钮，在弹出的工作台里点**左下角签到卡上的「登录领奖」**登录，成功后回来点第 ② 个按钮复制」→ 等用户把 Cookie 粘过来。**不要代点、不要代填账号密码。**

> **两个域是两套会话（实测 2026-10-27）**：`www.kukuai.cn` 和 `kuku.baidu.com/app` 是同一个应用的两个入口，但登录态各自独立。
> 签到活动（iframe `kuku.baidu.com/operation/activitys/kukuPcSignAct/main`）在 `kuku.baidu.com` 域，
> 所以**必须在 `https://kuku.baidu.com/app` 登录**；只在 `www.kukuai.cn` 登录会出现「工作台已登录、签到卡却还是登录领奖」。
>
> 另外：不要把 `.kukuai.cn` 的 BDUSS 复制到 `.kuku.baidu.com`，会让活动页跳百度登录并重定向死循环（实测 ERR_TOO_MANY_REDIRECTS）。

### A2. 用户把 Cookie 粘过来了怎么办

用户从剪贴板粘贴过来的通常是一段 JSON 数组（也可能是 `BDUSS=...; STOKEN=...` 形式）：

1. 先判断格式：以 `[{` 开头 → 当 JSON 解析；含 `BDUSS=` → 当 Cookie 字符串解析
2. 校验必须含 `BDUSS`，否则提示重新抓
3. 归一化后写入 `~/.kukuai/cookies.json`（JSON 数组带 `domain`，两个域都保留）
4. 立刻跑一次 `--dry-run` 验证登录态，再正式执行
5. **不要**在回复里回显 Cookie 明文

### B. 浏览器开发者工具（没有 exe 时用）

1. Chrome / Edge 登录 `https://kuku.baidu.com/home`（或 `https://www.kukuai.cn/`）
2. `F12` → Application（应用）→ Cookies → 对应的域
3. 复制 `BDUSS`、`STOKEN` 的值（`BDUSS` 是 HttpOnly，只能在面板里复制）
4. 存成 `~/.kukuai/cookies.json`：

```json
{"BDUSS": "你的值", "STOKEN": "你的值"}
```

### C. 直接把 Cookie 粘给 Agent

把 `BDUSS=...; STOKEN=...` 粘进对话，让 Agent 帮你写入 `~/.kukuai/cookies.json`。
Agent 落盘前会先清理空条目、归一化域名。

> 活动内容在 `kuku.baidu.com` 域下，只导 `.kukuai.cn` 有时会判未登录。
> 用 A 方式会自动把两个域都抓下来，最稳。

## 前置条件

1. **已拿到登录 Cookie**：库库AI 用百度账号登录；签到依赖登录态（方式见上节，格式见 `assets/cookie.example.json`）。
2. **Cookie 未过期**：过期会报「登录态失效」，重新导出即可。
3. **不要索取账号密码**：只用 Cookie。除非用户主动明确提供，否则不要代填密码或验证码。

## 工作流

### 1. 准备 Cookie

见 `references/cloud-mode.md`。用户直接粘贴时先清理（丢空名条目、归一化域名）再落盘到 `~/.kukuai/cookies.json`。

### 2. 运行脚本

```bash
# 首次：只探测，不签到不点任务，并打开任务中心解析当前状态
python scripts/kukuai_checkin.py --cookies <cookie路径> --out outputs/ --dry-run --probe-entry

# 正式：签到 + 清全部可自动任务
python scripts/kukuai_checkin.py --cookies <cookie路径> --out outputs/

# 连「召唤专家」也做（会代勾用户协议，需本人明确同意后再用）
python scripts/kukuai_checkin.py --cookies <cookie路径> --out outputs/ --with-expert

# 只签到，不动任务
python scripts/kukuai_checkin.py --cookies <cookie路径> --only-signin

# 指定任务（去掉不想跑的）
python scripts/kukuai_checkin.py --cookies <cookie路径> --tasks topic_chat,browse_square
```

执行链路：注入 Cookie → 打开官网 → 关会员弹窗 → 校验登录态 → 点签到卡标题打开任务中心（iframe）→ 读签到按钮文案判断今日是否已签 → 点 `button.pc-sign-btn` 签到 → 复核状态 → 逐张任务卡按图片按钮状态点击 → 截全页图 → 输出 JSON + Markdown 汇总。

**登录态判定**（已按线上实测修正）：未登录时首页同样存在 `[data-testid="user-profile-trigger"]`，不能用它判断；实际信号是文案「登录领网盘会员」「登录领取网盘SVIP」以及签到卡 CTA 为「登录领奖」。

### 3. 上报结果

脚本产出 `outputs/kukuai-summary-<时间>.md`，直接把它（或 JSON 关键字段）作为答复内容。核心字段：

```json
{
  "ok": true,
  "signed_today": true,
  "streak_days": 2,
  "next_node": {"day": 3, "need": 1, "reward": "网盘SVIP天卡"},
  "activity": {"period": "2026-10-21 ~ 2026-12-04", "days_left": 38},
  "points": 1830,
  "lottery_chances": 4,
  "tasks": [{"name": "与库库聊聊热门话题", "result": "对话 3/3"}],
  "warnings": ["再签 1 天即可解锁「网盘SVIP天卡」"]
}
```

### 4. 定时任务

> ⚠️ 这里说的「定时任务」指 **Agent 自带的定时任务 / 自动化任务**（在 Agent 界面里新建的那条周期任务），**不是 Windows 计划任务（taskschd.msc）、不是 crontab、也不是开机启动项**。不要用 `schtasks` / `crontab` 去配，配了也不受 Agent 管，结果没人汇报。

在 Agent 里建一条每天固定时间的周期任务（建议 09:00 前后，便于 Cookie 失效当天人工处理），任务描述写明：用 `~/.kukuai/cookies.json` 运行本 Skill 的 `scripts/kukuai_checkin.py`，完成后把 `kukuai-summary-*.md` 内容推给用户；出现「登录态失效」提醒重新导出 Cookie；`warnings` 里有断签或活动临期提示时重点提醒。

区别：

| 方式 | 谁触发 | 能不能把结果推给你 | 电脑关机时 |
| --- | --- | --- | --- |
| Agent 定时任务 / 自动化任务 | Agent 客户端 | 能，按对话汇报 | 不能（客户端没开就不跑） |
| Windows 计划任务 / crontab | 操作系统 | 不能，只能自己写日志 | 不能 |
| GitHub Actions | GitHub 云端 | 能用 issue / 仓库页面看 | **能**（推荐给「不想开电脑」的场景） |

## 任务清单与自动化能力

| 任务 | 上限 | 奖励 | 脚本能否自动 |
| --- | --- | --- | --- |
| 每日签到 | 1/天 | 积分+10、抽奖+1 | ✅ 主流程 |
| 与库库聊聊热门话题 | 3/天 | 抽奖+1（积分奖励以页面为准） | ✅ 按剩余次数发对话 |
| 召唤任意专家并发起对话 | 1 | 抽奖+1 | ⚠️ 默认跳过，加 `--with-expert` 才做 |
| 浏览10s知识广场 | 1 | 抽奖+1 | ✅ 停留 12s |
| 邀请新用户下载登录库库PC端 | — | 网盘SVIP天卡、抽奖+1 | ❌ 需真人邀请 |
| 邀请好友与库库对话 | 10 | 抽奖+1 | ❌ 需真人邀请 |

> - 实测账号只展示 **5 张任务卡**；部分账号会多出「下载并登录库库PC客户端」（需装客户端），脚本不处理。
> - 本期**没有**「上传本地文件」「导入网盘文件」任务（上一版照第三方攻略写的，实测不存在）。
> - 日历支持**补签**（历史日期标「补」），脚本不自动补签，避免消耗道具。

任务卡右侧是图片按钮，脚本按图片名判状态：

| 图片 | 含义 | 脚本动作 |
| --- | --- | --- |
| `btn_todo.png` | 未完成，可做 | 点 `.pc-kuku-task-card__action` |
| `btn_done.png` | 已完成 | 跳过并记为完成 |
| `btn_invite.png` | 需邀请好友 | 跳过（需真人） |

> 「召唤任意专家」会弹《库库 AI 用户协议》确认框。**默认不做这一项**，因为它需要勾「我已阅读并同意」，属于本人的同意行为，脚本不该替人做主。本人确认后自己加 `--with-expert` 才会代勾，并在 `notes` 里写明。

任务定义都在 `assets/activity.json`，加任务或改文案只改这个文件。

## 页面结构（决定了怎么写自动化）

| 层 | 位置 | 内容 | 选择器 |
| --- | --- | --- | --- |
| 主页面 | 工作台左下角 | 签到卡：标题 / 副标题 / 5 个日格 / CTA | `[data-testid="signin-promo"]`、`-cta`、`-title` |
| 弹窗 | 全屏弹层 | 任务中心外壳 + iframe | `iframe.signin-center-iframe` |
| **iframe** | `kuku.baidu.com/operation/activitys/kukuPcSignAct/main` | 连签日历、`button.pc-sign-btn` 签到按钮、6 张任务卡、规则/奖品 | 见下 |
| 任务卡 | iframe 内 | `.pc-kuku-task-card`，标题 `.pc-kuku-task-card__title`，按钮是**图片** `.pc-kuku-task-card__btn` | `btn_todo`=去完成 / `btn_done`=已完成 / `btn_invite`=邀请好友 |

三个坑（都已处理）：
1. **iframe 不能直接打开**，直连该地址 body 为空，必须从应用内点签到卡标题。
2. **任务按钮是图片不是文字**，「去完成」在 DOM 里没有文本节点，只能按 `.pc-kuku-task-card__btn` 的 `src` 判断状态再点 `.pc-kuku-task-card__action`。
3. **会员弹窗遮罩**：首页加载弹一次、打开任务中心又弹一次，会拦掉真实鼠标点击。脚本会主动关 `[data-testid="activity-dialog-close"]`，仍被拦时退化为 DOM 级 `element.click()`。
4. **专家任务有协议确认**：点「召唤」后弹《库库 AI 用户协议》，必须勾「我已阅读并同意」再点「继续使用」，否则永远没有输入框。**默认跳这项**，加 `--with-expert` 才代勾。

## 失败处理与风控

| 现象 | 处理 |
| --- | --- |
| 未登录 / 登录态失效 | 提示重新导出 Cookie。**不要代填账号密码。** |
| 未找到 Cookie 文件 | 提示提供 Cookie，或说明默认查找路径。 |
| 签到卡没出现 | 脚本会自动重开；仍没有说明卡片被关或改版，用 `--dry-run` 看截图，必要时改 `selectors.signin_cta`。 |
| 任务中心打不开 | 签到不受影响（会走签到卡 CTA 兜底），任务跳过并在 `warnings` 标注；截图看 `[data-testid="signin-promo-title"]` 是否还存在。 |
| 签到按钮找不到 | 页面改版。改 `assets/activity.json` 的 `selectors.signin_btn`（当前 `button.pc-sign-btn`）与 `signin_texts`，再 dry-run 验证。 |
| 任务卡点不动 | 先看 `card_state` 读到的图片名。`btn_invite` 表示需真人邀请，属正常跳过；`btn_todo` 点不动多为遮罩，脚本已退化 DOM 点击，仍失败就截图排查。 |
| 出现验证码 / 滑块 / 风控提示 | **立即停止**自动操作，提示用户手动完成，不要绕过。 |
| 签到后按钮仍显示「登录领奖」 | Cookie 实际无效（伪登录态）。按登录失效处理，别谎报成功。 |
| 提示「今日已签」 | 正常，报告今天已完成并给出连签天数。 |
| 断签 | 提示连签已清零、当前回到第 1 天，从今天重新累计。 |

## 合规提示

自动化仅用于**用户本人账号**的日常签到与官方公示任务，不涉及代签、刷量、多账号或绕过风控。平台规则明确禁止脚本/插件/模拟器/群控等自动化工具与多账号参与，**是否使用本 Skill 需用户自行判断并承担风险**；遇到任何反自动化机制即刻停止。

## 资源

- `assets/activity.json` — **当前活动配置**（周期、节点、入口文案、签到按钮文案、任务清单）。换期只改这里。
- `scripts/kukuai_checkin.py` — 签到主脚本（Cookie 注入，输出 JSON + Markdown）
- `references/checkin-rules.md` — 本期活动规则、奖励档位、常见问题
- `references/cloud-mode.md` — 导出 Cookie、脚本参数、定时任务
- `references/changelog.md` — 版本变更（9 月期 → 10 月期改了什么）
- `assets/cookie.example.json` — Cookie 文件格式示例
