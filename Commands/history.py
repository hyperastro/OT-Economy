import json
import time
import config

"""
Command history persistence.

Tracks the most recently executed commands (success or failure) so they can
be shown on the forum post — see ForumUpdate.create_command_history().
"""

# === COMMAND HISTORY UTILITIES ===
def load_command_history():
    if config.COMMAND_HISTORY_PATH.exists():
        with open(config.COMMAND_HISTORY_PATH, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

def save_command_history(history):
    with open(config.COMMAND_HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=4)

def record_command(username, raw_command, success):
    """Append an executed command to the history log, keeping only the most recent MAX_COMMAND_HISTORY entries."""
    history = load_command_history()
    history.append({
        "timestamp": time.time(),
        "username": username,
        "command": raw_command,
        "success": bool(success)
    })
    history = history[-config.MAX_COMMAND_HISTORY:]
    save_command_history(history)
