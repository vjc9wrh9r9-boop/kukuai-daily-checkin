---
name: kukuai-checkin-tasks
display_name: "库库AI 签到 + 每日任务"
version: "4.0.2"
updated: "2026-10-28"
activity: "每日签到得网盘SVIP月卡 · 做任务抽好礼 赢苹果笔记本（2026-10-21 ~ 2026-12-04）"
description: "库库AI（kuku.baidu.com / kukuai.cn，百度 AI 办公智能体）每日签到与每日任务的自动化。适配 2026-10-21 起的新一期活动「每日签到得网盘SVIP月卡」，连签 3/7/15/30 天解锁网盘 SVIP，做任务攒积分与抽奖次数。**任务进度分「网页端」和「PC 客户端」两套独立记录，脚本两端都做、都核验**。当用户提出「帮我签到」「自动签到」「领一下库库AI的每日积分」「完成库库AI每日任务」「今天签到成功没 / 连签几天了」等诉求时使用。本 Skill 自带 Cookie 抓取工具 tools/GetCookie.exe（双击即用），不要让用户手动按 F12。"
---

# 库库AI 签到 + 每日任务（v4.0.0 · 2026Q4 期）

> ## ⛔ 汇报纪律：只认接口核验，不认「我做了」
>
> v3 最大的坑：脚本说「已发 3 条对话」就报成功，用户打开客户端一看还是 **0/3**。
>
> 现在脚本只认两个接口：
>
> - `GET /api/taskscore/tasklist?task_from=<渠道>` → `task_finish_count / task_count_max`（真实进度）
> - `POST /api/genflowpro/activity/taskcomplete` → `errno=0` 才算上报成功
>
> **汇报时必须照抄 `task_board` 里的数字**，不许把 `actions` 里的「已发 3 条」当成完成。
> `task_board` 为空 / `warnings` 里有「读取任务接口失败」时，直接说「进度无法核验」，别猜。

## 为什么你看到「做完了」但客户端还是 0/3

库库AI 的每日任务是**分渠道统计**的：

| 渠道 | `task_from` | 任务数 | 谁会看到 |
| --- | --- | --- | --- |
| 网页端 | `kuku_signin_30_web` | 6 张（含「下载并登录库库PC客户端」） | 浏览器打开 kuku.baidu.com |
| PC 客户端 | `kuku_signin_30_pc` | 7 张（多「导入网盘文件」「上传本地文件」，少「下载客户端」） | 库库AI 桌面客户端里的任务中心 |

**签到是账号级、各端同步；每日任务进度互不相通。** 网页端把「聊热门话题」做到 3/3，客户端里仍然是 0/3——这就是上一版误报的根因。

v4 会两个渠道都做、都上报、都核验，所以 `task_board` 里会同时出现网页端和 PC 客户端的行。

> ## ⛔ 第一步：先启动 Cookie 工具（不可跳过）
>
> 本 Skill **自带抓取工具** `tools/GetCookie.exe`。用户点两下按钮就能拿到 Cookie。
> **不要**让用户按 F12 手动复制：大多数人不会用开发者工具，而且手动复制常漏 `STOKEN`。
>
> ### 情况 0：Agent 在云端/沙箱里，拿不到 `tools/GetCookie.exe`（最常见）
>
> 技能包是 zip，Agent 通常**解不开、也执行不了里面的 exe**。这种情况**别让用户解压**，
> 直接把下面这个**单文件下载链接**发给他（点开就下载，双击就能跑，不用解压）：
>
> > https://github.com/vjc9wrh9r9-boop/kukuai-daily-checkin/releases/download/v4.0.1/GetCookie.exe
>
> 附一句用法：「下载后双击 → 点 ① → 在打开的网页里点左下角签到卡『登录领奖』登录 → 状态条变绿后点 ② → 粘贴给我」。
>
> **工具路径**：本地安装时在 `<Skill目录>/tools/GetCookie.exe`。
>
> ### 情况 A：你能执行命令 → 直接拉起来
>
> ```bash
> explorer.exe "<Skill目录>/tools/GetCookie.exe"
> ```
>
> 拉起后告诉用户：
> 「在弹出的窗口点 **① 打开网页登录库库AI** → 登录 → 状态条变绿 → 点 **② 复制已抓取的 Cookie** → 粘贴给我」
>
> ### 情况 B：你启动不了 GUI（沙箱 / 无桌面 / 命令被拒）→ 让用户双击
>
> 仍然不要退回 F12。把下面这段发给用户（替换成真实路径）：
>
> > 双击这个文件：`<Skill目录>\tools\GetCookie.exe`
> > 点「① 打开网页登录库库AI，抓取 Cookie」→ 在弹出的浏览器里登录
> > → 状态条变绿（提示"抓取成功"）后，点「② 复制已抓取的 Cookie」
> > → 直接粘贴发给我
>
> ### 情况 C：用户说「我不会 / 有没有工具」
>
> 直接回答「有工具」，给出上面的路径与两个按钮的用法。**不要再讲 F12。**
>
> ### ❌ 明确禁止
>
> - 让用户按 F12 手动复制 `BDUSS` / `STOKEN`
> - 索要账号密码、验证码
> - 只回一句「请导出 Cookie 发我」就结束
>
> 手动 F12 只在用户**明确拒绝用工具**、且工具确实无法运行时作为最后兜底（见「方式 B」）。

