#!/usr/bin/env python3
import json
import os
import shlex
import subprocess
import sys

HERDR = os.environ.get("HERDR_BIN_PATH", "herdr")
MODIFY_KEY = "ctrl-e"


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


def herdr(*args, capture=True):
    r = subprocess.run([HERDR, *args], capture_output=True, text=True, check=True)
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


def fzf_select(options, header=None, prompt_text="> ", colors="bg+:#3b4261,fg+:#ffffff", expect_keys=None):
    args = ["fzf", "--no-sort", "--prompt", prompt_text, "--color", colors]
    if header:
        args.extend(["--header", header])
    if expect_keys:
        args.extend(["--expect", ",".join(expect_keys)])

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
                  f"alt-t:title  alt-l:label  alt-n:new-agent  ctrl-r:rename  ctrl-f:focus  ctrl-x:close  esc:quit")
    header_visible = (
        f"{headers[0]:<{widths[0]}}  "
        f"{headers[1]:<{widths[1]}}  "
        f"{headers[2]:<{widths[2]}}  "
        f"{headers[3]:<{widths[3]}}"
    )
    lines = [f"|{header_visible}"]
    for a in agents:
        lines.append(format_agent_line(agent_display_fields(a, pane_labels.get(a.get("pane_id"))), widths))

    result = subprocess.run(
        ["fzf", "--delimiter=|",
               "--with-nth=2",
               "--header-lines=1",
               "--prompt=agent> ",
               "--header", fzf_header,
               "--preview", preview,
               "--preview-window=right:50%",
               f"--expect={MODIFY_KEY},ctrl-r,ctrl-f,ctrl-x,alt-t,alt-l,alt-n",
               "--color", fzf_colors],
        input="\n".join(lines),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0 or not result.stdout.strip():
        sys.exit(0)

    parts = result.stdout.strip("\n").split("\n")
    if len(parts) >= 2:
        action = parts[0] or None
        selection = parts[-1]
    else:
        action = None
        selection = parts[0]

    name = selection.split("|")[0]
    return name, action


def send_to_agent(name, pane_id, message):
    herdr("agent", "send", name, message)
    herdr("pane", "send-keys", pane_id, "Return")
    notify("Sent", f"to {name}")


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
    # alt-n (now in the modify menu): create a workspace whose cwd is the
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


def create_agent(agent):
    # alt-n: start a new agent via `herdr agent start` in a chosen workspace.
    # Defaults are pre-filled and editable: argv defaults to `opencode`, cwd
    # defaults to the selected agent's cwd, name defaults to basename(argv).
    # Supports --env KEY=VALUE for agents that need env vars (e.g. opencode).
    default_cwd = agent.get("cwd") or os.getcwd()

    # 1. command to run (argv) — default opencode, editable
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

    # 2. agent name — default basename(argv[0])
    default_name = os.path.basename(argv[0])
    name = prompt_prefill("Agent name: ", default_name)
    if not name:
        name = default_name

    # 3. cwd — default current agent's cwd, editable (delete/edit chars)
    cwd = prompt_prefill("Cwd: ", default_cwd)
    if not cwd:
        cwd = default_cwd

    # 4. env vars — KEY=VAL space-separated, blank = none
    env_str = prompt("Env vars (KEY=VAL ..., blank=none): ")

    # 5. target workspace
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
        if not agents:
            print("No agents found")
            break

        name, action = pick_agent(agents)
        agent = next((a for a in agents if a["name"] == name), None)
        if agent is None:
            print(f"agent '{name}' not found")
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

        if action == "alt-t":
            rename_agent(name)
            continue

        if action == "alt-l":
            set_pane_label(agent)
            continue

        if action == "alt-n":
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
