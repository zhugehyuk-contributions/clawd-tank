#!/usr/bin/env python3
"""tcp_test.py — Interactive TCP test CLI for Clawd Tank network server.

Connects to the daemon's network server and sends session events directly,
bypassing Claude Code hooks and BLE. Useful for testing without hardware.

Usage:
    python tools/tcp_test.py                         # localhost:19873
    python tools/tcp_test.py --host 192.168.1.10     # remote server
    python tools/tcp_test.py --port 19874            # custom port

Interactive commands:
    s <project>   Start a new session
    t <tool>      Tool use (Edit/Bash/Read/Grep/Agent/WebSearch/LSP)
    w             Waiting for input (Stop notification)
    u             User prompt submit (dismiss + thinking)
    e             End current session
    a+            Subagent start
    a-            Subagent stop
    n <message>   Custom notification
    c             Clear all notifications
    demo          Run single-machine demo (3 sessions)
    demo2         Run multi-machine demo (3 machines, 5 sessions, labels [A][B][C])
    demo3         Run skin color showcase (presets + custom colors + rainbow cycle)
    q             Quit
"""

import argparse
import asyncio
import json
import sys
import uuid


async def do_connect(host: str, port: int, hostname: str):
    """Connect and perform handshake. Returns (reader, writer)."""
    reader, writer = await asyncio.open_connection(host, port)
    hello = json.dumps({"type": "hello", "hostname": hostname}) + "\n"
    writer.write(hello.encode())
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), timeout=5.0)
    welcome = json.loads(line.decode())
    server = welcome.get("server", "unknown")
    print(f"Connected to {server} (port {port})")
    return reader, writer


async def send(writer, msg: dict):
    """Send a daemon message."""
    writer.write((json.dumps(msg) + "\n").encode())
    await writer.drain()


async def run_demo(writer):
    """Run an automated 3-session demo sequence."""
    sids = [f"demo-{i}" for i in range(1, 4)]
    projects = ["project-a", "project-b", "project-c"]
    agent_id = f"agent-{uuid.uuid4().hex[:8]}"

    steps = [
        (0.5, {"event": "session_start", "session_id": sids[0], "project": projects[0]}),
        (1.0, {"event": "tool_use", "session_id": sids[0], "tool_name": "Edit", "project": projects[0]}),
        (0.5, {"event": "session_start", "session_id": sids[1], "project": projects[1]}),
        (1.0, {"event": "tool_use", "session_id": sids[1], "tool_name": "Bash", "project": projects[1]}),
        (1.0, {"event": "tool_use", "session_id": sids[0], "tool_name": "Agent", "project": projects[0]}),
        (1.0, {"event": "subagent_start", "session_id": sids[0], "agent_id": agent_id}),
        (0.5, {"event": "session_start", "session_id": sids[2], "project": projects[2]}),
        (2.0, {"event": "tool_use", "session_id": sids[2], "tool_name": "WebSearch", "project": projects[2]}),
        (2.0, {"event": "add", "hook": "Stop", "session_id": sids[1], "project": projects[1], "message": "Waiting for input"}),
        (1.0, {"event": "dismiss", "hook": "UserPromptSubmit", "session_id": sids[1]}),
        (1.0, {"event": "subagent_stop", "session_id": sids[0], "agent_id": agent_id}),
    ]

    print("Running demo sequence...")
    for i, (delay, msg) in enumerate(steps, 1):
        event = msg["event"]
        extra = msg.get("tool_name", msg.get("hook", ""))
        sid_short = msg.get("session_id", "")
        print(f"  [{i}/{len(steps)}] {event} {extra} ({sid_short})")
        await send(writer, msg)
        await asyncio.sleep(delay)

    # End all sessions
    for sid in sids:
        await send(writer, {"event": "dismiss", "hook": "SessionEnd", "session_id": sid})
        await asyncio.sleep(0.3)

    print("Demo complete.")


