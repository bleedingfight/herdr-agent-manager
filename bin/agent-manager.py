#!/usr/bin/env python3
import json
import os
import subprocess
import sys

HERDR = os.environ.get("HERDR_BIN_PATH", "herdr")
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


def list_agents():
    data = json.loads(herdr("agent", "list"))
    return data["result"]["agents"]


def list_workspaces():
    data = json.loads(herdr("workspace", "list"))
    return data["result"]["workspaces"]


def list_tabs(workspace_id):
    data = json.loads(herdr("tab", "list", "--workspace", workspace_id))
    return data["result"]["tabs"]


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
    fzf_header = f"agents — enter:send  {MODIFY_KEY}:modify  ctrl-r:rename  ctrl-f:focus  ctrl-x:close  esc:quit"
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
               "--nth=2",
               "--header-lines=1",
               "--prompt=agent> ",
               "--header", fzf_header,
               "--preview", preview,
               "--preview-window=right:50%",
               f"--expect={MODIFY_KEY},ctrl-r,ctrl-f,ctrl-x",
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
                "Set pane title",
                "Move to workspace",
                "Move to tab",
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
                new_name = prompt(f"Rename agent '{name}' to: ")
                if new_name:
                    herdr("agent", "rename", name, new_name)
                    notify("Agent renamed", f"{name} → {new_name}")
            elif sel == "Set pane title":
                cur_label = json.loads(herdr("pane", "get", agent["pane_id"]))["result"]["pane"].get("label") or ""
                cur_title = agent.get("terminal_title_stripped", "")
                cur = cur_label or cur_title
                new = prompt(f"Set title for pane {agent['pane_id']} (current: {cur}): ")
                if new:
                    herdr("pane", "rename", agent["pane_id"], new)
                    notify("Pane title set", f"{agent['pane_id']} → {new}")
            elif sel == "Move to workspace":
                workspaces = list_workspaces()
                ws_lines = [
                    f"{w['workspace_id']}|{w.get('label','-')}"
                    for w in workspaces
                ]
                selected, _ = fzf_select(ws_lines, header="select target workspace", prompt_text="workspace> ")
                if selected:
                    ws_id = selected.split("|")[0]
                    herdr("pane", "move", agent["pane_id"], "--new-tab", "--workspace", ws_id)
                    notify("Agent moved", f"{name} → workspace {ws_id}")
            elif sel == "Move to tab":
                ws_id = agent.get("workspace_id")
                if ws_id:
                    tabs = list_tabs(ws_id)
                    tab_lines = [
                        f"{t['tab_id']}|{t.get('label','-')}"
                        for t in tabs
                    ]
                    selected, _ = fzf_select(tab_lines, header="select target tab", prompt_text="tab> ")
                    if selected:
                        tab_id = selected.split("|")[0]
                        herdr("pane", "move", agent["pane_id"], "--tab", tab_id, "--split", "right")
                        notify("Agent moved", f"{name} → tab {tab_id}")
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
            new_name = prompt(f"Rename agent '{name}' to: ")
            if new_name:
                herdr("agent", "rename", name, new_name)
                notify("Agent renamed", f"{name} → {new_name}")
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
