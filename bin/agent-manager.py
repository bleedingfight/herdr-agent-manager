#!/usr/bin/env python3
import json
import os
import re
import shlex
import subprocess
import sys

HERDR = os.environ.get("HERDR_BIN_PATH", "herdr")
# We use Ctrl-O for "edit/modify". Avoid Ctrl-E: herdr's herdr-navigator plugin
# binds Ctrl-E globally to termscope.open-links, so the keystroke is captured
# before it ever reaches fzf's --expect and the modify menu never opens.
# Avoid Alt-* on macOS: Terminal.app/iTerm2 default Option to compose chars
# (Option+m -> µ), so the key never reaches fzf unless "Option as Meta" is on.
# Ctrl-O is a plain control key — works on every macOS terminal, and is free in
# both herdr's default config and fzf's default bindings.
MODIFY_KEY = "ctrl-o"


def normalize_agent(a):
    # Newer herdr versions omit `name` for agents that haven't been explicitly
    # renamed; fall back to terminal_id (a valid target for `herdr agent ...`)
    # so the rest of the script can keep treating `name` as the identifier.
    if not a.get("name"):
        a["name"] = a.get("terminal_id") or a.get("pane_id") or "agent"
    return a


def set_title(title):
    pane_id = os.environ.get("HERDR_PANE_ID")
    if pane_id:
        try:
            subprocess.run([HERDR, "pane", "rename", pane_id, title],
                           capture_output=True, text=True, check=False)
        except Exception:
            pass


# Debug 模式：把插件实际执行的每条 herdr 命令记录到日志。
# 开关（二选一，标志文件优先）：
#   touch ~/.config/herdr/plugins/local/agent-manager/debug      # 开
#   rm    ~/.config/herdr/plugins/local/agent-manager/debug      # 关
#   或环境变量 HERDR_AGENT_MANAGER_DEBUG=1（插件跑在 herdr 起的 pane 里，
#   shell 里 export 的变量通常传不进来，所以默认用标志文件）
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEBUG_FLAG = os.path.join(PLUGIN_DIR, "debug")
DEBUG_LOG = os.path.join(PLUGIN_DIR, "debug.log")


def debug_log(msg):
    if not (os.path.exists(DEBUG_FLAG)
            or os.environ.get("HERDR_AGENT_MANAGER_DEBUG") == "1"):
        return
    try:
        from datetime import datetime
        with open(DEBUG_LOG, "a") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except Exception:
        pass


