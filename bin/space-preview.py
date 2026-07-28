#!/usr/bin/env python3
import json
import os
import subprocess
import sys

HERDR = os.environ.get("HERDR_BIN_PATH", "herdr")


def herdr(*args):
    r = subprocess.run([HERDR, *args], capture_output=True, text=True, check=True)
    return r.stdout


def main():
    if len(sys.argv) < 2:
        print("usage: space-preview.py <workspace-id>")
        sys.exit(1)

    workspace_id = sys.argv[1]

    # workspace metadata
    try:
        ws = json.loads(herdr("workspace", "get", workspace_id))["result"]["workspace"]
    except Exception as e:
        print(f"(workspace metadata unavailable: {e})")
        sys.exit(0)

    # full snapshot for tabs/agents
    try:
        snap = json.loads(herdr("api", "snapshot"))["result"]["snapshot"]
    except Exception as e:
        print(f"(snapshot unavailable: {e})")
        snap = {"tabs": [], "agents": []}

    tabs = [t for t in snap["tabs"] if t.get("workspace_id") == workspace_id]
    agents = [a for a in snap["agents"] if a.get("workspace_id") == workspace_id]

    active_tab_label = "-"
    active_tab_id = ws.get("active_tab_id")
    for t in tabs:
        if t["tab_id"] == active_tab_id:
            active_tab_label = f"{t.get('label', '-')} ({active_tab_id})"
            break

    print(f"Workspace: {ws.get('label', '-')} ({workspace_id})")
    print(f"Active tab: {active_tab_label}")
    print(f"Tabs: {ws.get('tab_count', 0)}  |  Panes: {ws.get('pane_count', 0)}")
    print()

    print("Tabs in this workspace:")
    for t in tabs:
        marker = "*" if t["tab_id"] == active_tab_id else " "
        print(f"  [{marker}] {t.get('number', '-'):<2} {t.get('label', '-'):<20} ({t.get('pane_count', 0)} panes)")

    print()
    if agents:
        print("Agents in this workspace:")
        for a in agents:
            status = a.get("agent_status", "unknown")
            title = a.get("terminal_title_stripped") or a.get("name")
            cwd = a.get("cwd", "-")
            print(f"  • {a['name']}")
            print(f"    status : {status}")
            print(f"    pane   : {a.get('pane_id', '-')}")
            print(f"    cwd    : {cwd}")
            print(f"    title  : {title}")
    else:
        print("No agents in this workspace.")


if __name__ == "__main__":
    main()
