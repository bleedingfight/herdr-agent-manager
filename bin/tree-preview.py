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
    if len(sys.argv) < 2 or ":" not in sys.argv[1]:
        print("usage: tree-preview.py <type:id>")
        sys.exit(1)

    typ, id_ = sys.argv[1].split(":", 1)
    snap = json.loads(herdr("api", "snapshot"))["result"]["snapshot"]

    if typ == "workspace":
        ws = next((w for w in snap["workspaces"] if w["workspace_id"] == id_), None)
        if ws is None:
            print("Workspace not found")
            return
        active = ws.get("active_tab_id", "-")
        print(f"Workspace: {ws.get('label', '-')} ({id_})")
        print(f"Active tab: {active}")
        print(f"Tabs: {ws.get('tab_count', 0)}  Panes: {ws.get('pane_count', 0)}")
        print()
        tabs = [t for t in snap["tabs"] if t.get("workspace_id") == id_]
        print("Tabs:")
        for t in tabs:
            marker = "*" if t["tab_id"] == active else " "
            print(f"  [{marker}] {t.get('label','-')}  ({t.get('pane_count',0)} panes)")
        print()
        agents = [a for a in snap["agents"] if a.get("workspace_id") == id_]
        print("Agents:")
        for a in agents:
            print(f"  • {a['name']} [{a.get('agent_status','unknown')}] {a.get('terminal_title_stripped','')}")

    elif typ == "tab":
        tab = next((t for t in snap["tabs"] if t["tab_id"] == id_), None)
        if tab is None:
            print("Tab not found")
            return
        ws = next((w for w in snap["workspaces"] if w["workspace_id"] == tab.get("workspace_id")), None)
        print(f"Tab: {tab.get('label', '-')} ({id_})")
        print(f"Workspace: {ws.get('label','-') if ws else '-'}")
        print(f"Panes: {tab.get('pane_count', 0)}")
        print()
        panes = [p for p in snap["panes"] if p.get("tab_id") == id_]
        print("Panes / Agents:")
        for p in panes:
            agent = next((a for a in snap["agents"] if a.get("pane_id") == p["pane_id"]), None)
            if agent:
                print(f"  • {agent['name']} [{agent.get('agent_status','unknown')}] {agent.get('terminal_title_stripped','')}")
            else:
                title = p.get("terminal_title_stripped", "") or p.get("label", "-")
                print(f"  • pane {title}")

    elif typ in ("agent", "pane"):
        pane = next((p for p in snap["panes"] if p["pane_id"] == id_), None)
        agent = next((a for a in snap["agents"] if a.get("pane_id") == id_), None)
        if pane is None and agent is None:
            print("Pane/agent not found")
            return

        if agent:
            plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            subprocess.run([os.path.join(plugin_root, "bin", "agent-preview.py"), agent["name"]])
        else:
            print(f"Pane: {id_}")
            print(f"Title: {pane.get('terminal_title_stripped','-')}")
            print(f"Tab: {pane.get('tab_id','-')}")
            print(f"Workspace: {pane.get('workspace_id','-')}")

    else:
        print(f"Unknown type: {typ}")


if __name__ == "__main__":
    main()