def herdr(*args, capture=True):
    debug_log("$ herdr " + " ".join(shlex.quote(a) for a in args))
    try:
        r = subprocess.run([HERDR, *args], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        debug_log("  FAILED: " + (e.stderr or e.stdout or str(e)).strip()[:2000])
        raise
    return r.stdout


def move_pane(pane_id, *, tab_id=None, new_tab_workspace_id=None, split="right"):
    # Move a pane, returning (changed, detail). herdr returns exit 0 with
    # `move_result.changed = false` when it refuses a move. Common reasons:
    #   - source tab is zoomed (reason == "zoomed_tab") — we auto-unzoom first
    #   - the pane hosts the currently-active session (the kscc/claude/picker
    #     you're driving now); idle agent panes DO move.
    _unzoom_source_tab(pane_id)
    try:
        if tab_id:
            r = herdr("pane", "move", pane_id, "--tab", tab_id, "--split", split, "--no-focus")
        else:
            r = herdr("pane", "move", pane_id, "--new-tab", "--workspace", new_tab_workspace_id, "--no-focus")
        mr = json.loads(r)["result"]["move_result"]
        if mr.get("changed", False):
            return True, None
        reason = mr.get("reason") or ""
        if reason == "zoomed_tab":
            return False, "source tab is zoomed and could not be unzoomed — unzoom it (herdr pane zoom <pane> --off) and retry"
        return False, _refusal_reason(pane_id)
    except subprocess.CalledProcessError as e:
        return False, (e.stderr or e.stdout or str(e)).strip()
    except Exception as e:
        return False, str(e)


def _unzoom_source_tab(pane_id):
    try:
        snap = json.loads(herdr("api", "snapshot"))["result"]["snapshot"]
        pane = next((p for p in snap["panes"] if p["pane_id"] == pane_id), None)
        if not pane:
            return None
        layout = next((l for l in snap.get("layouts", []) if l.get("tab_id") == pane.get("tab_id")), None)
        if layout and layout.get("zoomed"):
            herdr("pane", "zoom", pane_id, "--off")
        return pane.get("tab_id")
    except Exception:
        return None


def _refusal_reason(pane_id):
    try:
        cur = os.environ.get("HERDR_PANE_ID")
        snap = json.loads(herdr("api", "snapshot"))["result"]["snapshot"]
        tgt = next((p for p in snap["panes"] if p["pane_id"] == pane_id), None)
        if tgt is None:
            return "herdr refused to move this pane"
        if cur and pane_id == cur:
            return "this is the picker's own pane — it can't move while the picker is open"
        if tgt.get("agent_session"):
            return ("this pane is the active kscc/claude session you're in right now "
                    "— exit/stop it first, or move it from a different pane")
        return "herdr refused to move this pane (it may be running a foreground process)"
    except Exception:
        return "herdr refused to move this pane"


def notify(title, body=""):
    try:
        args = [HERDR, "notification", "show", title]
        if body:
            args.extend(["--body", body])
        subprocess.run(args, capture_output=True, text=True, check=False)
    except Exception:
        pass


def prompt(question):
    # Read from /dev/tty so interactive input works even when stdin is a pipe
    # (fzf is launched with capture_output=True, leaving stdin non-TTY).
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write(question)
            tty.flush()
            return tty.readline().strip()
    except OSError:
        if not sys.stdin.isatty():
            sys.exit("stdin is not a TTY and /dev/tty unavailable")
        return input(question).strip()


def fzf_select(options, header=None, prompt_text="> ", colors="bg+:#3b4261,fg+:#ffffff", expect_keys=None,
               preview=None, preview_window=None):
    args = ["fzf", "--no-sort", "--prompt", prompt_text, "--color", colors]
    if header:
        args.extend(["--header", header])
    if expect_keys:
        args.extend(["--expect", ",".join(expect_keys)])
    if preview:
        args.extend(["--preview", preview])
    if preview_window:
        args.extend(["--preview-window", preview_window])

    result = subprocess.run(
        args,
        input="\n".join(options),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0 or not result.stdout.strip():
        return None, None

    parts = result.stdout.strip("\n").split("\n")
    if expect_keys and len(parts) >= 2:
        action = parts[0] or None
        selection = parts[-1]
    else:
        action = None
        selection = parts[0]

    return selection, action


def list_agents():
    data = json.loads(herdr("agent", "list"))
    return [normalize_agent(a) for a in data["result"]["agents"]]


def list_workspaces():
    data = json.loads(herdr("workspace", "list"))
    return data["result"]["workspaces"]


def list_tabs(workspace_id):
    data = json.loads(herdr("tab", "list", "--workspace", workspace_id))
    return data["result"]["tabs"]


def pick_target_tab_anywhere():
    # Cross-workspace tab picker (for moving an agent's pane to any tab).
    snap = json.loads(herdr("api", "snapshot"))["result"]["snapshot"]
    workspaces = {w["workspace_id"]: w.get("label", "-") for w in snap["workspaces"]}
    lines = []
    for t in snap["tabs"]:
        ws_label = workspaces.get(t.get("workspace_id"), "-")
        lines.append(f"{t['tab_id']}|{ws_label} / {t.get('label','-')}  ({t.get('pane_count',0)} panes)")
    if not lines:
        return None
    selected, _ = fzf_select(lines, header="select target tab (any workspace)", prompt_text="tab> ")
    if selected is None:
        return None
    return selected.split("|")[0]


def agent_display_fields(a, pane_label):
    # Prefer the user-set pane label if available.
    title = pane_label or a.get("terminal_title_stripped") or a.get("name")
    return (
        a["name"],
        a.get("workspace_id", "-"),
        a.get("agent_status", "unknown"),
        title,
    )


def format_agent_line(a, widths):
    name, ws, status, title = a
    visible = (
        f"{name:<{widths[0]}}  "
        f"{ws:<{widths[1]}}  "
        f"{status:<{widths[2]}}  "
        f"{title:<{widths[3]}}"
    )
    return f"{name}|{visible}"


def format_header_line(headers, widths):
    # Same alignment as data rows so the pinned header (--header-lines=1)
    # lines up exactly with the agent rows below it.
    visible = (
        f"{headers[0]:<{widths[0]}}  "
        f"{headers[1]:<{widths[1]}}  "
        f"{headers[2]:<{widths[2]}}  "
        f"{headers[3]:<{widths[3]}}"
    )
    # Key column is empty for the header so fzf's {1} matching column stays
    # blank and the NAME column begins at the same offset as data rows.
    return f"|{visible}"


def pick_agent(agents):
    set_title("agents")

    # Fetch pane labels so renamed titles are reflected in the list.
    try:
        snapshot = json.loads(herdr("api", "snapshot"))["result"]["snapshot"]
        pane_labels = {p["pane_id"]: p.get("label") for p in snapshot["panes"]}
    except Exception:
        pane_labels = {}

    headers = ["NAME", "WORKSPACE*", "STATUS~", "TITLE"]
    data_fields = [agent_display_fields(a, pane_labels.get(a.get("pane_id"))) for a in agents]
    widths = [
        max(len(headers[i]), max(len(f[i]) for f in data_fields) if data_fields else 0) + 2
        for i in range(4)
    ]

    plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    preview = os.path.join(plugin_root, "bin", "agent-preview.py") + " {1}"

    fzf_colors = "bg+:#3b4261,fg+:#ffffff"
    fzf_header = (f"agents — enter:send  {MODIFY_KEY}:modify  "
                  f"ctrl-t:title  ctrl-l:label  ctrl-n:new-agent  ctrl-r:rename  ctrl-f:focus  ctrl-x:close  esc:quit")
    blocked_n = sum(1 for a in agents if a.get("agent_status") == "blocked")
    if blocked_n:
        fzf_header = (f"⏸ {blocked_n} 个 agent 等待输入 — "
                      f"选中后回车直接应答(允许/拒绝)   " + fzf_header)
    header_visible = format_header_line(headers, widths)
    lines = [header_visible]
    for a in agents:
        lines.append(format_agent_line(agent_display_fields(a, pane_labels.get(a.get("pane_id"))), widths))

    result = subprocess.run(
        ["fzf", "--no-sort",
               "--layout=reverse",  # header (lines[0]) pinned at top, agents below
               "--delimiter=|",
               "--with-nth=2",
               "--header-lines=1",
               "--prompt=agent> ",
               "--header", fzf_header,
               "--preview", preview,
               "--preview-window=right:50%",
               f"--expect={MODIFY_KEY},ctrl-r,ctrl-f,ctrl-x,ctrl-t,ctrl-l,ctrl-n",
               "--color", fzf_colors],
        input="\n".join(lines),
        capture_output=True,
        text=True,
    )

    # fzf exit codes: 0 = normal select, 1 = no match, 2 = error, 130 = esc/ctrl-c.
    # BUT with --expect, fzf exits 1 when an expect-key is pressed and outputs
    # the key on stdout. So rc==1 with non-empty stdout is NOT an error here —
    # it's the ctrl-n / ctrl-o / etc. action we asked for. Only treat rc!=0 as
    # "cancelled" when there's no expect-key output.
    out = result.stdout
    if (result.returncode != 0 and not out.strip()) or not out.strip():
        sys.exit(0)

    # With --expect, fzf prints: line1 = pressed key (empty if none),
    # line2 = selected item (empty if none — e.g. an empty agent list has no
    # selectable row, so pressing ctrl-n yields just "ctrl-n"). We must NOT
    # strip("\n") first: that collapses a trailing empty selection line into
    # nothing, leaving a single "ctrl-n" line that the old len>=2 logic
    # misparsed as "no action" (action=None) — making ctrl-n on an empty list
    # look like it does nothing. Instead, since we know the expect keys, treat
    # line[0] as the action iff it is one of them; the selection is whatever
    # follows (possibly empty).
    EXPECT_KEYS = {MODIFY_KEY, "ctrl-r", "ctrl-f", "ctrl-x",
                  "ctrl-t", "ctrl-l", "ctrl-n"}
    lines = result.stdout.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    # With --expect, fzf ALWAYS emits a first line for the pressed key — empty
    # when none was pressed (plain Enter). So:
    #   pressed expect key -> line0=key, line1=selection (may be empty)
    #   plain Enter        -> line0="" (empty), line1=selection
    first = lines[0] if lines else ""
    if first in EXPECT_KEYS:
        action = first
        selection = lines[-1] if len(lines) >= 2 else ""
    else:
        # No expect key pressed (plain Enter): line0 is the empty key line,
        # the actual selection is line1. first here is "" — NOT the selection.
        action = None
        selection = lines[1] if len(lines) >= 2 else (first if first else "")

    name = selection.split("|")[0] if selection else ""
    return name, action


def respond_blocked(agent):
    # 选中 blocked 状态的 agent 后的应答界面：预览窗实时显示它卡住的对话框，
    # 动作经 herdr agent send-keys 远程下发（人不用切到那个 pane）。
    name = agent["name"]
    proj = os.path.basename(agent.get("cwd") or "?")
    preview = (f"{shlex.quote(HERDR)} agent read {shlex.quote(name)} "
               f"--source visible --lines 40 2>/dev/null | tail -40")
    opts = [
        "✅ 允许  (Enter 确认当前高亮项)",
        "❌ 拒绝  (Esc 取消/否定)",
        "🔢 选择选项  (输入选项号后回车)",
        "⏭  跳过  (保持等待，稍后处理)",
    ]
    sel, _ = fzf_select(
        opts,
        header=f"⏸ {name} @ {proj} 等待输入 — 右侧预览=它卡住的界面",
        prompt_text="action> ",
        preview=preview,
        preview_window="right:60%",
    )
    if sel is None:
        return
    if sel.startswith("✅"):
        herdr("agent", "send-keys", name, "enter", capture=False)
        notify(f"已允许 {name}", f"已发送 Enter，{proj} 的任务继续")
    elif sel.startswith("❌"):
        herdr("agent", "send-keys", name, "esc", capture=False)
        notify(f"已拒绝 {name}", "已发送 Esc，该步操作被取消")
    elif sel.startswith("🔢"):
        num = prompt("选项号 (如 1/2/3): ").strip()
        if num:
            herdr("agent", "send-keys", name, num, capture=False)
            herdr("agent", "send-keys", name, "enter", capture=False)
            notify(f"已选择选项 {num}", f"{name} @ {proj}")


def _send_via_prompt(name, message):
    # herdr >= 0.8: `agent prompt <target> <text>` is the real submission path.
    # It routes text through herdr's agent-input layer (respects the agent's
    # state — rejects with agent_blocked at approval/question dialogs). Do NOT
    # pass --timeout alone: it requires --wait, and we don't want to block the
    # picker on the agent's turn to settle.
    herdr("agent", "prompt", name, message)


def _send_via_legacy(name, pane_id, message):
    # herdr < 0.8 (or fallback): the old `agent send <target> <text>` plus a
    # literal Return keystroke. `agent send` was removed in 0.8, so this path
    # only works on older installs.
    herdr("agent", "send", name, message)
    herdr("pane", "send-keys", pane_id, "Return")


def send_to_agent(name, pane_id, message):
    # Version-dispatched, with a runtime fallback: try the method that matches
    # the running herdr version first; if it fails (e.g. the version boundary
    # was misjudged, or the command was renamed in a patch release), fall back
    # to the other method so the message is still delivered on some path.
    use_new = herdr_version() >= (0, 8, 0)
    try:
        if use_new:
            _send_via_prompt(name, message)
        else:
            _send_via_legacy(name, pane_id, message)
        notify("Sent", f"to {name}")
        return
    except subprocess.CalledProcessError as e:
        # Primary path failed — try the other one.
        pass
    try:
        if use_new:
            _send_via_legacy(name, pane_id, message)
        else:
            _send_via_prompt(name, message)
        notify("Sent", f"to {name} (fallback)")
    except subprocess.CalledProcessError as e:
        notify("Send failed", f"to {name}: {(e.stderr or e.stdout or str(e)).strip()}")
    except Exception as e:
        notify("Send failed", f"to {name}: {e}")


def rename_agent(name):
    new_name = prompt(f"Rename agent '{name}' to: ")
    if new_name:
        herdr("agent", "rename", name, new_name)
        notify("Agent renamed", f"{name} → {new_name}")


def set_pane_label(agent):
    cur_label = json.loads(herdr("pane", "get", agent["pane_id"]))["result"]["pane"].get("label") or ""
    cur = cur_label or agent.get("terminal_title_stripped", "")
    new = prompt(f"Set label for pane {agent['pane_id']} (current: {cur}): ")
    if new:
        herdr("pane", "rename", agent["pane_id"], new)
        notify("Pane label set", f"{agent['pane_id']} → {new}")


def new_workspace(agent):
    # ctrl-n (now in the modify menu): create a workspace whose cwd is the
    # selected agent's directory.
    cwd = agent.get("cwd") or os.getcwd()
    label = prompt(f"New workspace label (optional). cwd: {cwd}: ")
    args = ["workspace", "create", "--cwd", cwd, "--no-focus"]
    if label:
        args.extend(["--label", label])
    try:
        r = herdr(*args)
        wid = json.loads(r)["result"]["workspace"]["workspace_id"]
        notify("Workspace created", f"{wid} @ {cwd}" + (f" ({label})" if label else ""))
    except Exception as e:
        notify("Workspace create failed", str(e))


def prompt_prefill(question, prefill=""):
    # An EDITABLE pre-filled prompt. Implementation: a tiny fzf whose candidate
    # list contains ONLY the prefill (so it's pre-highlighted), with free typing
    # enabled. You can just Enter to accept the prefill, type to filter, or
    # Ctrl-u / Backspace to clear and type your own (e.g. prefill /a/b/c →
    # backspace twice → /a/b). fzf reports both the query and the selection via
    # --print-query, so free input that matches nothing still returns what you
    # typed. This avoids the fragile readline/startup-hook + /dev/tty combo,
    # which silently no-ops (returns empty) in some pane environments.
    items = [prefill] if prefill else []
    try:
        result = subprocess.run(
            ["fzf", "--no-sort", "--print-query", "--prompt", f"{question} ",
             "--header", "(Enter=accept  type to edit  Ctrl-u clears)",
             "--color", "bg+:#3b4261,fg+:#ffffff"],
            input="\n".join(items),
            capture_output=True, text=True,
        )
    except Exception:
        # last-resort fallback: non-editable prompt via /dev/tty
        if prefill:
            ans = prompt(f"{question} [{prefill}]: ")
            return ans if ans else prefill
        return prompt(f"{question}: ")
    if result.returncode != 0 and not result.stdout.strip():
        # Esc / cancelled
        return ""
    parts = result.stdout.rstrip("\n").split("\n")
    # With --print-query, line 1 is the query string, line 2 (if any) the selection.
    query = parts[0] if parts else ""
    selection = parts[1] if len(parts) > 1 else ""
    # Prefer the selection (matches a candidate) when the user didn't type a
    # custom query; otherwise honor the typed query (covers free input + Ctrl-u).
    if query and query != prefill:
        return query
    return selection or query or prefill


def pick_workspace_for_new():
    # Choose which workspace to start a new agent in.
    workspaces = list_workspaces()
    lines = [f"{w['workspace_id']}|{w.get('label','-')}  ({w['workspace_id']})"
             for w in workspaces]
    selected, _ = fzf_select(lines, header="start agent in which workspace?",
                             prompt_text="workspace> ")
    if selected is None:
        return None
    return selected.split("|")[0]


def herdr_version():
    # Parse the running herdr version into a tuple, e.g. "herdr 0.8.2" -> (0, 8, 2).
    # Used to branch create_agent() between the 0.7.x and 0.8.x `agent start`
    # CLI signatures. Falls back to (0, 0, 0) so unknown/old versions take the
    # legacy path (the one the plugin was originally written against).
    try:
        out = subprocess.run([HERDR, "--version"], capture_output=True, text=True, check=False)
        text = (out.stdout or out.stderr or "").strip()
        # tolerate "herdr 0.8.2" or bare "0.8.2"
        tok = text.split()[-1] if text else ""
        parts = []
        for p in tok.split("."):
            num = "".join(ch for ch in p if ch.isdigit())
            parts.append(int(num) if num else 0)
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])
    except Exception:
        return (0, 0, 0)