> ### ✅ 「已复制 2 条」或「已复制 14 条」都正常，看登录域
>
> 库库AI 有两个前端入口，**两套 cookie 互不相认**，但背后是同一个账号、同一份任务进度：
>
> | 状态条 | 登录域 | 对应 cookie | 脚本走哪个入口 |
> | --- | --- | --- | --- |
> | 已复制 **2 条** | `kuku.baidu.com` | `BDUSS@.baidu.com` + `STOKEN@.kuku.baidu.com` | `https://kuku.baidu.com` |
> | 已复制 **14 条** | `www.kukuai.cn` | `BDUSS@.kukuai.cn`、`STOKEN@.passport.kukuai.cn` 等 | `https://www.kukuai.cn` |
>
> v4.0.2 起脚本会**先探测哪个域认这份 cookie**（`--dry-run` 的 `base_host` 字段可以看到），
> 不用再纠结抓了几条。工具也会标注「登录域」。
>
> 唯一要避免的是「工具说成功、但其实没登录」——现在必须接口 `errno=0` 才保存。

## 当前活动（2026-10-21 ~ 2026-12-04）

| 项 | 内容 |
| --- | --- |
| 活动名 | 每日签到得网盘SVIP月卡 · 做任务抽好礼 赢苹果笔记本 |
| 周期 | 2026-10-21 至 2026-12-04（以活动页实时展示为准） |
| 核心奖励 | 连签 **30 天必得**百度网盘 SVIP 月卡；连签 3 / 7 / 15 天解锁前置档位 |
| 每日签到 | 日历每格标「+10」与「抽奖+1」（实测），以页面为准 |
| 断签 | **清零回第 1 天**，已发奖品不回收 |
| 多端 | 签到天数各端同步；**每日任务进度不同步**（见上表） |
| 签到入口 | 工作台左下角签到卡（`[data-testid="signin-promo"]`）或活动页 `button.pc-sign-btn` |
| 活动页 | `https://kuku.baidu.com/operation/activitys/kukuPcSignAct/main`（可直连，无需从应用里点开） |

## 概述

用**无头浏览器 + Cookie** 完成每日签到与每日任务，并把**接口核验过的真实进度**回报给用户。不依赖本机浏览器，也不需要 PC 客户端在线。

## 交给其他 Agent / 朋友使用时的边界

| 会做 | 不会做 |
| --- | --- |
| 用**用户自己的** Cookie 登录 | 不索取账号密码、要验证码 |
| 点一次签到 | 不发邀请、不分享链接、不加好友 |
| 「聊热门话题」真发 N 条对话（N = 剩余次数） | 不发隐私内容 |
| 「浏览10s知识广场」真停留 14 秒 | 不浏览无关页面 |
| 「召唤专家」真召唤 + 真发一句话 | 首次协议弹窗不代勾（除非 `--with-expert`） |
| 「上传本地文件」往网盘传一个几百字节的占位 txt | 不上传用户的其他文件 |
| 「导入网盘文件」从网盘导入（需已授权） | 不删改用户网盘里的原有文件 |
| 截图 + 写摘要到 `outputs/` | 不把 Cookie 写进日志、不外传数据 |

