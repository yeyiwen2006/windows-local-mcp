"""Local-only controls. Never exported as remotely callable resume tools."""
import argparse
import json

from .guard import Guard, state_directory


def main():
    parser = argparse.ArgumentParser(description="Local operator control for Windows Local MCP")
    parser.add_argument("action", choices=["pause", "resume", "status"])
    args = parser.parse_args()
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
