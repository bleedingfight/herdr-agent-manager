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
        print("usage: agent-preview.py <agent-name>")
        sys.exit(1)

    name = sys.argv[1]
    agents = json.loads(herdr("agent", "list"))["result"]["agents"]
    agent = next((a for a in agents if a["name"] == name), None)
    if agent is None:
        print("Agent not found")
        sys.exit(0)

    ws_label = agent.get("workspace_id", "-")
    # try to resolve workspace label from snapshot
    try:
        snap = json.loads(herdr("api", "snapshot"))
        ws = next(
            (w for w in snap["result"]["snapshot"]["workspaces"]
             if w["workspace_id"] == agent.get("workspace_id")),
            None,
        )
        if ws:
            ws_label = f"{ws.get('label', '-')} ({agent.get('workspace_id', '-')})"
    except Exception:
        pass

    print(f"Name:      {agent['name']}")
    print(f"Workspace: {ws_label}")
    print(f"Pane:      {agent.get('pane_id', '-')}")
    print(f"Status:    {agent.get('agent_status', 'unknown')}")
    print(f"CWD:       {agent.get('cwd', '-')}")
    print(f"Title:     {agent.get('terminal_title_stripped', '-')}")
    print()
    print("--- Recent output ---")

    try:
        # use --format ansi to preserve terminal colors in the preview
        out = herdr("agent", "read", name, "--source", "recent", "--format", "ansi", "--lines", "30")
        data = json.loads(out)
        text = data["result"]["read"]["text"]
        print(text if text else "(no recent output)")
    except Exception as e:
        print(f"(unable to read output: {e})")


if __name__ == "__main__":
    main()