**邀请类任务不做**（必须真人点链接）。这是能力边界，不是失败，汇报时说清楚即可。

## 🔰 快速上手

```bash
# 1) 先只读看两端进度，确认登录态（不签到、不动任务）
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --dry-run

# 2) 正式跑：签到 + 两个渠道的每日任务
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json

# 3) 首次用：专家协议 / 网盘授权想一次做掉（本人同意后再加）
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --with-expert --with-netdisk

# 只签到（不碰任务）
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --only-signin

# 只做网页端 / 只做客户端
python scripts/kukuai_checkin.py --cookies ~/.kukuai/cookies.json --channels web
```

> 🔒 本 Skill 不内置任何账号或登录态。每个人用自己的百度账号、自己抓的 Cookie。

## 运行链路（v4）

1. 注入 Cookie → 打开 `https://kuku.baidu.com/app` → 关活动弹窗 → 校验登录态
2. 打开活动页 → 读签到按钮文案 → 需要就打点 → 复核「今日已签」→ 记连签天数
3. 拉两个渠道的 `tasklist`，算出每项**真实剩余次数**
4. 按剩余次数执行真实动作：
   - 聊天：每次**新开一个会话**发 1 条 → 记下 `session_id`
   - 广场：进 `#/workbench/knowledge-square` 停留 14s
   - 专家：进 `#/workbench/expert` → 召唤 → 发 1 句
   - 上传：进 `#/workbench/netdisk` → 上传 → 看到文件名出现在列表
5. 用 `session_id` / 事件上报 `taskcomplete`（`jsToken` 必须带，否则 `errno=8002`）
6. **重新拉 tasklist 核验**，没到 max 就如实记「未达成」
7. 截图 + 输出 JSON + Markdown

## 参数

| 参数 | 作用 |
| --- | --- |
| `--dry-run` | 只读接口看两端进度，不签到、不动任务 |
| `--only-signin` / `--no-tasks` | 只签到 |
| `--no-signin` | 只做任务，不签到 |
| `--tasks topic_chat,expert_chat,browse_square,upload_local,import_netdisk` | 只跑指定的 |
| `--channels web` / `--channels pc` | 只做某个渠道（默认两个都做） |
| `--with-expert` | 首次召唤专家时代勾《库库 AI 用户协议》 |
| `--with-netdisk` | 首次导入网盘文件时代点「确定授权」 |
| `--no-upload` | 不往网盘传占位文件（「上传本地文件」这项就不做） |
| `--deadline 1200` | 整体硬超时，超时会输出 `stage=timeout` 而不是静默挂住 |

## 任务清单与自动化能力

| 任务 | 上限 | 奖励 | 出现在 | 脚本能否自动 |
| --- | --- | --- | --- | --- |
| 每日签到 | 1/天 | 积分+10、抽奖+1 | 两端 | ✅ 账号级，签一次两端都算 |
| 与库库聊聊热门话题 | 3/天 | 抽奖+1 | 两端 | ✅ 每条一个会话 + 上报 |
| 召唤任意专家并发起对话 | 1 | 抽奖+1 | 两端 | ✅ 首次需勾协议（`--with-expert`） |
| 浏览10s知识广场 | 1 | 抽奖+1 | 两端 | ✅ 停留 14s 后上报 |
| 去上传一次本地文件 | 1 | 抽奖+1 | 仅 PC 客户端 | ✅ 传一个占位 txt（`--no-upload` 可关） |
| 去导入一次网盘文件 | 1 | 抽奖+1 | 仅 PC 客户端 | ⚠️ 需先授权百度网盘（`--with-netdisk`） |
| 下载并登录库库PC客户端 | 1 | 网盘SVIP天卡、抽奖+1 | 仅网页端 | ❌ 装一次客户端即可（装了就没有这张卡） |
| 邀请新用户下载登录库库PC端 | 100 | SVIP天卡、积分+20 | 两端 | ❌ 需真人邀请 |
| 邀请好友与库库对话 | 10 | 积分+5、抽奖+1 | 两端 | ❌ 需真人邀请 |