# Supported `--kind` values for `herdr agent start` (herdr >= 0.8). The kind
# maps to a canonical executable; `-- <argv>` is no longer how you specify the
# agent binary — `--kind` is required and the rest of argv goes after `--` as
# extra args to that binary.
AGENT_KINDS = [
    "pi", "claude", "codex", "gemini", "cursor", "devin", "agy", "cline",
    "omp", "mastracode", "opencode", "copilot", "kimi", "kiro", "droid",
    "amp", "grok", "hermes", "kilo", "qodercli", "qwen", "maki",
]


def supported_kinds():
    # 动态获取 herdr 当前支持的 --kind 列表：socket API schema 里 kind 只是
    # {"type": "string"}（无枚举），但 CLI help 的 possible values 行有完整
    # 列表。解析失败时回退到上面的硬编码列表，保证 picker 永远可用。
    try:
        out = subprocess.run(
            [HERDR, "agent", "start", "--help"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        m = re.search(r"possible values:\s*([a-z0-9_,\s]+)", out)
        if m:
            kinds = [k.strip() for k in m.group(1).split(",") if k.strip()]
            if kinds:
                return kinds
    except Exception:
        pass
    return AGENT_KINDS

# 本机没有 claude 二进制，claude kind 通过 shim 实际启动 kscc（见
# /usr/local/node-v24.14.0-darwin-arm64/bin/claude）。展示用标签让 picker
# 里能认出它是 kscc；传给 herdr agent start 的仍是合法 kind "claude"。
KIND_LABELS = {
    "claude": "claude (runs kscc)",
}

# 默认选中 claude：本机主力 agent 是 kscc（claude shim）。
DEFAULT_KIND = "claude"


def pick_kind(default_kind=DEFAULT_KIND):
    # fzf over the kind list fetched from the CLI (fallback: hardcoded).
    # fzf 的空查询回车选中列表第一行，所以把默认 kind 排到最前，
    # "一路回车"才会创建默认 agent 而不是 pi。
    kinds = supported_kinds()
    if default_kind in kinds:
        kinds.remove(default_kind)
        kinds.insert(0, default_kind)
    labels = [KIND_LABELS.get(k, k) for k in kinds]
    label_to_kind = {KIND_LABELS.get(k, k): k for k in kinds}
    selected, _ = fzf_select(
        labels,
        header="agent kind (--kind)",
        prompt_text="kind> ",
    )
    if selected is None:
        return None
    kind = label_to_kind.get(selected.strip())
    if kind not in kinds:
        notify("Create agent failed", f"unsupported kind: {selected.strip()}")
        return None
    return kind


def split_clean_pane(workspace_id, cwd=None):
    # `herdr agent start` (0.8+) requires --pane pointing at an *available*
    # interactive shell. The picker can't guarantee any existing pane is idle,
    # so we split a fresh one in the target workspace and start the agent there.
    # `pane split` splits next to an EXISTING pane (it has no --workspace flag),
    # so we grab any pane in the target workspace as the anchor.
    # Returns the new pane_id, or None on failure.
    try:
        snap = json.loads(herdr("api", "snapshot"))["result"]["snapshot"]
    except Exception as e:
        notify("Create agent failed", f"snapshot failed: {e}")
        return None
    anchor = next((p["pane_id"] for p in snap.get("panes", [])
                   if p.get("workspace_id") == workspace_id), None)
    if not anchor:
        notify("Create agent failed", f"no pane in workspace {workspace_id} to split from")
        return None
    args = ["pane", "split", anchor, "--direction", "down"]
    if cwd:
        args.extend(["--cwd", cwd])
    try:
        r = herdr(*args)
        pane = json.loads(r)["result"]["pane"]
        return pane.get("pane_id")
    except subprocess.CalledProcessError as e:
        notify("Create agent failed", f"pane split failed: {(e.stderr or e.stdout or str(e)).strip()}")
        return None
    except Exception as e:
        notify("Create agent failed", f"pane split failed: {e}")
        return None


def _create_agent_legacy(agent):
    # herdr < 0.8 signature: `agent start <NAME> --cwd <cwd> --workspace <ws>
    # --no-focus [--env K=V]... -- <argv>`. argv is the agent binary directly
    # (no --kind). This is the original plugin behavior; kept intact so the
    # picker still works on 0.7.x installs.
    default_cwd = (agent.get("cwd") if agent else None) or os.getcwd()

    argv_str = prompt_prefill("Command to run (argv): ", "opencode")
    if not argv_str:
        return
    try:
        argv = shlex.split(argv_str)
    except ValueError as e:
        notify("Create agent failed", f"bad command: {e}")
        return
    if not argv:
        notify("Create agent failed", "empty command")
        return

    default_name = os.path.basename(argv[0])
    name = prompt_prefill("Agent name: ", default_name)
    if not name:
        name = default_name

    cwd = prompt_prefill("Cwd: ", default_cwd)
    if not cwd:
        cwd = default_cwd

    env_str = prompt("Env vars (KEY=VAL ..., blank=none): ")

    ws_id = pick_workspace_for_new()
    if not ws_id:
        notify("Create agent cancelled", "no workspace chosen")
        return

    cmd = ["agent", "start", name, "--cwd", cwd, "--workspace", ws_id, "--no-focus"]
    if env_str:
        try:
            for tok in shlex.split(env_str):
                if "=" in tok:
                    cmd.extend(["--env", tok])
        except ValueError as e:
            notify("Create agent failed", f"bad env: {e}")
            return
    cmd.extend(["--", *argv])
    try:
        r = herdr(*cmd)
        res = json.loads(r)["result"]
        new_pane = res.get("agent", {}).get("pane_id", "?")
        notify("Agent created", f"{name} @ {ws_id} (pane {new_pane})")
    except subprocess.CalledProcessError as e:
        notify("Create agent failed", (e.stderr or e.stdout or str(e)).strip())
    except Exception as e:
        notify("Create agent failed", str(e))


def create_agent(agent):
    # ctrl-n: start a new agent via `herdr agent start`. The CLI signature
    # changed in 0.8: 0.7.x used `--cwd/--workspace/--no-focus -- <argv>`;
    # 0.8.x requires `--kind <KIND> --pane <ID> [-- ARGS...]`. Dispatch on the
    # running herdr version so the picker works on both.
    if herdr_version() < (0, 8, 0):
        return _create_agent_legacy(agent)

    # --- 0.8.x path ---
    # We split a fresh pane in the chosen workspace (so --pane is always an
    # available shell), then start the agent there.
    default_cwd = (agent.get("cwd") if agent else None) or os.getcwd()

    # 1. agent kind — default opencode
    kind = pick_kind()
    if not kind:
        notify("Create agent cancelled", "no kind chosen")
        return

    # 2. agent name — default = kind
    name = prompt_prefill("Agent name: ", kind)
    if not name:
        name = kind

    # 3. cwd for the new pane — default current agent's cwd, editable
    cwd = prompt_prefill("Cwd: ", default_cwd)
    if not cwd:
        cwd = default_cwd

    # 4. extra argv after `--` (optional, blank = none)
    argv_str = prompt("Extra args after -- (blank=none): ")
    argv = []
    if argv_str:
        try:
            argv = shlex.split(argv_str)
        except ValueError as e:
            notify("Create agent failed", f"bad extra args: {e}")
            return

    # 5. env vars — KEY=VAL space-separated, blank = none
    env_str = prompt("Env vars (KEY=VAL ..., blank=none): ")

    # 6. target workspace — split a fresh pane there
    ws_id = pick_workspace_for_new()
    if not ws_id:
        notify("Create agent cancelled", "no workspace chosen")
        return

    pane_id = split_clean_pane(ws_id, cwd)
    if not pane_id:
        return

    # Give the freshly split shell a moment to reach its prompt before herdr
    # tries to detect an interactive agent inside it.
    import time
    time.sleep(0.6)

    cmd = ["agent", "start", name, "--kind", kind, "--pane", pane_id]
    if env_str:
        try:
            for tok in shlex.split(env_str):
                if "=" in tok:
                    cmd.extend(["--env", tok])
        except ValueError as e:
            notify("Create agent failed", f"bad env: {e}")
            return
    if argv:
        cmd.extend(["--", *argv])
    try:
        r = herdr(*cmd)
        res = json.loads(r)["result"]
        new_pane = res.get("agent", {}).get("pane_id", pane_id)
        notify("Agent created", f"{name} ({kind}) @ {ws_id} (pane {new_pane})")
    except subprocess.CalledProcessError as e:
        notify("Create agent failed", (e.stderr or e.stdout or str(e)).strip())
    except Exception as e:
        notify("Create agent failed", str(e))


def main():
    name = os.environ.get("AGENT_MANAGER_PICK")
    message = os.environ.get("AGENT_MANAGER_MESSAGE")

    if name:
        agent = next((a for a in list_agents() if a["name"] == name), None)
        if agent is None:
            sys.exit(f"agent '{name}' not found")
        if message:
            send_to_agent(name, agent["pane_id"], message)
        return

    while True:
        agents = list_agents()
        empty = not agents

        name, action = pick_agent(agents)
        agent = next((a for a in agents if a["name"] == name), None) if not empty else None
        # On an empty list only "create a new agent" (ctrl-n) is meaningful;
        # send/rename/focus/close all need a selected agent, so steer the user
        # to ctrl-n instead of crashing on the None agent.
        if empty and action != "ctrl-n":
            notify("No agents", "press ctrl-n (new-agent) to create one, esc to quit")
            continue
        if not empty and agent is None:
            print(f"agent '{name}' not found")
            continue

        # 选中的 agent 正被对话框卡住（等权限/确认/选项）→ 直接进应答界面：
        # 预览=它卡住的屏幕，允许/拒绝经 send-keys 远程下发。
        if agent is not None and agent.get("agent_status") == "blocked":
            respond_blocked(agent)
            continue

        if action == MODIFY_KEY:
            opts = [
                "Send message",
                "Rename agent",
                "Set pane label",
                "Move to workspace",
                "Move to tab",
                "New workspace",
                "Focus agent",
                "Close pane",
                "Cancel",
            ]
            headers = f"modify '{agent['name']}'"
            sel, _ = fzf_select(opts, header=headers, prompt_text="action> ")
            if sel == "Send message":
                message = prompt(f"Message for {name}: ")
                if message:
                    send_to_agent(name, agent["pane_id"], message)
            elif sel == "Rename agent":
                rename_agent(name)
            elif sel == "Set pane label":
                set_pane_label(agent)
            elif sel == "Move to workspace":
                workspaces = list_workspaces()
                ws_lines = [
                    f"{w['workspace_id']}|{w.get('label','-')}"
                    for w in workspaces
                ]
                selected, _ = fzf_select(ws_lines, header="select target workspace", prompt_text="workspace> ")
                if selected:
                    ws_id = selected.split("|")[0]
                    changed, err = move_pane(agent["pane_id"], new_tab_workspace_id=ws_id)
                    if changed:
                        notify("Agent moved", f"{name} → workspace {ws_id}")
                    else:
                        notify("Move failed", err or "herdr refused (active agent pane?)")
            elif sel == "Move to tab":
                tab_id = pick_target_tab_anywhere()
                if tab_id:
                    changed, err = move_pane(agent["pane_id"], tab_id=tab_id)
                    if changed:
                        notify("Agent moved", f"{name} → tab {tab_id}")
                    else:
                        notify("Move failed", err or "herdr refused (active agent pane?)")
            elif sel == "New workspace":
                new_workspace(agent)
            elif sel == "Focus agent":
                herdr("agent", "focus", name, capture=False)
                break
            elif sel == "Close pane":
                confirm = prompt(f"Close pane {agent['pane_id']} for agent '{name}'? [y/N] ")
                if confirm.lower() == "y":
                    herdr("pane", "close", agent["pane_id"], capture=False)
                break
            continue

        if action == "ctrl-r":
            rename_agent(name)
            continue

        if action == "ctrl-t":
            rename_agent(name)
            continue

        if action == "ctrl-l":
            set_pane_label(agent)
            continue

        if action == "ctrl-n":
            create_agent(agent)
            continue

        if action == "ctrl-f":
            herdr("agent", "focus", name, capture=False)
            break

        if action == "ctrl-x":
            confirm = prompt(f"Close pane {agent['pane_id']} for agent '{name}'? [y/N] ")
            if confirm.lower() == "y":
                herdr("pane", "close", agent["pane_id"], capture=False)
            break

        message = prompt(f"Message for {name}: ")
        if message:
            send_to_agent(name, agent["pane_id"], message)


if __name__ == "__main__":
    main()
