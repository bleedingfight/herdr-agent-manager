# Herdr Agent Manager

一个用于 [Herdr](https://herdr.dev) 的本地插件，让你快速搜索/选择当前 session 中的 agent 和 workspace，并给 agent 发送消息。

---

## 功能

- **Agent 选择器** (`prefix + a`)
  - `fzf` 模糊搜索所有 agent，列表带表头：`NAME | WORKSPACE* | STATUS~ | TITLE`
    - `WORKSPACE*`：可修改
    - `STATUS~`：只读，来自 agent 本身的运行状态
  - 右侧预览 agent 的 workspace、状态、cwd、标题 以及最近 30 行彩色输出
  - 选中后可以执行多种操作：发消息 / 修改 workspace / 修改 tab / 重命名 / 设置 title / 聚焦 / 关闭 pane

- **Workspace/Space 选择器** (`prefix + w`)
  - 以**树状层次结构**展示 `workspace → tab → agent/pane`
  - 选中任意层级（workspace / tab / agent / pane）后按 `Ctrl + e` 都可以修改
  - 支持操作：聚焦、重命名、移动、关闭、发送消息
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
- `tab` 节点：可重命名、关闭
- `agent/pane` 节点：可发送消息、重命名、设置 title、移动 workspace/tab、关闭

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
├── README.md               # 本文件
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

### 一键安装（推荐）

```bash
# 如果你已经把这个仓库/目录放到本机
/home/ubuntu/.config/herdr/plugins/local/agent-manager/install.sh
```

脚本会自动：

1. 检查 `herdr` 是否已安装
2. 把插件复制到 `~/.config/herdr/plugins/local/agent-manager`
3. 执行 `herdr plugin link`
4. 在 `~/.config/herdr/config.toml` 里添加快捷键
5. 执行 `herdr server reload-config`

装完后直接按 `ctrl+b a` 和 `ctrl+b w` 就能用。

### 手动安装

```bash
mkdir -p ~/.config/herdr/plugins/local
cp -r /path/to/agent-manager ~/.config/herdr/plugins/local/
herdr plugin link ~/.config/herdr/plugins/local/agent-manager
```

然后手动把下面的快捷键加到 `~/.config/herdr/config.toml`：

```toml
[[keys.command]]
key = "prefix+a"
type = "pane"
command = "/home/ubuntu/.config/herdr/plugins/local/agent-manager/bin/agent-manager.py"

[[keys.command]]
key = "prefix+w"
type = "pane"
command = "/home/ubuntu/.config/herdr/plugins/local/agent-manager/bin/space-picker.py"
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

在 `~/.config/herdr/config.toml` 中添加：

```toml
[[keys.command]]
key = "prefix+a"
type = "pane"
command = "/home/ubuntu/.config/herdr/plugins/local/agent-manager/bin/agent-manager.py"

[[keys.command]]
key = "prefix+w"
type = "pane"
command = "/home/ubuntu/.config/herdr/plugins/local/agent-manager/bin/space-picker.py"
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
     Ctrl + e    打开修改菜单：移动 workspace / 移动 tab / 重命名 / 设置 title
     Ctrl + r    快速重命名 agent，完成后回到 fzf
     Ctrl + f    聚焦 agent 并退出选择器
     Ctrl + x    关闭 agent 所在 pane（需确认），然后退出
     Esc         直接退出

表头标记：
  WORKSPACE*   可修改
  STATUS~      只读（agent 自身状态，不能改）

修改菜单内选项：
  - Move to another workspace   （在 workspace 列表里选中时还可以 Ctrl-r 重命名该 workspace）
  - Move to another tab
  - Rename this agent
  - Set pane title
  - Cancel
```

### workspace / tab / agent 树状选择器

```text
按 ctrl+b w
 → fzf 以树状列出 workspace → tab → agent/pane
 → 搜索 / 方向键选中任意层级
 → 按 Enter 聚焦该节点
 → 或按 Ctrl + e 打开修改菜单：
     workspace 节点：Rename workspace / Close workspace
     tab 节点：Rename tab / Close tab
     agent/pane 节点：Send message / Rename / Set title / Move to workspace / Move to tab / Close
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
- Herdr 自带 popup 的标题不可自定义，所以这里使用 `type = "pane"`（临时 pane），并在脚本中调用 `herdr pane rename` 将 pane 标题设置为 `agents` / `spaces`。