> 任务定义与 ID 都在 `assets/activity.json`（`type_id` / `event_type` / `channels`），换期只改这个文件。

## 结果怎么读（汇报模板）

脚本输出 JSON，关键字段：

```json
{
  "ok": true,
  "signed_today": true,
  "streak_days": 2,
  "next_node": {"day": 3, "need": 1, "reward": "网盘SVIP天卡"},
  "channels": [
    {"key": "kuku_signin_30_web", "label": "网页端", "done": 3, "total": 6},
    {"key": "kuku_signin_30_pc",  "label": "PC客户端", "done": 4, "total": 7}
  ],
  "task_board": [
    {"label": "PC客户端", "name": "与库库聊聊热门话题", "finish": 3, "max": 3, "state": "已完成"}
  ],
  "actions": [{"key": "topic_chat", "result": "已完成（网页端 3/3、PC客户端 3/3）"}],
  "warnings": ["再签 1 天即可解锁「网盘SVIP天卡」"]
}
```

**给用户就这么说**：

1. 先报签到：今天签没签、连签几天、下一档还差几天
2. 再贴两边完成度：「网页端 3/6，PC 客户端 4/7」
3. 逐项说没做的和为什么（邀请要真人 / 导入要授权 / 客户端那张卡本来就不存在）
4. **不要**写「全部完成」「任务已清空」这类没说法的结论

## 已知接口错误码

| errno | 含义 | 处理 |
| --- | --- | --- |
| 0 | 成功 | — |
| 8002 | 系统繁忙（多为缺 `jsToken`） | 重新取 `window.jsToken` 再报 |
| 194001 | 会话不存在（聊天类没带 `session_id`） | 真发一条对话拿 `session_id` 再报 |
| 191005 | 服务繁忙（事件与任务不匹配，如带 `invite_code` 触发邀请事件） | 别带 `invite_code` |

## 失败处理与风控

| 现象 | 处理 |
| --- | --- |
| 未登录 / 登录态失效 | 提示重新抓 Cookie，**不代填账号密码** |
| 读取 tasklist 失败（`any(boards)` 为空） | 直接说「进度无法核验」，不要凭动作报成功 |
| 签到按钮文案仍是「立即签到」且没有成功提示 | 报「未确认签到」并给截图 |
| 出现验证码 / 滑块 / 风控 | **立即停止**，提示手动完成，不绕过 |
| 页面卡住 / 整体超时（`stage=timeout`） | 把 timeout 信息原样告诉用户，附日志路径 |
| 任务上报失败 | `warnings` 里有 errno，按上表处理；核验未达就写「未达成」 |

## 定时任务

> ⚠️ 这里的「定时任务」指 **Agent 自带的定时任务 / 自动化任务**，不是 Windows 计划任务（taskschd.msc）、不是 crontab。
> 用 `schtasks` / `crontab` 配的没人汇报结果。

建一条每天 09:00 前后的周期任务，描述写：用 `~/.kukuai/cookies.json` 运行 `scripts/kukuai_checkin.py`，把 `task_board` 的完成度推给用户；登录失效就提醒重新抓 Cookie；有断签/临期提醒就重点说。

## 合规提示

自动化仅用于**用户本人账号**的日常签到与官方公示任务，不涉及代签、刷量、多账号或绕过风控。平台规则对脚本类工具有限制，**是否使用需用户自行判断并承担风险**；遇到任何反自动化机制即刻停止。

## 资源

- `assets/activity.json` — 活动配置（周期、节点、渠道、任务 `type_id`/`event_type`）
- `scripts/kukuai_checkin.py` — 主脚本（签到 + 双渠道任务 + 接口核验）
- `references/checkin-rules.md` — 活动规则、奖励档位、常见问题
- `references/cloud-mode.md` — Cookie、参数、定时任务、GitHub Actions
- `references/changelog.md` — 版本变更（含 v4 的双渠道修复）
- `assets/cookie.example.json` — Cookie 文件格式示例
