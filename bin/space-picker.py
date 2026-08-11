#!/usr/bin/env python3
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

HERDR = os.environ.get("HERDR_BIN_PATH", "herdr")

# We use Ctrl-O for "edit/modify". Avoid Ctrl-E: herdr's herdr-navigator plugin
# binds Ctrl-E globally to termscope.open-links, so the keystroke is captured
# before it ever reaches fzf's --expect and the modify menu never opens.
# Avoid Alt-* on macOS: Terminal.app/iTerm2 default Option to compose chars
# (Option+m -> µ), so the key never reaches fzf unless "Option as Meta" is on.
# Ctrl-O is a plain control key — works on every macOS terminal, and is free in
# both herdr's default config and fzf's default bindings.
MODIFY_KEY = "ctrl-o"


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
    # `move_result.changed = false` when it refuses to move a pane. The most
    # common reasons we've seen in the wild:
    #   - the source tab is zoomed (move_result.reason == "zoomed_tab")
    #   - the pane hosts the currently-active session (the kscc/claude/picker
    #     you're driving right now); idle agent panes DO move.
    # We auto-unzoom the source tab first (zoomed tabs reject every move),
    # then surface any remaining no-op so callers don't mistake it for success.
    src_tab_id = _unzoom_source_tab(pane_id)
    try:
        if tab_id:
            r = herdr("pane", "move", pane_id, "--tab", tab_id, "--split", split, "--no-focus")
        else:
            r = herdr("pane", "move", pane_id, "--new-tab", "--workspace", new_tab_workspace_id, "--no-focus")
        mr = json.loads(r)["result"]["move_result"]
        changed = mr.get("changed", False)
        if changed:
            return True, None
        reason = mr.get("reason") or ""
        if reason == "zoomed_tab":
            detail = "source tab is zoomed and could not be unzoomed — unzoom it (herdr pane zoom <pane> --off) and retry"
        elif reason == "same_tab":
            detail = "that's the tab this pane is already in — pick a different tab"
        else:
            detail = _refusal_reason(pane_id)
        return False, detail
    except subprocess.CalledProcessError as e:
        return False, (e.stderr or e.stdout or str(e)).strip()
    except Exception as e:
        return False, str(e)


def _unzoom_source_tab(pane_id):
    # If the pane's tab is zoomed, unzoom it so the move can proceed. Returns
    # the source tab_id (or None). herdr silently no-ops moves out of a zoomed
    # tab with move_result.changed=false / reason="zoomed_tab".
    try:
        snap = json.loads(herdr("api", "snapshot"))["result"]["snapshot"]
        pane = next((p for p in snap["panes"] if p["pane_id"] == pane_id), None)
        if not pane:
            return None
        src_tab_id = pane.get("tab_id")
        layout = next((l for l in snap.get("layouts", []) if l.get("tab_id") == src_tab_id), None)
        if layout and layout.get("zoomed"):
            herdr("pane", "zoom", pane_id, "--off")
        return src_tab_id
    except Exception:
        return None


def _refusal_reason(pane_id):
    # Best-effort human reason for a non-zoom move refusal.
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


def normalize_agent(a):
    # Newer herdr versions omit `name` for agents that haven't been explicitly
    # renamed; fall back to terminal_id (a valid target for `herdr agent ...`)
    # so the rest of the script can keep treating `name` as the identifier.
    if not a.get("name"):
        a["name"] = a.get("terminal_id") or a.get("pane_id") or "agent"
    return a


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


def get_snapshot():
    snap = json.loads(herdr("api", "snapshot"))["result"]["snapshot"]
    snap["agents"] = [normalize_agent(a) for a in snap.get("agents", [])]
    return snap


