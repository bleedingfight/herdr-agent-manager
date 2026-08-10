# Herdr Agent Manager

**English** | [中文](README.zh-CN.md)

A local plugin for [Herdr](https://herdr.dev) that lets you quickly search / select agents and workspaces in the current session, and send messages to agents.

---

## Features

- **Agent picker** (`prefix + a`)
  - `fzf` fuzzy-search over all agents, with a header row: `NAME | WORKSPACE* | STATUS~ | TITLE`
    - `WORKSPACE*`: editable
    - `STATUS~`: read-only, reflects the agent's own runtime state
    - Search matches everything shown in the list (name / workspace / title); CJK keywords work too
  - Right-side preview shows the agent's workspace, status, cwd, title, and the last 30 lines of colorized output
  - Once an agent is selected you can: send a message / change workspace / change tab / rename / set pane label / focus / close the pane
  - Agents with no explicit name fall back to their `terminal_id` as the label, so the list never crashes on a missing field
  - Quick rename (skips the `Ctrl + e` sub-menu): `Alt + t` renames the current agent (title / name), `Alt + l` sets the current pane's label
  - `Alt + n`: create a new workspace using the selected agent's cwd as the working directory (label optional; if left blank, herdr auto-names it from the cwd's basename)

- **Workspace/Space picker** (`prefix + w`)
  - Renders the `workspace → tab → agent/pane` hierarchy as a **tree**
  - Select any level (workspace / tab / agent / pane), press `Enter` to focus it, `Ctrl + e` to open the modify menu
  - When you press Enter on an agent / pane node, it first runs `tab focus` on the containing tab, then `agent focus` on the pane, so you actually switch to it
  - Supported actions: focus, rename, set pane label, move, close, send message
  - Move capabilities: an agent / pane can move to **any tab in any workspace** (`Move to tab` now lists targets across all workspaces, options labeled `workspace / tab`); a whole tab can move to **another workspace** (`Move tab to workspace` — creates a target tab in the destination and moves all the source tab's panes over, then auto-closes the source tab)
  - Quick rename (skips the `Ctrl + e` sub-menu): `Alt + t` renames the current node (agent name, or a workspace / tab label), `Alt + l` sets the current pane's label (agent/pane nodes only)
  - `Alt + n`: create a new workspace using the current node's directory as the working directory. On an agent/pane it uses that pane's cwd; on a workspace/tab it uses the cwd of the focused pane inside it; label optional (if blank, herdr auto-names from the cwd basename). It does not auto-switch focus afterward — the new workspace appears in the refreshed tree; press Enter to focus it
  - `Ctrl + r`: manually re-render the tree in place (a fallback on top of the auto-refresh, for when you want to force a re-pull). The picker already **auto-refreshes live** (see below), so you usually don't need this
  - **Live auto-refresh**: while the picker is open, a background watcher thread checks the herdr state fingerprint (labels, ownership, and agent status of workspaces/tabs/panes) every 0.5s. If you edit / move / rename / create / close any pane or tab in **another pane**, the watcher detects the change and reloads the list with the latest tree via fzf's `--listen` socket — **no need to close and reopen, no keypress needed**. This solves the "I edited a pane but the picker still shows the old state" problem: when you come back to a still-open picker, the list is already up to date. Each reload re-runs `herdr api snapshot` (~3.6ms) + rebuilds the tree (~6ms) — accurate and smooth
  - Search **preserves the tree's nesting order**: the list is rendered with `--no-sort`, so typing a filter keyword **does not** re-rank by match score — a child node (e.g. `tab travel`) always stays right after its parent workspace (e.g. `travel-rule`) and never drifts to the top of the list detached from its parent just because it "matches better". So after moving a tab, searching its name shows it directly under the workspace it belongs to
  - The right-side preview adapts to the selected node type

---

## About the header markers

| Marker | Meaning |
|---|---|
| `*` | this column is editable |
| `~` | this column is read-only, decided by Herdr/the agent itself |

Agent list: `NAME | WORKSPACE* | STATUS~ | TITLE`

- `WORKSPACE*`: the agent's workspace can be changed (Move to another workspace)
- `STATUS~`: the agent's `idle/working/blocked/unknown` status is read-only

Workspace picker: **tree structure**, every node is editable:

- `workspace` node: rename, close
- `tab` node: rename, **move to another workspace**, close
- `agent/pane` node: send message, rename, set pane label, **move to any tab in any workspace**, close

---

## About the "selection preview"

fzf's preview pane is **read-only and not interactive** — you can't select or interact with it.

If you want to "do something to an agent after selecting it", you select a list item and combine it with an action key. Several action keys are already bound to list items.

---

## Directory layout

```text
agent-manager/
├── .gitignore              # git ignore rules
├── herdr-plugin.toml       # plugin manifest
├── README.md               # this file (English)
├── README.zh-CN.md         # Chinese docs
├── install.sh              # one-click install script
└── bin/
    ├── agent-manager.py    # agent picker entry
    ├── agent-preview.py    # right-side preview for agents
    ├── space-picker.py     # workspace tree picker entry
    ├── space-preview.py    # (legacy, superseded by tree-preview)
    └── tree-preview.py     # right-side preview for the tree picker
```

---

## Install

### One-click install (recommended)

Run inside the plugin directory:

```bash
~/.config/herdr/plugins/local/agent-manager/install.sh
```

The script automatically:

1. Checks that `herdr` is installed
2. Copies the plugin to `~/.config/herdr/plugins/local/agent-manager` (backs up an existing one to `*.backup.<timestamp>`)
3. `chmod +x bin/*.py`
4. Runs `herdr plugin link`
5. Appends the keybindings to `~/.config/herdr/config.toml` (skipped if already present)
6. Runs `herdr server reload-config`

After install, just press `ctrl+b a` and `ctrl+b w`.

### Update / reinstall

The plugin is a plain local directory — just overwrite it:

```bash
# Option 1: re-run install.sh (auto-backs up the old dir)
./install.sh

# Option 2: overwrite manually, then reload
cp -R /path/to/agent-manager ~/.config/herdr/plugins/local/agent-manager
herdr server reload-config
```

Note: upgrading herdr itself will not overwrite this plugin directory (it's outside the herdr binary). But if you re-clone the `agent-manager` repo to install, that overwrites any local edits you made to `bin/*.py` — back up your patches yourself.

### Manual install

```bash
mkdir -p ~/.config/herdr/plugins/local
cp -r /path/to/agent-manager ~/.config/herdr/plugins/local/
herdr plugin link ~/.config/herdr/plugins/local/agent-manager
```

Then add the following keybindings to `~/.config/herdr/config.toml` manually (replace `~` with your real home directory):

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

Finally reload the config:

```bash
herdr server reload-config
```

If you edited `herdr-plugin.toml`, you need to re-link:

```bash
herdr plugin unlink local.agent-manager
herdr plugin link ~/.config/herdr/plugins/local/agent-manager
```

---

## Configure keybindings

Add to `~/.config/herdr/config.toml`:

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

> The paths above use `~` for the home directory. herdr does not expand `~` — replace it with your real home directory path.

The default prefix is `ctrl+b`, so:

- `ctrl+b a`: open the agent picker
- `ctrl+b w`: open the workspace picker

Then reload:

```bash
herdr server reload-config
```

---

## Usage

### Send a message to an agent / run an action

```text
Press ctrl+b a
 → fzf lists all agents (with NAME / WORKSPACE* / STATUS~ / TITLE header)
 → search / arrow-select
 → press the matching key to act:
     Enter       type a message and send it; returns to fzf to keep selecting
     Ctrl + e    open the modify menu: move workspace / move tab / rename / set pane label
     Alt + t     rename the current agent (title / name) directly, skipping the sub-menu; returns to fzf when done
     Alt + l     set the current pane's label directly, skipping the sub-menu; returns to fzf when done
     Alt + n     create a new workspace from the current agent's cwd (label optional); returns to fzf when done
     Ctrl + r    quick-rename the agent; returns to fzf when done
     Ctrl + f    focus the agent and exit the picker
     Ctrl + x    close the agent's pane (asks for confirmation), then exit
     Esc         just exit

Header markers:
  WORKSPACE*   editable
  STATUS~      read-only (the agent's own state, not editable)

Modify menu options:
  - Move to another workspace   (when selecting from the workspace list you can also Ctrl-r to rename that workspace)
  - Move to another tab          (lists tabs across all workspaces, options formatted `workspace / tab`)
  - Rename this agent
  - Set pane label
  - Cancel
```

### workspace / tab / agent tree picker

```text
Press ctrl+b w
 → fzf lists workspace → tab → agent/pane as a tree
 → search / arrow-select any level
 → press Enter to focus that node
 → or Alt + t to rename the current node directly (agent name / workspace / tab label)
 → or Alt + l to set the current pane's label (agent/pane nodes only)
 → or Alt + n to create a new workspace from the current node's directory (label optional)
 → or Ctrl + r to refresh the tree (re-pulls the snapshot, refreshes in place, doesn't exit the picker)
 → or Ctrl + e to open the modify menu:
     workspace node: Rename workspace / Close workspace
     tab node:       Rename tab / Move tab to workspace / Close tab
     agent/pane node: Send message / Rename / Set pane label / Move to workspace / Move to tab / Close
```

---

## Customization

### Adjust how many lines of agent output the preview shows

Edit `bin/agent-preview.py`:

```python
out = herdr("agent", "read", name, "--source", "recent", "--format", "ansi", "--lines", "30")
```

Change the number after `--lines` to `50` / `100` to show more lines.

### Adjust the selected-row background color

Edit this in `bin/agent-manager.py` and `bin/space-picker.py`:

```python
fzf_colors = "bg+:#3b4261,fg+:#ffffff"
```

Change `#3b4261` to whatever highlight background you want.

---

## Version control

This plugin directory is itself a Git repo; the initial commit is already done.

```bash
cd ~/.config/herdr/plugins/local/agent-manager
git log --oneline
```

After daily dev or edits, commit the usual Git way:

```bash
git add .
git commit -m "your change description"
```

### Push to GitHub/GitLab

```bash
git remote add origin git@github.com:<your-username>/herdr-agent-manager.git
git push -u origin main
```

Others can clone and run the install script directly:

```bash
git clone git@github.com:<your-username>/herdr-agent-manager.git
# or https://github.com/<your-username>/herdr-agent-manager.git
cd herdr-agent-manager
./install.sh
```

This lets you manage the plugin through normal PRs / branches / tags.

---

## Uninstall

```bash
herdr plugin unlink local.agent-manager
rm -rf ~/.config/herdr/plugins/local/agent-manager
```

Then remove the matching `[[keys.command]]` blocks from `~/.config/herdr/config.toml` and run `herdr server reload-config`.

---

## Dependencies

- [Herdr](https://herdr.dev) >= 0.7.0
- [fzf](https://github.com/junegunn/fzf)
- Python 3

---

## Known limitations

- The plugin sends messages via `herdr agent send` + `herdr pane send-keys Return`, so the receiving agent must be able to read terminal input (works for kscc / Claude Code / Codex, etc.).
- If the target agent is busy (e.g. kscc in Thinking), messages queue up and are processed once it's idle.
- Herdr's built-in popup title isn't customizable, so this uses `type = "pane"` (a temporary pane) and calls `herdr pane rename` in the script to set the popup pane's label to `agents` / `spaces`. Side effect: this label sticks to the **source pane** that triggered the shortcut and isn't restored automatically after the picker exits. If that bothers you, manually `herdr pane rename <pane_id> <original_label>` to put it back.
- When you press Enter on a pane node inside a tab that has multiple panes, it can only focus the tab (herdr CLI's `pane focus` currently supports only `--direction`, not focusing by pane_id) — it can't switch precisely to a specific pane.
- Interactive input (rename / send message / confirm close) is read from `/dev/tty` so it still works when fzf takes over stdin as a pipe. In the rare environment with no `/dev/tty` it falls back to `stdin`; if stdin isn't a TTY either, it errors out.
- `Alt + t` / `Alt + l` rely on the terminal passing `Alt+letter` through to fzf as `ESC+letter`. Most terminals do this by default; if your terminal binds `Alt+letter` to a menu / system shortcut so it doesn't work, you can change `alt-t` / `alt-l` to `ctrl-t` / `ctrl-l` in the script (mind conflicts with the terminal's redraw).
- When moving a pane to another tab, if the source tab becomes empty herdr auto-closes that tab (and may even close an empty workspace). This is herdr's own behavior, not the plugin's. `Move tab to workspace` relies on this too: once all panes leave the source tab it auto-closes.
- `Move tab to workspace` creates a new tab in the target workspace to receive the panes; the new tab comes with an empty root pane, which the script auto-closes after the move, so only the moved panes remain in the target tab.
- **Panes inside a zoomed tab can't be moved**: herdr **silently refuses** to move a pane out of a zoomed tab — `herdr pane move` returns success (exit 0) but `move_result.changed = false` and `reason = "zoomed_tab"`, leaving the pane in place. **The plugin handles this automatically**: before moving it checks whether the source tab is zoomed, and if so runs `herdr pane zoom <pane> --off` to unzoom first, then moves — so you usually don't need to care. In the rare case auto-unzoom fails, the notification says `source tab is zoomed and could not be unzoomed — unzoom it (herdr pane zoom <pane> --off) and retry`; manually unzoom and retry.
- **The pane hosting your currently-active session may also be unmovable**: even without zoom, herdr refuses to move the pane that carries the session you're **using right now** (the current kscc / claude session, or the picker's own pane). **Other (non-current) agent panes move fine** — only the "currently active session" one is refused. The script inspects the `changed` field and gives a targeted notification:
  - A single-pane move failed → the notification explains why, e.g. `this is the picker's own pane — it can't move while the picker is open`, or `this pane is the active kscc/claude session you're in right now — exit/stop it first, or move it from a different pane`
  - Some panes stuck during `Move tab to workspace` → notification `Move partial: N moved, M stuck`; the ones that can move do, the stuck ones stay in the source tab; if none moved, it cleans up the just-created empty target tab and notifies `Move failed`
  - To move a tab that contains the "current session": exit kscc/claude in that pane (`/exit` or Ctrl+C), or launch the picker from **another pane** to move it; after the move the pane's `pane_id` changes (herdr reassigns it) — that's normal.
- **A moved agent is "lost" from herdr's agent registry (shown as `[detected]`)**: after you move a pane running a claude/kscc session to another workspace, herdr reassigns the `pane_id` and **drops** it from the `agents` array (i.e. `herdr agent list`) — the session is still running (the pane still carries `agent_session`), but herdr no longer manages it. In the `prefix+w` tree it shows as `◦ agent  <title>  [detected]` (rather than a plain `◦ pane`, and not a managed agent with an `idle/working` status). Such a **detected (unmanaged) agent**:
  - `herdr agent send / rename / focus` are **ineffective** on it (`agent_not_found`). So its modify menu **does not offer** `Send message` / `Rename`; `Alt + t` rename prompts you to use `Alt + l` to set the pane label instead; pressing Enter to focus only switches to the containing tab (`herdr agent focus` fails on an unmanaged agent; the script try/exceptes it, and the tab focus still takes effect).
  - `Set pane label` / `Move to workspace` / `Move to tab` / `Close` still work — these go through `herdr pane ...` and don't depend on the agent registry.
  - This is herdr's own behavior (it doesn't re-register the agent after a move); the plugin can only recognize and display it faithfully, and cannot turn it back into a managed agent. There's currently no command to "re-claim" it in herdr; you can restart the session in that pane.
- **The `prefix + a` agent picker lists only herdr-managed agents**: it's based on `herdr agent list`, so the "moved and lost" agents above **do not appear** in `prefix + a`. To view / act on such agents, use the `prefix + w` tree picker (they're marked `[detected]`).
