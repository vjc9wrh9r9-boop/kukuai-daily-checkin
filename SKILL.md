---
name: kukuai-daily-checkin
display_name: "库库AI 每日签到"
version: "2.2.0"
updated: "2026-10-27"
activity: "每日签到得网盘SVIP月卡 · 做任务抽好礼 赢苹果笔记本（2026-10-21 ~ 2026-12-04）"
description: "库库AI（kukuai.cn / kuku.baidu.com，百度文库与百度网盘联合推出的 AI 办公智能体平台）每日签到与每日任务的云端自动化。当前适配 2026-10-21 起的新一期活动「每日签到得网盘SVIP月卡」，连签 3/7/15/30 天解锁网盘 SVIP，做任务攒积分与抽奖次数。当用户提出「帮我签到」「自动签到」「领一下库库AI的每日积分」「完成库库AI每日任务」「每天定时自动签到」「今天签到成功没 / 连签几天了」等诉求时使用。用导出的登录 Cookie 在云端跑脚本完成签到与任务，无需本机浏览器。"
---

# 库库AI 每日签到（云端 · 2026Q4 期）

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

## 🔰 快速上手

1. **导出 Cookie**：浏览器登录 `https://www.kukuai.cn/`（或 `https://kuku.baidu.com`），按 `references/cloud-mode.md` 导出（JSON 或字符串）。
2. **首次务必 dry-run**：`python scripts/kukuai_checkin.py --cookies <路径> --out outputs/ --dry-run --probe-entry`
3. **正式签到**：`python scripts/kukuai_checkin.py --cookies <路径> --out outputs/`
4. **要每天自动**：说「帮我建每天自动签到」，注册每日定时任务（见「定时任务」）。

> 🔒 本 Skill 不内置任何账号或登录态。每个人用自己的百度账号、自己导出的 Cookie，不要往 Skill 里写别人的真实 Cookie。

## 适用场景

- 「帮我签到 / 自动签到 / 领一下库库AI的每日积分」
- 「每天定时自动签到，我不用管」
- 「今天签到成功没？连签几天了？还差几天拿月卡？」
- 「把库库AI的每日任务也顺手清一下」

## 前置条件

1. **已导出登录 Cookie**：库库AI 用百度账号登录；签到依赖登录态（格式见 `assets/cookie.example.json`）。
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

建每天固定时间的周期任务（建议 09:00，便于 Cookie 失效时人工介入），任务描述写明：用 `~/.kukuai/cookies.json` 运行本 Skill 的 `scripts/kukuai_checkin.py`，完成后把 `kukuai-summary-*.md` 内容推给用户；出现「登录态失效」提醒重新导出 Cookie；`warnings` 里有断签或活动临期提示时重点提醒。

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