def agent_for_pane(snapshot, pane_id):
    # Resolve a pane to its agent, if any. Two independent signals:
    #   1. snapshot["agents"] — herdr's managed agent registry (what
    #      `herdr agent list` returns).
    #   2. pane.agent_session — a live claude/kscc session attached to the pane.
    # A pane can have (2) but not (1): when a pane hosting an agent is moved to
    # another workspace, herdr reassigns its pane_id and drops it from the
    # registry, so the session is still running but `herdr agent list` no longer
    # knows it. Such panes ARE live agents, so we synthesize a minimal record
    # (marked `synthesized=True`) and the tree labels them as agents. herdr's
    # `agent send/rename` CLI does NOT target these (agent_not_found), so
    # callers must handle synthesized agents defensively.
    agent = next((a for a in snapshot["agents"] if a.get("pane_id") == pane_id), None)
    if agent:
        return agent
    pane = next((p for p in snapshot["panes"] if p["pane_id"] == pane_id), None)
    if pane and pane.get("agent_session"):
        return {
            "name": pane.get("terminal_title_stripped") or pane.get("label") or pane_id,
            "pane_id": pane_id,
            "agent_status": "detected",
            "workspace_id": pane.get("workspace_id"),
            "cwd": pane.get("cwd"),
            "terminal_title_stripped": pane.get("terminal_title_stripped", ""),
            "synthesized": True,
        }
    return None


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
                agent = agent_for_pane(snapshot, pane_id)
                if agent:
                    name = agent["name"]
                    status = agent.get("agent_status", "unknown")
                    # Show the pane label as the title; drop it when it just
                    # duplicates the name (synthesized agents whose name IS the
                    # terminal title and whose label is empty).
                    title = pane.get("label") or agent.get("terminal_title_stripped", "")
                    suffix = f"  {title}" if title and title != name else ""
                    lines.append(f"agent:{pane_id}|    ◦ agent  {name}  [{status}]{suffix}")
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
        agent = agent_for_pane(snapshot, id_)
        return pane, agent
    return None


def pick_target_workspace(snapshot, exclude_workspace_id=None):
    # Excludes the pane/tab's current workspace (exclude_workspace_id) so you
    # can't pick a no-op target — moving a pane to its own workspace (new tab)
    # is a silent herdr no-op, which reads as "move didn't take effect".
    lines = [
        f"{w['workspace_id']}|{w.get('label','-')}  ({w['workspace_id']})"
        for w in snapshot["workspaces"]
        if w["workspace_id"] != exclude_workspace_id
    ]
    if not lines:
        return None
    selected, _ = fzf_select(lines, header="select target workspace", prompt_text="workspace> ")
    if selected is None:
        return None
    return selected.split("|")[0]


def pick_target_tab_anywhere(snapshot, exclude_tab_id=None):
    # Cross-workspace tab picker. Excludes the tab the pane already lives in
    # (exclude_tab_id), so you can't pick a no-op target — herdr returns
    # move_result.changed=false / reason="same_tab" for a move to the pane's
    # own tab, which reads as "move didn't take effect". Returns tab_id or None.
    lines = []
    for w in sorted(snapshot["workspaces"], key=lambda w: w.get("number", 0)):
        ws_label = w.get("label", "-")
        tabs = sorted(
            [t for t in snapshot["tabs"]
             if t.get("workspace_id") == w["workspace_id"]
             and t["tab_id"] != exclude_tab_id],
            key=lambda t: t.get("number", 0),
        )
        for t in tabs:
            lines.append(
                f"{t['tab_id']}|{ws_label} / {t.get('label','-')}  "
                f"({t.get('pane_count',0)} panes)"
            )
    if not lines:
        return None
    selected, _ = fzf_select(
        lines, header="select target tab (any workspace)", prompt_text="tab> "
    )
    if selected is None:
        return None
    return selected.split("|")[0]


