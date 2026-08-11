# Herdr Agent Manager

[English](README.md) | **中文**

一个用于 [Herdr](https://herdr.dev) 的本地插件，让你快速搜索/选择当前 session 中的 agent 和 workspace，并给 agent 发送消息。

---

## 功能

- **Agent 选择器** (`prefix + a`)
  - `fzf` 模糊搜索所有 agent，列表带表头：`NAME | WORKSPACE* | STATUS~ | TITLE`
    - `WORKSPACE*`：可修改
    - `STATUS~`：只读，来自 agent 本身的运行状态
    - 搜索匹配列表中显示的全部内容（name / workspace / title），中文关键词也能命中
  - 右侧预览 agent 的 workspace、状态、cwd、标题 以及最近 30 行彩色输出
  - 选中后可以执行多种操作：发消息 / 修改 workspace / 修改 tab / 重命名 / 设置 pane label / 聚焦 / 关闭 pane
  - 没有 explicit name 的 agent 会自动回退用 `terminal_id` 作为标识，列表不会因缺字段而崩溃
  - 快捷重命名（跳过 `Alt + m` 子菜单）：`Alt + t` 直接重命名当前 agent（title / 名称），`Alt + l` 直接设置当前 pane 的 label
  - `Alt + n`：以当前选中 agent 的 cwd 为工作目录创建一个新 workspace（label 可留空，留空时 herdr 会用 cwd 的 basename 自动命名）

- **Workspace/Space 选择器** (`prefix + w`)
  - 以**树状层次结构**展示 `workspace → tab → agent/pane`
  - 选中任意层级（workspace / tab / agent / pane）后按 `Enter` 聚焦该节点，按 `Alt + m` 打开修改菜单
  - 选中 agent / pane 节点回车时，会先 `tab focus` 到所在 tab，再 `agent focus` 到对应 pane，确保真正切换过去
  - 支持操作：聚焦、重命名、设置 pane label、移动、关闭、发送消息
  - 移动能力：agent / pane 可移动到**任意 workspace 的任意 tab**（`Move to tab` 现在跨 workspace 列出目标，选项里标了 `workspace / tab`）；整个 tab 可移动到**其他 workspace**（`Move tab to workspace`，内部新建目标 tab 并把源 tab 的所有 pane 搬过去，源 tab 自动关闭）
  - 快捷重命名（跳过 `Alt + m` 子菜单）：`Alt + t` 直接重命名当前节点（agent 名称，或 workspace / tab 的 label），`Alt + l` 直接设置当前 pane 的 label（仅 agent/pane 节点）
  - `Alt + n`：以当前光标所在节点的目录为工作目录创建一个新 workspace。光标在 agent/pane 上取该 pane 的 cwd，在 workspace/tab 上取其内部 focused pane 的 cwd；label 可留空（留空时 herdr 用 cwd 的 basename 自动命名）。创建后不自动切换焦点，新 workspace 会出现在刷新后的树里，按 Enter 即可聚焦
  - `Ctrl + r`：手动原地刷新树（在自动刷新之上的兜底，比如你想立刻强制重拉一次）。选择器本身已**自动实时刷新**（见下），通常无需手动按。
  - **自动实时刷新**：picker 打开期间有一个后台 watcher 线程，每 0.5 秒检查一次 herdr 状态指纹（workspaces/tabs/panes 的 label、归属、agent 状态）。你在**别的 pane** 里编辑/移动/重命名/新建/关闭了任何 pane 或 tab，watcher 检测到变化后会通过 fzf 的 `--listen` socket 自动让列表 reload 最新树——**不用关重开、不用按键**。这是为了解决"编辑完一个 pane，picker 还显示旧状态"的问题：回到还开着的 picker，列表已经是新的了。每次 reload 都重新调 `herdr api snapshot`（~3.6ms）+ 重建树（~6ms），准确且不卡。
  - 搜索时**保持树状嵌套顺序**：列表用 `--no-sort` 渲染，输入关键词筛选时**不会**按匹配度重排——子节点（如 `tab travel`）始终紧跟其父 workspace（如 `travel-rule`）之后，不会因为"匹配度更高"而漂到列表最上方脱离父节点。这样移动完一个 tab 后搜它的名字，能直接在它所属 workspace 下方看到它
  - 右侧 preview 会根据选中类型展示对应信息

---

## 关于表头标记

| 标记 | 含义 |
|---|---|
| `*` | 该列内容可修改 |
| `~` | 该列内容只读，由 Herdr/agent 自身决定 |

agent 列表：`NAME | WORKSPACE* | STATUS~ | TITLE`

- `WORKSPACE*`：agent 的 workspace 可以被修改（Move to another workspace）
- `STATUS~`：agent 的 `idle/working/blocked/unknown` 状态是只读的

workspace 选择器：**树状结构**，任意节点都可修改：

- `workspace` 节点：可重命名、关闭
- `tab` 节点：可重命名、**移动到其他 workspace**、关闭
- `agent/pane` 节点：可发送消息、重命名、设置 pane label、**移动到任意 workspace 的任意 tab**、关闭

---

## 关于“选中预览框”

`fzf` 的预览框（preview）**本身不能被选中或交互**，它是只读的。

如果你想“选中一个 agent 后对它做点什么”，可以通过 fzf 列表项选中 + 快捷键组合来实现。当前已经给列表项绑了几个动作键。

---

## 目录结构

```text
agent-manager/
├── .gitignore              # git 忽略规则
├── herdr-plugin.toml       # 插件清单
├── README.md               # 英文文档
├── README.zh-CN.md         # 本文件（中文）
├── install.sh              # 一键安装脚本
└── bin/
    ├── agent-manager.py    # agent 选择器入口
    ├── agent-preview.py    # agent 右侧预览
    ├── space-picker.py     # workspace 树状选择器入口
    ├── space-preview.py    # workspace 右侧预览（旧版，已被 tree-preview 替代）
    └── tree-preview.py     # 树状选择器的右侧预览
```

---

## 安装

### 通过 `herdr plugin install` 安装（推荐）

只要装了 herdr >= 0.7.0，就能用一条命令直接从 GitHub 安装，无需手动 clone 或拷贝：

```bash
herdr plugin install bleedingfight/herdr-agent-manager --yes
```

herdr 会拉取仓库、放到 `~/.config/herdr/plugins/github/` 下、链接插件
（plugin id：`local.agent-manager`）并重载配置。然后按下文的
[配置快捷键](#配置快捷键)添加——推荐用 `plugin_action` 形式，它不依赖安装
路径，插件更新后依然有效——再重载一次即可：

```bash
herdr server reload-config
```

装完后按 `ctrl+b a` 和 `ctrl+b w` 就能用。

日后更新只需再跑一遍同样的 `herdr plugin install` 命令（或加
`--ref <tag>` 指定某个 tag）；卸载用 `herdr plugin uninstall local.agent-manager`。

### 通过 install.sh 安装（本地 clone）

在插件目录内执行：

```bash
~/.config/herdr/plugins/local/agent-manager/install.sh
```

脚本会自动：

1. 检查 `herdr` 是否已安装
2. 把插件复制到 `~/.config/herdr/plugins/local/agent-manager`（若已存在则备份为 `*.backup.<时间戳>`）
3. `chmod +x bin/*.py`
4. 执行 `herdr plugin link`
5. 在 `~/.config/herdr/config.toml` 里追加快捷键（若已存在则跳过）
6. 执行 `herdr server reload-config`

装完后直接按 `ctrl+b a` 和 `ctrl+b w` 就能用。

### 更新 / 重装

插件是纯本地目录，直接覆盖即可：

```bash
# 方式一：重新跑 install.sh（会自动备份旧目录）
./install.sh

# 方式二：手动覆盖后重载
cp -R /path/to/agent-manager ~/.config/herdr/plugins/local/agent-manager
herdr server reload-config
```

注意：herdr 自身升级不会覆盖本插件目录（不在 herdr 二进制范围内），但插件自带的 `agent-manager` 仓库如果重新 clone 安装，会覆盖你对 `bin/*.py` 的本地改动 —— 请自行备份补丁。

### 手动安装

```bash
mkdir -p ~/.config/herdr/plugins/local
cp -r /path/to/agent-manager ~/.config/herdr/plugins/local/
herdr plugin link ~/.config/herdr/plugins/local/agent-manager
```

然后手动把下面的快捷键加到 `~/.config/herdr/config.toml`（注意把路径里的 `~` 换成你的真实家目录）：

```toml
[[keys.command]]
key = "prefix+a"
type = "pane"
command = "~/.config/herdr/plugins/local/agent-manager/bin/agent-manager.py"

[[keys.command]]
key = "prefix+w"
type = "pane"
command = "~/.config/herdr/plugins/local/agent-manager/bin/space-picker.py"
```

最后重载配置：

```bash
herdr server reload-config
```

如果修改了 `herdr-plugin.toml`，需要重新 link：

```bash
herdr plugin unlink local.agent-manager
herdr plugin link ~/.config/herdr/plugins/local/agent-manager
```

---

## 配置快捷键

在 `~/.config/herdr/config.toml` 中添加。推荐用 `type = "plugin_action"`
形式，它按 id 引用插件的 action，不依赖安装路径——`herdr plugin install`
和本地 clone 两种装法都适用，插件更新后也不会失效：

```toml
[[keys.command]]
key = "prefix+a"
type = "plugin_action"
command = "local.agent-manager.picker"
description = "Pick agent and send message"

[[keys.command]]
key = "prefix+w"
type = "plugin_action"
command = "local.agent-manager.space-picker"
description = "Pick workspace/space"
```

如果你更想直接指向脚本（例如本地 clone 的场景），可以用绝对路径形式。
herdr 不会自动展开 `~`，请换成你的真实家目录：

```toml
[[keys.command]]
key = "prefix+a"
type = "pane"
command = "/home/you/.config/herdr/plugins/local/agent-manager/bin/agent-manager.py"

[[keys.command]]
key = "prefix+w"
type = "pane"
command = "/home/you/.config/herdr/plugins/local/agent-manager/bin/space-picker.py"
```

默认 prefix 是 `ctrl+b`，所以：

- `ctrl+b a`：打开 agent 选择器
- `ctrl+b w`：打开 workspace 选择器

然后重载配置：

```bash
herdr server reload-config
```

---

## 使用流程

### 给 agent 发消息 / 执行操作

```text
按 ctrl+b a
 → fzf 列出所有 agent（带 NAME / WORKSPACE* / STATUS~ / TITLE 表头）
 → 搜索 / 方向键选中
 → 按对应按键执行操作：
     Enter       输入消息并发送，发送后仍回到 fzf 继续选择
     Alt + m    打开修改菜单：移动 workspace / 移动 tab / 重命名 / 设置 pane label
     Alt + t     直接重命名当前 agent（title / 名称），跳过子菜单，完成后回到 fzf
     Alt + l     直接设置当前 pane 的 label，跳过子菜单，完成后回到 fzf
     Alt + n     以当前 agent 的 cwd 创建新 workspace（label 可留空），完成后回到 fzf
     Ctrl + r    快速重命名 agent，完成后回到 fzf
     Ctrl + f    聚焦 agent 并退出选择器
     Ctrl + x    关闭 agent 所在 pane（需确认），然后退出
     Esc         直接退出

表头标记：
  WORKSPACE*   可修改
  STATUS~      只读（agent 自身状态，不能改）

修改菜单内选项：
  - Move to another workspace   （在 workspace 列表里选中时还可以 Ctrl-r 重命名该 workspace）
  - Move to another tab          （跨 workspace 列出所有 tab，选项格式 `workspace / tab`）
  - Rename this agent
  - Set pane label
  - Cancel
```

### workspace / tab / agent 树状选择器

```text
按 ctrl+b w
 → fzf 以树状列出 workspace → tab → agent/pane
 → 搜索 / 方向键选中任意层级
 → 按 Enter 聚焦该节点
 → 或按 Alt + t 直接重命名当前节点（agent 名称 / workspace / tab label）
 → 或按 Alt + l 直接设置当前 pane 的 label（仅 agent/pane 节点）
 → 或按 Alt + n 以当前节点目录创建新 workspace（label 可留空）
 → 或按 Ctrl + r 刷新树（重新拉取 snapshot，原地刷新，不退出选择器）
 → 或按 Alt + m 打开修改菜单：
     workspace 节点：Rename workspace / Close workspace
     tab 节点：Rename tab / Move tab to workspace / Close tab
     agent/pane 节点：Send message / Rename / Set pane label / Move to workspace / Move to tab / Close
```

---

## 自定义

### 调整预览中 agent 输出长度

编辑 `bin/agent-preview.py`：

```python
out = herdr("agent", "read", name, "--source", "recent", "--format", "ansi", "--lines", "30")
```

把 `--lines` 后面的数字改成 `50` / `100` 即可显示更多行。

### 调整选中行背景色

编辑 `bin/agent-manager.py` 和 `bin/space-picker.py` 里的：

```python
fzf_colors = "bg+:#3b4261,fg+:#ffffff"
```

修改 `#3b4261` 为你想要的高亮背景色。

---

## 版本管理

这个插件目录本身已经是一个 Git 仓库，初始化提交已完成。

```bash
cd ~/.config/herdr/plugins/local/agent-manager
git log --oneline
```

日常开发或修改后，按常规 Git 流程提交：

```bash
git add .
git commit -m "your change description"
```

### 推送到 GitHub/GitLab

```bash
git remote add origin git@github.com:<your-username>/herdr-agent-manager.git
git push -u origin main
```

别人安装时可以直接 clone 再运行 install 脚本：

```bash
git clone git@github.com:<your-username>/herdr-agent-manager.git
# 或者 https://github.com/<your-username>/herdr-agent-manager.git
cd herdr-agent-manager
./install.sh
```

这样你就可以通过正常的 PR / 分支 / tag 来管理这个插件了。

---

## 卸载

```bash
herdr plugin unlink local.agent-manager
rm -rf ~/.config/herdr/plugins/local/agent-manager
```

然后删除 `~/.config/herdr/config.toml` 中对应的 `[[keys.command]]` 配置并 `herdr server reload-config`。

---

## 依赖

- [Herdr](https://herdr.dev) >= 0.7.0
- [fzf](https://github.com/junegunn/fzf)
- Python 3

---

## 已知限制

- 插件通过 `herdr agent send` + `herdr pane send-keys Return` 发送消息，接收 agent 必须能读取终端输入（对 kscc / Claude Code / Codex 等有效）。
- 如果目标 agent 正在忙（例如 kscc 处于 Thinking 状态），消息会排队，等待空闲后处理。
- Herdr 自带 popup 的标题不可自定义，所以这里使用 `type = "pane"`（临时 pane），并在脚本中调用 `herdr pane rename` 把弹出 pane 的 label 设置为 `agents` / `spaces`。副作用：这个 label 会留在触发快捷键的**源 pane** 上，选择器退出后不会自动恢复。如果在意，可手动 `herdr pane rename <pane_id> <原label>` 改回去。
- 在一个有多个 pane 的 tab 里选中某个 pane 节点回车时，只能聚焦到该 tab（herdr CLI 的 `pane focus` 目前只支持 `--direction`，不支持按 pane_id 直接聚焦），无法精确切到具体的 pane。
- 交互式输入（重命名 / 发消息 / 确认关闭）通过 `/dev/tty` 读取，以保证在 fzf 把 stdin 接管成管道时仍能正常输入；极少数无 `/dev/tty` 的环境会回退到 `stdin`，若 stdin 也不是 TTY 则会报错退出。
- `Alt + t` / `Alt + l` 依赖终端把 `Alt+字母` 作为 `ESC+字母` 透传给 fzf。绝大多数终端默认即可；若你的终端把 `Alt+字母` 绑给了菜单/系统快捷键导致不生效，可在脚本里把 `alt-t` / `alt-l` 改成 `ctrl-t` / `ctrl-l`（注意别和终端的 redraw 冲突）。
- 移动 pane 到另一个 tab 时，如果源 tab 因此变空，herdr 会自动关闭该 tab（甚至会连带关闭空 workspace）；这是 herdr 自身行为，不是插件做的。`Move tab to workspace` 也依赖这个机制：源 tab 的 pane 全部移走后源 tab 自动关闭。
- `Move tab to workspace` 在目标 workspace 新建一个 tab 来承接 pane，新建的 tab 会自带一个空 root pane，脚本会在搬完后自动 close 掉它，所以目标 tab 里只剩被搬过来的 pane。
- **zoomed tab 里的 pane 无法移动**：herdr 会**静默拒绝**从处于缩放（zoomed）状态的 tab 里移动 pane——`herdr pane move` 返回成功（exit 0）但 `move_result.changed = false`、`reason = "zoomed_tab"`，pane 留在原地。**插件会自动处理**：移动前检测源 tab 是否 zoomed，是的话先 `herdr pane zoom <pane> --off` 取消缩放，再移动，所以你通常无需关心。极少数自动 unzoom 失败的情况，通知会提示 `source tab is zoomed and could not be unzoomed — unzoom it (herdr pane zoom <pane> --off) and retry`，手动 unzoom 后重试即可。
- **当前活跃会话所在 pane 也可能无法移动**：即使没有 zoom，herdr 也会拒绝移动承载你**此刻正在用的会话**的 pane（当前 kscc / claude 会话、或当前 picker 自己的 pane）。**其它（非当前）的 agent pane 是可以正常移动的**，被拒的只是"当前活跃会话"这一个。脚本会检测 `changed` 字段并给出针对性通知：
  - 单 pane 移动失败 → 通知说明原因，例如 `this is the picker's own pane — it can't move while the picker is open`，或 `this pane is the active kscc/claude session you're in right now — exit/stop it first, or move it from a different pane`
  - `Move tab to workspace` 里部分 pane 移不动 → 通知 `Move partial: N moved, M stuck`；能移的照移，移不动的留在源 tab；如果一个都没移成功，会清理掉刚建的空目标 tab 并通知 `Move failed`
  - 想搬一个含"当前会话"的 tab：在那个 pane 里退出 kscc/claude（`/exit` 或 Ctrl+C），或从**另一个 pane** 启动 picker 去搬它；搬完后 pane 的 `pane_id` 会变（herdr 重新分配），这是正常现象。
- **被移动过的 agent 会从 herdr 的 agent 注册表里"丢失"（显示为 `[detected]`）**：把一个跑着 claude/kscc 会话的 pane 移到别的 workspace 后，herdr 会重新分配 `pane_id` 并把它从 `agents` 数组（也就是 `herdr agent list`）里**丢掉**——会话还在跑（pane 上仍带有 `agent_session`），但 herdr 不再管理它。`prefix+w` 的树里它显示成 `◦ agent  <title>  [detected]`（而不是普通 `◦ pane`，也不是带 `idle/working` 状态的受管 agent）。这种 **detected（未受管）agent**：
  - `herdr agent send / rename / focus` 对它**无效**（`agent_not_found`）。所以它的修改菜单**不提供** `Send message` / `Rename`；`Alt + t` 重命名会提示改用 `Alt + l` 设置 pane label；回车聚焦只能切到所在 tab（`herdr agent focus` 对未受管 agent 会失败，脚本已 try/except 兜底，tab 焦点照常生效）。
  - `Set pane label` / `Move to workspace` / `Move to tab` / `Close` 仍可正常使用——这些走 `herdr pane ...`，不依赖 agent 注册表。
  - 这是 herdr 自身行为（移动后不重新注册 agent），插件只能识别并如实展示，无法把它变回受管 agent。想在 herdr 里重新"认领"它，目前没有对应命令；可在该 pane 里重启会话。
- **`prefix + a` agent 选择器只列出 herdr 受管的 agent**：它基于 `herdr agent list`，因此上面那种"被移动后丢失"的 agent 在 `prefix + a` 里**不会出现**。要查看/操作这类 agent，用 `prefix + w` 的树状选择器（会以 `[detected]` 标出）。