async def run_multi_demo(host: str, port: int):
    """Simulate 3 machines connecting simultaneously with interleaved work."""
    machines = [
        {"hostname": "macbook-pro", "projects": ["api-server", "auth-lib"]},
        {"hostname": "imac-studio", "projects": ["ml-pipeline"]},
        {"hostname": "linux-ci", "projects": ["infra-deploy", "monitoring"]},
    ]

    # Connect all machines
    connections = []
    for m in machines:
        r, w = await asyncio.open_connection(host, port)
        hello = json.dumps({"type": "hello", "hostname": m["hostname"]}) + "\n"
        w.write(hello.encode())
        await w.drain()
        welcome = await asyncio.wait_for(r.readline(), timeout=5.0)
        wdata = json.loads(welcome.decode())
        print(f"  {m['hostname']} connected → server {wdata.get('server', '?')}")
        connections.append((m, w))
        await asyncio.sleep(0.3)

    async def s(writer, msg):
        writer.write((json.dumps(msg) + "\n").encode())
        await writer.drain()

    m0, w0 = connections[0]  # macbook-pro
    m1, w1 = connections[1]  # imac-studio
    m2, w2 = connections[2]  # linux-ci

    steps = [
        # macbook-pro starts coding (default skin)
        (0.5, w0, {"event": "session_start", "session_id": "s1", "project": "api-server"},
         "[A] macbook-pro: session_start api-server"),
        (1.0, w0, {"event": "tool_use", "session_id": "s1", "tool_name": "Edit", "project": "api-server"},
         "[A] macbook-pro: Edit api-server"),

        # imac-studio joins with ML work (white skin)
        (0.5, w1, {"event": "session_start", "session_id": "s1", "project": "ml-pipeline", "skin": "clawd-white"},
         "[B] imac-studio: session_start ml-pipeline (clawd-white)"),
        (1.0, w1, {"event": "tool_use", "session_id": "s1", "tool_name": "Bash", "project": "ml-pipeline"},
         "[B] imac-studio: Bash ml-pipeline"),

        # linux-ci starts deploy (black skin)
        (0.5, w2, {"event": "session_start", "session_id": "s1", "project": "infra-deploy", "skin": "clawd-black"},
         "[C] linux-ci: session_start infra-deploy (clawd-black)"),
        (1.0, w2, {"event": "tool_use", "session_id": "s1", "tool_name": "Bash", "project": "infra-deploy"},
         "[C] linux-ci: Bash infra-deploy"),

        # macbook-pro spawns subagent
        (1.0, w0, {"event": "tool_use", "session_id": "s1", "tool_name": "Agent", "project": "api-server"},
         "[A] macbook-pro: Agent (spawning subagent)"),
        (0.5, w0, {"event": "subagent_start", "session_id": "s1", "agent_id": "agent-review"},
         "[A] macbook-pro: subagent started"),

        # macbook-pro starts 2nd session (custom red skin)
        (0.5, w0, {"event": "session_start", "session_id": "s2", "project": "auth-lib", "skin": "clawd-custom", "body_color": "FF0000"},
         "[A] macbook-pro: session_start auth-lib (clawd-custom red)"),
        (1.0, w0, {"event": "tool_use", "session_id": "s2", "tool_name": "Read", "project": "auth-lib"},
         "[A] macbook-pro: Read auth-lib"),

        # imac-studio searches web
        (1.0, w1, {"event": "tool_use", "session_id": "s1", "tool_name": "WebSearch", "project": "ml-pipeline"},
         "[B] imac-studio: WebSearch ml-pipeline"),

        # linux-ci finishes, waits for input
        (2.0, w2, {"event": "add", "hook": "Stop", "session_id": "s1", "project": "infra-deploy", "message": "Deploy complete. Proceed?"},
         "[C] linux-ci: NOTIFICATION 'Deploy complete. Proceed?'"),

        # linux-ci starts 2nd session for monitoring (transparent skin)
        (1.0, w2, {"event": "session_start", "session_id": "s2", "project": "monitoring", "skin": "clawd-transparent"},
         "[C] linux-ci: session_start monitoring (clawd-transparent)"),
        (1.0, w2, {"event": "tool_use", "session_id": "s2", "tool_name": "Grep", "project": "monitoring"},
         "[C] linux-ci: Grep monitoring"),

        # imac-studio hits error
        (2.0, w1, {"event": "add", "hook": "StopFailure", "session_id": "s1", "project": "ml-pipeline", "message": "CUDA out of memory"},
         "[B] imac-studio: ERROR 'CUDA out of memory' (red LED flash)"),

        # macbook-pro subagent done
        (2.0, w0, {"event": "subagent_stop", "session_id": "s1", "agent_id": "agent-review"},
         "[A] macbook-pro: subagent stopped"),

        # linux-ci user responds
        (1.0, w2, {"event": "dismiss", "hook": "UserPromptSubmit", "session_id": "s1"},
         "[C] linux-ci: user responds → thinking"),

        # Hold for viewing
        (3.0, None, None, "... holding for 3s ..."),
    ]

    print("\nRunning multi-machine demo (3 machines, 5 sessions)...\n")
    for i, (delay, writer, msg, desc) in enumerate(steps, 1):
        print(f"  [{i:2d}/{len(steps)}] {desc}")
        if writer and msg:
            await s(writer, msg)
        await asyncio.sleep(delay)

    # Clean up: end all sessions
    print("\n  Cleaning up sessions...")
    for m, w in connections:
        for sid in ["s1", "s2"]:
            await s(w, {"event": "dismiss", "hook": "SessionEnd", "session_id": sid})
            await asyncio.sleep(0.1)

    # Disconnect all
    for m, w in connections:
        w.close()
        try:
            await w.wait_closed()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    await asyncio.sleep(0.5)
    print("Multi-machine demo complete.\n")


