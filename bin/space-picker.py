#!/usr/bin/env python3
import json
import os
import subprocess
import sys

HERDR = os.environ.get("HERDR_BIN_PATH", "herdr")

# We use Ctrl-E for "edit/modify" instead of Ctrl-M because Ctrl-M
# is indistinguishable from Enter in most terminals.
MODIFY_KEY = "ctrl-e"


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


def notify(title, body=""):
    try:
        args = [HERDR, "notification", "show", title]
        if body:
            args.extend(["--body", body])
        subprocess.run(args, capture_output=True, text=True, check=False)
    except Exception:
        pass


def prompt(question):
    if not sys.stdin.isatty():
        sys.exit("stdin is not a TTY")
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


def get_snapshot():
    return json.loads(herdr("api", "snapshot"))["result"]["snapshot"]


def build_tree(snapshot):
    lines = []
    workspaces = sorted(snapshot["workspaces"], key=lambda w: w.get("number", 0))
    for ws in workspaces:
        ws_id = ws["workspace_id"]
        lines.append(f"workspace:{ws_id}|● workspace  {ws.get('label', '-')}")

        tabs = sorted(
            [t for t in snapshot["tabs"] if t.get("workspace_id") == ws_id],
            key=lambda t: t.get("number", 0),
        )
        for tab in tabs:
            tab_id = tab["tab_id"]
            lines.append(f"tab:{tab_id}|  ▸ tab  {tab.get('label', '-')}")

            panes = [p for p in snapshot["panes"] if p.get("tab_id") == tab_id]
            for pane in panes:
                pane_id = pane["pane_id"]
                agent = next((a for a in snapshot["agents"] if a.get("pane_id") == pane_id), None)
                # Prefer the user-set pane label if present, otherwise fall back
                # to the terminal title or agent name.
                if agent:
                    name = agent["name"]
                    status = agent.get("agent_status", "unknown")
                    title = pane.get("label") or agent.get("terminal_title_stripped", "")
                    lines.append(f"agent:{pane_id}|    ◦ agent  {name}  [{status}]  {title}")
                else:
                    title = pane.get("label") or pane.get("terminal_title_stripped", "") or "pane"
                    lines.append(f"pane:{pane_id}|    ◦ pane  {title}")
    return lines


def lookup(snapshot, typ, id_):
    if typ == "workspace":
        return next((w for w in snapshot["workspaces"] if w["workspace_id"] == id_), None)
    if typ == "tab":
        return next((t for t in snapshot["tabs"] if t["tab_id"] == id_), None)
    if typ in ("agent", "pane"):
        pane = next((p for p in snapshot["panes"] if p["pane_id"] == id_), None)
        agent = next((a for a in snapshot["agents"] if a.get("pane_id") == id_), None)
        return pane, agent
    return None


def pick_target_workspace(snapshot):
    lines = [f"{w['workspace_id']}|{w.get('label','-')}  ({w['workspace_id']})" for w in snapshot["workspaces"]]
    selected, _ = fzf_select(lines, header="select target workspace", prompt_text="workspace> ")
    if selected is None:
        return None
    return selected.split("|")[0]


def pick_target_tab(snapshot, workspace_id):
    tabs = [t for t in snapshot["tabs"] if t.get("workspace_id") == workspace_id]
    if not tabs:
        return None
    lines = [f"{t['tab_id']}|{t.get('label','-')}  ({t.get('pane_count',0)} panes)" for t in tabs]
    selected, _ = fzf_select(lines, header="select target tab", prompt_text="tab> ")
    if selected is None:
        return None
    return selected.split("|")[0]