def move_tab_to_workspace(snapshot, src_tab_id):
    # Move an entire tab to another workspace. herdr has no `tab move`, so we
    # build it: create a new tab in the target workspace, then move every pane
    # from the source tab into it (the last successful move auto-closes the
    # source tab once it's empty). The freshly created tab starts with one
    # empty root pane — we drop it at the end so the destination contains only
    # the moved panes.
    #
    # Caveat: herdr silently refuses (move_result.changed=false, exit 0) to move
    # a pane that hosts an active interactive agent (kscc/claude). We detect
    # that per-pane and report it instead of claiming success.
    src_tab = next((t for t in snapshot["tabs"] if t["tab_id"] == src_tab_id), None)
    if not src_tab:
        notify("Move failed", f"tab {src_tab_id} not found")
        return
    src_ws_id = src_tab.get("workspace_id")
    src_panes = [p for p in snapshot["panes"] if p.get("tab_id") == src_tab_id]
    if not src_panes:
        notify("Move failed", "tab has no panes")
        return

    ws_id = pick_target_workspace(snapshot, exclude_workspace_id=src_ws_id)
    if not ws_id:
        notify("Move cancelled", "cancelled")
        return

    label = src_tab.get("label", "-")
    try:
        r = herdr("tab", "create", "--workspace", ws_id, "--label", label, "--no-focus")
        new_tab_id = json.loads(r)["result"]["tab"]["tab_id"]
        empty_root = json.loads(r)["result"]["root_pane"]["pane_id"]
    except Exception as e:
        notify("Move failed", f"create tab: {e}")
        return

    moved, skipped = [], []
    for p in src_panes:
        changed, err = move_pane(p["pane_id"], tab_id=new_tab_id,
                                split="down" if moved else "right")
        if changed:
            moved.append(p["pane_id"])
        else:
            skipped.append((p["pane_id"], err or "herdr refused (likely an active agent pane)"))

    # Drop the empty root pane the new tab started with — but only if we
    # actually moved something into the tab; otherwise the tab is just the
    # empty shell and we leave it (user can close the workspace if unwanted).
    if moved:
        try:
            herdr("pane", "close", empty_root)
        except Exception:
            pass

    if skipped and not moved:
        # nothing moved — clean up the empty target tab we just created
        try:
            herdr("tab", "close", new_tab_id, capture=False)
        except Exception:
            pass
        sample = skipped[0]
        notify("Move failed",
               f"no panes moved. {sample[0]}: {sample[1]}")
    elif skipped:
        notify("Move partial",
               f"{len(moved)} moved, {len(skipped)} stuck. "
               f"Stuck: {', '.join(s[0] for s in skipped)} (see notification for why)")
    else:
        notify("Tab moved", f"{src_tab_id} → workspace {ws_id} ({len(moved)} panes)")


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
        opts = ["Rename tab", "Move tab to workspace", "Close tab", "Cancel"]
        sel, _ = fzf_select(opts, header=f"modify tab '{tab.get('label', id_)}'")
        if sel == "Rename tab":
            new = prompt(f"Rename tab '{tab.get('label', id_)}' to: ")
            if new:
                herdr("tab", "rename", id_, new)
                notify("Tab renamed", f"{tab.get('label', id_)} → {new}")
        elif sel == "Move tab to workspace":
            move_tab_to_workspace(snapshot, id_)
        elif sel == "Close tab":
            confirm = prompt(f"Close tab '{tab.get('label', id_)}'? [y/N] ")
            if confirm.lower() == "y":
                herdr("tab", "close", id_, capture=False)

    elif typ in ("agent", "pane"):
        pane, agent = lookup(snapshot, typ, id_)
        if not pane:
            return
        synth = bool(agent and agent.get("synthesized"))
        name = agent["name"] if agent else pane.get("label", "?")
        kind = "agent (unmanaged)" if synth else ("agent" if agent else "pane")
        header = f"modify {kind} '{name}'"
        opts = ["Set pane label", "Move to workspace", "Move to tab", "Close", "Cancel"]
        if agent and not synth:
            opts = ["Send message", "Rename"] + opts
        sel, _ = fzf_select(opts, header=header)
        if sel is None or sel == "Cancel":
            return
        if sel == "Send message" and agent and not synth:
            msg = prompt(f"Message for {agent['name']}: ")
            if msg:
                herdr("agent", "send", agent["name"], msg)
                herdr("pane", "send-keys", id_, "Return")
                notify("Sent", f"to {agent['name']}")
        elif sel == "Rename":
            if agent and not synth:
                new = prompt(f"Rename agent '{agent['name']}' to: ")
                if new:
                    herdr("agent", "rename", agent["name"], new)
                    notify("Agent renamed", f"{agent['name']} → {new}")
            else:
                notify("Cannot rename",
                       "This is a live agent session herdr doesn't manage (likely moved). "
                       "Use Alt+l to set the pane label instead.")
        elif sel == "Set pane label":
            cur = pane.get("label") or pane.get("terminal_title_stripped", "")
            new = prompt(f"Set label for pane {id_} (current: {cur}): ")
            if new:
                herdr("pane", "rename", id_, new)
                notify("Pane label set", f"{id_} → {new}")
        elif sel == "Move to workspace":
            ws_id = pick_target_workspace(snapshot, exclude_workspace_id=pane.get("workspace_id"))
            if ws_id:
                changed, err = move_pane(id_, new_tab_workspace_id=ws_id)
                if changed:
                    notify("Pane moved", f"{id_} to workspace {ws_id}")
                else:
                    notify("Move failed", err or "herdr refused (active agent pane?)")
        elif sel == "Move to tab":
            tab_id = pick_target_tab_anywhere(snapshot, exclude_tab_id=pane.get("tab_id"))
            if tab_id:
                changed, err = move_pane(id_, tab_id=tab_id)
                if changed:
                    notify("Pane moved", f"{id_} to tab {tab_id}")
                else:
                    notify("Move failed", err or "herdr refused (active agent pane?)")
        elif sel == "Close":
            confirm = prompt(f"Close pane {id_} ({name})? [y/N] ")
            if confirm.lower() == "y":
                herdr("pane", "close", id_, capture=False)


