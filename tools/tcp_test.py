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
    demo          Run automated demo sequence
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
                current_project = arg or f"project-{session_counter}"
                msg = {"event": "session_start", "session_id": current_sid, "project": current_project}
                await send(writer, msg)
                print(f"  [session {current_sid}] started ({current_project})")
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