async def run_skin_demo(host: str, port: int):
    """Showcase all skin presets + custom colors cycling through animations."""
    skins = [
        ("default",     None,             None),
        ("clawd-white", "clawd-white",    None),
        ("clawd-black", "clawd-black",    None),
        ("clawd-transparent", "clawd-transparent", None),
        ("red",         "clawd-custom",   "FF0000"),
        ("blue",        "clawd-custom",   "0088FF"),
        ("green",       "clawd-custom",   "00CC44"),
        ("purple",      "clawd-custom",   "AA00FF"),
        ("gold",        "clawd-custom",   "FFD700"),
        ("cyan",        "clawd-custom",   "00FFFF"),
        ("pink",        "clawd-custom",   "FF69B4"),
        ("lime",        "clawd-custom",   "AAFF00"),
    ]
    tools = ["Edit", "Bash", "Read", "Agent", "WebSearch", "Grep"]

    r, w = await asyncio.open_connection(host, port)
    w.write((json.dumps({"type": "hello", "hostname": "skin-demo"}) + "\n").encode())
    await w.drain()
    welcome = await asyncio.wait_for(r.readline(), timeout=5.0)
    print(f"Connected to {json.loads(welcome.decode()).get('server', '?')}\n")

    async def s(msg):
        w.write((json.dumps(msg) + "\n").encode())
        await w.drain()

    print("=== Phase 1: All 5 presets side by side ===\n")
    preset_sids = []
    for i, (name, skin, color) in enumerate(skins[:4]):
        sid = f"preset-{i}"
        preset_sids.append(sid)
        msg = {"event": "session_start", "session_id": sid, "project": name}
        if skin:
            msg["skin"] = skin
        if color:
            msg["body_color"] = color
        await s(msg)
        await asyncio.sleep(0.3)
        await s({"event": "tool_use", "session_id": sid, "tool_name": tools[i % len(tools)], "project": name})
        print(f"  [{i+1}/4] {name:20s} → {tools[i % len(tools)]}")
        await asyncio.sleep(0.5)

    print("\n  Showing 4 presets for 5s...")
    await asyncio.sleep(5)

    # Remove presets
    for sid in preset_sids:
        await s({"event": "dismiss", "hook": "SessionEnd", "session_id": sid})
        await asyncio.sleep(0.2)
    await asyncio.sleep(1)

    print("\n=== Phase 2: Custom color parade (4 at a time) ===\n")
    custom_skins = skins[4:]  # red, blue, green, purple, gold, cyan, pink, lime
    for batch_start in range(0, len(custom_skins), 4):
        batch = custom_skins[batch_start:batch_start + 4]
        batch_sids = []
        for i, (name, skin, color) in enumerate(batch):
            sid = f"color-{batch_start + i}"
            batch_sids.append(sid)
            msg = {"event": "session_start", "session_id": sid, "project": name, "skin": skin, "body_color": color}
            await s(msg)
            await asyncio.sleep(0.2)
            tool = tools[(batch_start + i) % len(tools)]
            await s({"event": "tool_use", "session_id": sid, "tool_name": tool, "project": name})
            print(f"  #{color} {name:8s} → {tool}")
            await asyncio.sleep(0.3)

        print(f"\n  Showing batch for 5s...")
        await asyncio.sleep(5)

        for sid in batch_sids:
            await s({"event": "dismiss", "hook": "SessionEnd", "session_id": sid})
            await asyncio.sleep(0.2)
        await asyncio.sleep(1)

    print("\n=== Phase 3: Rainbow animation cycle ===\n")
    rainbow = [
        ("FF0000", "Edit"),    # red
        ("FF8800", "Bash"),    # orange
        ("FFFF00", "Read"),    # yellow
        ("00FF00", "Agent"),   # green
    ]
    rainbow_sids = []
    for i, (color, tool) in enumerate(rainbow):
        sid = f"rainbow-{i}"
        rainbow_sids.append(sid)
        await s({"event": "session_start", "session_id": sid, "project": f"#{color}", "skin": "clawd-custom", "body_color": color})
        await asyncio.sleep(0.2)
        await s({"event": "tool_use", "session_id": sid, "tool_name": tool, "project": f"#{color}"})
        print(f"  #{color} → {tool}")
        await asyncio.sleep(0.5)

    print("\n  Cycling animations for 10s...")
    cycle_tools = ["Edit", "Bash", "WebSearch", "Agent", "Read", "Grep"]
    for cycle in range(5):
        await asyncio.sleep(2)
        for i, sid in enumerate(rainbow_sids):
            tool = cycle_tools[(cycle + i) % len(cycle_tools)]
            await s({"event": "tool_use", "session_id": sid, "tool_name": tool, "project": f"cycle-{cycle}"})
        print(f"  cycle {cycle + 1}/5")

    await asyncio.sleep(2)
    for sid in rainbow_sids:
        await s({"event": "dismiss", "hook": "SessionEnd", "session_id": sid})
        await asyncio.sleep(0.1)

    w.close()
    try:
        await w.wait_closed()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    print("\nSkin demo complete.\n")