def focus_item(snapshot, typ, id_):
    if typ == "workspace":
        herdr("workspace", "focus", id_, capture=False)
    elif typ == "tab":
        herdr("tab", "focus", id_, capture=False)
    elif typ in ("agent", "pane"):
        # Focus the pane's tab first so we land in the right place, then (for
        # agent panes) focus the agent by pane_id — a stable target that works
        # even when the agent has no explicit name.
        pane, agent = lookup(snapshot, typ, id_)
        if pane is None:
            return
        tab_id = pane.get("tab_id")
        if tab_id:
            herdr("tab", "focus", tab_id, capture=False)
        if agent:
            # `herdr agent focus` only targets herdr-managed agents; for a
            # synthesized (unmanaged) pane it errors out (agent_not_found), so
            # try best-effort — the tab focus above already lands in the tab.
            try:
                herdr("agent", "focus", id_, capture=False)
            except Exception:
                pass


def rename_node(snapshot, typ, id_):
    # alt-t: rename the node's primary identifier without opening the modify
    # submenu (agent name, or workspace/tab label).
    if typ == "workspace":
        ws = lookup(snapshot, typ, id_)
        if not ws:
            return
        new = prompt(f"Rename workspace '{ws.get('label', id_)}' to: ")
        if new:
            herdr("workspace", "rename", id_, new)
            notify("Workspace renamed", f"{ws.get('label', id_)} → {new}")
    elif typ == "tab":
        tab = lookup(snapshot, typ, id_)
        if not tab:
            return
        new = prompt(f"Rename tab '{tab.get('label', id_)}' to: ")
        if new:
            herdr("tab", "rename", id_, new)
            notify("Tab renamed", f"{tab.get('label', id_)} → {new}")
    elif typ in ("agent", "pane"):
        pane, agent = lookup(snapshot, typ, id_)
        if not pane:
            return
        if agent and not agent.get("synthesized"):
            new = prompt(f"Rename agent '{agent['name']}' to: ")
            if new:
                herdr("agent", "rename", agent["name"], new)
                notify("Agent renamed", f"{agent['name']} → {new}")
        else:
            notify("Cannot rename",
                   "This is a live agent session herdr doesn't manage (likely moved). "
                   "Use Alt+l to set the pane label instead.")


def set_node_pane_label(snapshot, typ, id_):
    # alt-l: set the pane's label directly, skipping the modify submenu.
    # Only meaningful for agent/pane nodes.
    if typ not in ("agent", "pane"):
        return
    pane, _ = lookup(snapshot, typ, id_)
    if not pane:
        return
    cur = pane.get("label") or pane.get("terminal_title_stripped", "")
    new = prompt(f"Set label for pane {id_} (current: {cur}): ")
    if new:
        herdr("pane", "rename", id_, new)
        notify("Pane label set", f"{id_} → {new}")


def resolve_cwd(snapshot, typ, id_):
    # Pick the working directory of the pane "at" the selected node, so the new
    # workspace inherits a sensible cwd. agent/pane → that pane; tab/workspace →
    # the focused pane inside it (else the first one).
    pane = None
    if typ in ("agent", "pane"):
        pane = next((p for p in snapshot["panes"] if p["pane_id"] == id_), None)
    elif typ == "tab":
        panes = [p for p in snapshot["panes"] if p.get("tab_id") == id_]
        pane = next((p for p in panes if p.get("focused")), None) or (panes[0] if panes else None)
    elif typ == "workspace":
        panes = [p for p in snapshot["panes"] if p.get("workspace_id") == id_]
        pane = next((p for p in panes if p.get("focused")), None) or (panes[0] if panes else None)
    cwd = pane.get("cwd") if pane else None
    if not cwd:
        fp = next((p for p in snapshot["panes"] if p.get("pane_id") == snapshot.get("focused_pane_id")), None)
        cwd = fp.get("cwd") if fp else None
    if not cwd:
        try:
            cwd = json.loads(herdr("pane", "current"))["result"]["pane"].get("cwd")
        except Exception:
            pass
    return cwd or os.getcwd()


def new_workspace(snapshot, typ, id_):
    # alt-n: create a workspace whose cwd is the selected node's directory.
    cwd = resolve_cwd(snapshot, typ, id_)
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


