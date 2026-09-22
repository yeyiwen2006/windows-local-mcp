"""Local-only controls. Never exported as remotely callable resume tools."""
import argparse
import json

from .guard import Guard, state_directory


def main():
    parser = argparse.ArgumentParser(description="Local operator control for Windows Local MCP")
    parser.add_argument("action", choices=["pause", "resume", "status", "commands-enable", "commands-disable"])
    parser.add_argument("--acknowledge-current-user-access", action="store_true")
    args = parser.parse_args()
    if args.action in ("commands-enable", "commands-disable"):
        if args.action == "commands-enable" and not args.acknowledge_current_user_access:
            parser.error("Enabling commands requires --acknowledge-current-user-access locally")
        guard = Guard()
        marker = guard.state / "COMMANDS_ENABLED"
        if args.action == "commands-enable":
            marker.write_text("current-user commands explicitly enabled by local operator\n", encoding="utf-8")
            print("Local commands enabled. Existing pause state is unchanged.")
        else:
            marker.unlink(missing_ok=True)
            print("Local commands disabled; running command jobs will terminate.")
        return
    state = state_directory()
    state.mkdir(parents=True, exist_ok=True)
    if args.action == "pause":
        (state / "PAUSED").write_text("paused\n", encoding="utf-8")
        print("Paused. Running long operations stop at the next checkpoint.")
    elif args.action == "resume":
        (state / "PAUSED").unlink(missing_ok=True)
        print("Resumed. If a disk error caused an in-memory emergency stop, restart the server.")
    else:
        print(json.dumps({"paused": (state / "PAUSED").exists(), "state_directory": str(state),
                          "note": "This reports the local pause marker, not connection health."}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