async def interactive(host: str, port: int, hostname: str):
    """Main interactive loop."""
    try:
        reader, writer = await do_connect(host, port, hostname)
    except (ConnectionRefusedError, OSError) as e:
        print(f"Server not running on {host}:{port} — {e}")
        return

    session_counter = 0
    current_sid = None
    current_project = "test-project"
    agent_counter = 0

    print("Type 'help' for commands, 'q' to quit.\n")

    try:
        while True:
            try:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("> ")
                )
            except EOFError:
                break

            parts = line.strip().split(maxsplit=1)
            if not parts:
                continue
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == "q":
                break
            elif cmd == "help":
                print(__doc__)
            elif cmd == "s":
                session_counter += 1
                current_sid = f"{hostname}-{session_counter}"
                # Parse: s <project> [skin] [body_color]
                s_parts = arg.split()
                current_project = s_parts[0] if s_parts else f"project-{session_counter}"
                skin = s_parts[1] if len(s_parts) > 1 else None
                body_color = s_parts[2] if len(s_parts) > 2 else None
                msg = {"event": "session_start", "session_id": current_sid, "project": current_project}
                if skin:
                    msg["skin"] = skin
                if body_color:
                    msg["body_color"] = body_color
                await send(writer, msg)
                skin_info = f" skin={skin}" if skin else ""
                print(f"  [session {current_sid}] started ({current_project}{skin_info})")
            elif cmd == "t":
                if not current_sid:
                    print("  No active session. Use 's' first.")
                    continue
                tool = arg or "Edit"
                msg = {"event": "tool_use", "session_id": current_sid, "tool_name": tool, "project": current_project}
                await send(writer, msg)
                print(f"  [session {current_sid}] tool_use: {tool}")
            elif cmd == "w":
                if not current_sid:
                    print("  No active session. Use 's' first.")
                    continue
                msg = {"event": "add", "hook": "Stop", "session_id": current_sid, "project": current_project, "message": "Waiting for input"}
                await send(writer, msg)
                print(f"  [session {current_sid}] waiting for input")
            elif cmd == "u":
                if not current_sid:
                    print("  No active session. Use 's' first.")
                    continue
                msg = {"event": "dismiss", "hook": "UserPromptSubmit", "session_id": current_sid}
                await send(writer, msg)
                print(f"  [session {current_sid}] user prompt submitted")
            elif cmd == "e":
                if not current_sid:
                    print("  No active session.")
                    continue
                msg = {"event": "dismiss", "hook": "SessionEnd", "session_id": current_sid}
                await send(writer, msg)
                print(f"  [session {current_sid}] ended")
                current_sid = None
            elif cmd == "a+":
                if not current_sid:
                    print("  No active session. Use 's' first.")
                    continue
                agent_counter += 1
                aid = f"agent-{agent_counter}"
                msg = {"event": "subagent_start", "session_id": current_sid, "agent_id": aid}
                await send(writer, msg)
                print(f"  [session {current_sid}] subagent started: {aid}")
            elif cmd == "a-":
                if not current_sid:
                    print("  No active session. Use 's' first.")
                    continue
                aid = f"agent-{agent_counter}"
                msg = {"event": "subagent_stop", "session_id": current_sid, "agent_id": aid}
                await send(writer, msg)
                print(f"  [session {current_sid}] subagent stopped: {aid}")
            elif cmd == "n":
                if not current_sid:
                    print("  No active session. Use 's' first.")
                    continue
                message = arg or "Custom notification"
                msg = {"event": "add", "hook": "Notification", "session_id": current_sid, "project": current_project, "message": message}
                await send(writer, msg)
                print(f"  [session {current_sid}] notification: {message}")
            elif cmd == "c":
                msg = {"event": "clear"}
                await send(writer, msg)
                print("  Cleared all")
            elif cmd == "demo":
                await run_demo(writer)
            elif cmd == "demo2":
                await run_multi_demo(host, port)
            elif cmd == "demo3":
                await run_skin_demo(host, port)
            else:
                print(f"  Unknown command: {cmd}. Type 'help' for commands.")

    except (ConnectionResetError, BrokenPipeError):
        print("\nConnection lost.")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        print("Disconnected.")


def main():
    parser = argparse.ArgumentParser(description="Clawd Tank TCP test CLI")
    parser.add_argument("--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=19873, help="Server port (default: 19873)")
    parser.add_argument("--hostname", default="tcp-test", help="Client hostname (default: tcp-test)")
    args = parser.parse_args()

    asyncio.run(interactive(args.host, args.port, args.hostname))


if __name__ == "__main__":
    main()