def dump_tree():
    # fzf `reload()` target: print the current tree (header + lines) so Ctrl+R
    # can refresh the list in place without closing the picker. The picker
    # freezes its snapshot at open time and does not live-update, so a move
    # done from another pane (or before this picker was opened) leaves the
    # tree stale until it is reopened or refreshed.
    snapshot = get_snapshot()
    header_line = "|TYPE        NAME"
    sys.stdout.write("\n".join([header_line] + build_tree(snapshot)) + "\n")


def _snapshot_fingerprint():
    # A cheap fingerprint of the herdr state we display: the structure that
    # build_tree renders (workspaces/tabs/panes labels, pane->tab ownership,
    # agent_session presence). We compare this across polls to detect any
    # change that would affect the tree — a move, rename, create, close, or
    # an agent session appearing/disappearing. (snapshot.protocol is NOT a
    # state sequence — it's a fixed protocol version that never bumps, so we
    # can't use it. ~3ms per call, polled every 0.5s.)
    try:
        snap = json.loads(herdr("api", "snapshot"))["result"]["snapshot"]
    except Exception:
        return None
    parts = []
    for w in sorted(snap["workspaces"], key=lambda w: w.get("workspace_id")):
        parts.append(("ws", w["workspace_id"], w.get("label")))
    for t in sorted(snap["tabs"], key=lambda t: t.get("tab_id")):
        parts.append(("tab", t["tab_id"], t.get("workspace_id"), t.get("label")))
    for p in sorted(snap["panes"], key=lambda p: p.get("pane_id")):
        parts.append(("pane", p["pane_id"], p.get("tab_id"), p.get("label"),
                      bool(p.get("agent_session")), p.get("terminal_title_stripped")))
    for a in sorted(snap.get("agents", []), key=lambda a: a.get("pane_id") or ""):
        parts.append(("agent", a.get("pane_id"), a.get("name"), a.get("agent_status")))
    return repr(parts)


def _fzf_listen_reload(sock_path, self_path):
    # Send a reload action to the running fzf via its --listen Unix socket.
    # fzf's listen API: POST / with the action string as the body → 200 OK.
    # The action reloads the tree from a fresh `--dump-tree` invocation, so
    # the list re-renders with the latest herdr state.
    try:
        body = f"reload(python3 '{self_path}' --dump-tree)".encode()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(sock_path)
        s.send(b"POST / HTTP/1.0\r\nContent-Length: " + str(len(body)).encode()
               + b"\r\n\r\n" + body)
        try:
            s.recv(64)
        except socket.timeout:
            pass
        s.close()
        return True
    except Exception:
        return False


def _start_watcher(sock_path, self_path, stop_event):
    # Background thread: poll herdr's state fingerprint every 0.5s; when it
    # changes (someone edited/moved/renamed a pane from another pane, or herdr
    # state shifted), tell the running fzf to reload its tree from a fresh
    # snapshot. This makes the picker "live" — edit a pane elsewhere, come
    # back to the still-open picker, and the list already reflects the new
    # state without pressing anything. We can't inject keystrokes (picker
    # stdin is a pipe, no /dev/tty), so we drive fzf via its --listen socket.
    last = _snapshot_fingerprint()
    while not stop_event.is_set():
        stop_event.wait(0.5)
        if stop_event.is_set():
            break
        cur = _snapshot_fingerprint()
        if cur is not None and cur != last:
            last = cur
            _fzf_listen_reload(sock_path, self_path)