def modify(snapshot, typ, id_):
    if typ == "workspace":
        ws = lookup(snapshot, typ, id_)
        if not ws:
            return
        opts = ["Rename workspace", "Close workspace", "Cancel"]
        sel, _ = fzf_select(opts, header=f"modify workspace '{ws.get('label', id_)}'")
        if sel == "Rename workspace":
            new = prompt(f"Rename workspace '{ws.get('label', id_)}' to: ")
            if new:
                herdr("workspace", "rename", id_, new)
                notify("Workspace renamed", f"{ws.get('label', id_)} → {new}")
        elif sel == "Close workspace":
            confirm = prompt(f"Close workspace '{ws.get('label', id_)}'? [y/N] ")
            if confirm.lower() == "y":
                herdr("workspace", "close", id_, capture=False)

    elif typ == "tab":
        tab = lookup(snapshot, typ, id_)
        if not tab:
            return
        opts = ["Rename tab", "Close tab", "Cancel"]
        sel, _ = fzf_select(opts, header=f"modify tab '{tab.get('label', id_)}'")
        if sel == "Rename tab":
            new = prompt(f"Rename tab '{tab.get('label', id_)}' to: ")
            if new:
                herdr("tab", "rename", id_, new)
                notify("Tab renamed", f"{tab.get('label', id_)} → {new}")
        elif sel == "Close tab":
            confirm = prompt(f"Close tab '{tab.get('label', id_)}'? [y/N] ")
            if confirm.lower() == "y":
                herdr("tab", "close", id_, capture=False)

    elif typ in ("agent", "pane"):
        pane, agent = lookup(snapshot, typ, id_)
        if not pane:
            return
        name = agent["name"] if agent else pane.get("label", "?")
        header = f"modify {'agent' if agent else 'pane'} '{name}'"
        opts = ["Rename", "Set title", "Move to workspace", "Move to tab", "Close", "Cancel"]
        if agent:
            opts.insert(0, "Send message")
        sel, _ = fzf_select(opts, header=header)
        if sel is None or sel == "Cancel":
            return
        if sel == "Send message" and agent:
            msg = prompt(f"Message for {agent['name']}: ")
            if msg:
                herdr("agent", "send", agent["name"], msg)
                herdr("pane", "send-keys", id_, "Return")
                notify("Sent", f"to {agent['name']}")
        elif sel == "Rename":
            if agent:
                new = prompt(f"Rename agent '{agent['name']}' to: ")
                if new:
                    herdr("agent", "rename", agent["name"], new)
                    notify("Agent renamed", f"{agent['name']} → {new}")
            else:
                notify("Cannot rename", "Only recognized agents can be renamed")
        elif sel == "Set title":
            cur = pane.get("label") or pane.get("terminal_title_stripped", "")
            new = prompt(f"Set title for pane {id_} (current: {cur}): ")
            if new:
                herdr("pane", "rename", id_, new)
                notify("Pane title set", f"{id_} → {new}")
        elif sel == "Move to workspace":
            ws_id = pick_target_workspace(snapshot)
            if ws_id:
                herdr("pane", "move", id_, "--new-tab", "--workspace", ws_id)
                notify("Pane moved", f"{id_} to workspace {ws_id}")
        elif sel == "Move to tab":
            ws_id = pane.get("workspace_id")
            tab_id = pick_target_tab(snapshot, ws_id) if ws_id else None
            if tab_id:
                herdr("pane", "move", id_, "--tab", tab_id, "--split", "right")
                notify("Pane moved", f"{id_} to tab {tab_id}")
        elif sel == "Close":
            confirm = prompt(f"Close pane {id_} ({name})? [y/N] ")
            if confirm.lower() == "y":
                herdr("pane", "close", id_, capture=False)


def focus_item(snapshot, typ, id_):
    if typ == "workspace":
        herdr("workspace", "focus", id_, capture=False)
    elif typ == "tab":
        herdr("tab", "focus", id_, capture=False)
    elif typ == "agent":
        _, agent = lookup(snapshot, typ, id_)
        if agent:
            herdr("agent", "focus", agent["name"], capture=False)


def main():
    spec = os.environ.get("AGENT_MANAGER_TREE_ITEM")
    if spec:
        typ, id_ = spec.split(":", 1)
        snapshot = get_snapshot()
        focus_item(snapshot, typ, id_)
        return

    while True:
        snapshot = get_snapshot()
        tree_lines = build_tree(snapshot)
        if not tree_lines:
            print("No workspaces found")
            break

        plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        preview = os.path.join(plugin_root, "bin", "tree-preview.py") + " {1}"

        header_line = "|TYPE        NAME"
        lines = [header_line] + tree_lines

        set_title("spaces")
        fzf_header = f"spaces tree — enter:focus  {MODIFY_KEY}:modify  esc:quit"
        result = subprocess.run(
            ["fzf", "--delimiter=|",
                   "--with-nth=2",
                   "--nth=2",
                   "--header-lines=1",
                   "--header", fzf_header,
                   "--prompt=space> ",
                   "--preview", preview,
                   "--preview-window=right:50%",
                   f"--expect={MODIFY_KEY}",
                   "--color", "bg+:#3b4261,fg+:#ffffff"],
            input="\n".join(lines),
            capture_output=True,
            text=True,
        )

        if result.returncode != 0 or not result.stdout.strip():
            break

        parts = result.stdout.strip("\n").split("\n")
        if len(parts) >= 2:
            action = parts[0] or None
            selection = parts[-1]
        else:
            action = None
            selection = parts[0]

        spec = selection.split("|")[0]
        if ":" not in spec:
            break
        typ, id_ = spec.split(":", 1)

        if action == MODIFY_KEY:
            modify(snapshot, typ, id_)
            continue

        focus_item(snapshot, typ, id_)
        break


if __name__ == "__main__":
    main()