def main():
    spec = os.environ.get("AGENT_MANAGER_TREE_ITEM")
    if spec:
        typ, id_ = spec.split(":", 1)
        snapshot = get_snapshot()
        focus_item(snapshot, typ, id_)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--dump-tree":
        dump_tree()
        return

    self_path = os.path.abspath(__file__)

    # Live refresh: start an fzf --listen socket + a watcher that reloads the
    # tree whenever herdr's state changes. Socket lives in a temp dir we own.
    listen_dir = tempfile.mkdtemp(prefix="herdr-picker-")
    sock_path = os.path.join(listen_dir, "listen.sock")
    stop_event = threading.Event()
    watcher = threading.Thread(
        target=_start_watcher, args=(sock_path, self_path, stop_event),
        daemon=True)

    try:
        while True:
            # Ensure a clean socket path each iteration (fzf rebinds --listen
            # to it; a leftover socket file from a previous fzf would make
            # the bind fail).
            try:
                os.unlink(sock_path)
            except OSError:
                pass
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
            fzf_header = (f"spaces tree — enter:focus  {MODIFY_KEY}:modify  "
                         f"alt-t:title  alt-l:label  alt-n:new-ws  "
                         f"ctrl-r:refresh  esc:quit")
            # ctrl-r reloads the tree in place from a fresh snapshot (manual refresh
            # on top of the automatic watcher-driven refresh).
            reload_bind = f"ctrl-r:reload(python3 '{self_path}' --dump-tree)"
            # Launch fzf with Popen so we can start the watcher WHILE fzf runs —
            # the watcher needs the live --listen socket to send reloads to. We
            # feed the tree via communicate(input=...) which writes stdin, closes
            # it, and waits — but we start the watcher first so it runs in
            # parallel. fzf's stderr inherits our stderr (the pane TTY in real
            # herdr), which is where fzf renders its UI.
            # Build a clean env for fzf: inherit the current environment but drop
            # FZF_DEFAULT_OPTS / FZF_DEFAULT_COMMAND. Herdr starts the picker from a
            # shell that may export FZF_DEFAULT_OPTS (e.g. fish universal vars like
            # `--height 40%`, or a user-set `--layout=reverse`/`--tac`), and any of
            # those would silently change the picker's fzf behavior. Stripping them
            # makes the picker's fzf obey ONLY the explicit flags below — so the
            # workspace→tab→pane order is deterministic regardless of the shell env.
            fzf_env = {k: v for k, v in os.environ.items()
                       if k not in ("FZF_DEFAULT_OPTS", "FZF_DEFAULT_COMMAND")}
            fzf_proc = subprocess.Popen(
                ["fzf", "--no-sort",          # preserve tree (workspace→tab→pane) order;
                       # fzf's default sort reorders filtered results by match relevance,
                       # which lifts a child node (e.g. `tab travel`) above its parent
                       # workspace (`travel-rule`) when you search for it — breaking the
                       # nesting. --no-sort keeps input order for both the full list and
                       # query-filtered matches.
                       "--layout=reverse",  # workspace on top, tab/pane indented below.
                       # Why reverse and not default: a non-visual fzf probe (load:up+accept
                       # on a 3-item list) shows that in this fzf build 0.74.2, under the
                       # picker's env, --layout=default renders the list BOTTOM-up (first
                       # input item at the bottom of the screen) while --layout=reverse
                       # renders it TOP-down (first input item at the top). Since build_tree
                       # emits workspaces first, --layout=reverse puts the first workspace
                       # at the top — the workspace→tab→pane order the user wants. This
                       # matches the user's live observation (default showed reversed).
                       "--delimiter=|",
                       "--with-nth=2",
                       "--header-lines=1",
                       "--header", fzf_header,
                       "--prompt=space> ",
                       "--preview", preview,
                       "--preview-window=right:50%",
                       f"--expect={MODIFY_KEY},alt-t,alt-l,alt-n",
                       "--bind", reload_bind,
                       f"--listen={sock_path}",
                       "--color", "bg+:#3b4261,fg+:#ffffff"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                env=fzf_env,
            )

            # Start the watcher now that fzf is launching. It polls herdr's state
            # and sends reload actions to fzf's --listen socket when anything
            # changes — so an edit/move done from another pane shows up here
            # automatically, no key press needed.
            if not watcher.is_alive():
                watcher.start()

            # Feed the tree and wait for fzf to exit (user picks or Esc). The
            # watcher reloads the list in the background while we block here.
            try:
                result_stdout, _ = fzf_proc.communicate(input="\n".join(lines))
            except KeyboardInterrupt:
                fzf_proc.terminate()
                result_stdout, _ = fzf_proc.communicate()
            result_stdout = result_stdout or ""

            if fzf_proc.returncode != 0 or not result_stdout.strip():
                break

            parts = result_stdout.strip("\n").split("\n")
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

            if action == "alt-t":
                rename_node(snapshot, typ, id_)
                continue

            if action == "alt-l":
                set_node_pane_label(snapshot, typ, id_)
                continue

            if action == "alt-n":
                new_workspace(snapshot, typ, id_)
                continue

            focus_item(snapshot, typ, id_)
            break
    finally:
        # Stop the watcher and remove the listen socket + temp dir on every
        # exit path (Esc, focus action, close, error). The socket is reused
        # across loop iterations, so only clean it up here at the end.
        stop_event.set()
        try:
            os.unlink(sock_path)
        except OSError:
            pass
        try:
            os.rmdir(listen_dir)
        except OSError:
            pass


if __name__ == "__main__":
    main()
