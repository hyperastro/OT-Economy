from Commands.parser import check_post_for_commands, command_queue
from Commands.history import record_command

"""
Public entry point for the Commands package.

main.py imports check_post_for_commands, process_command_queue, and
command_queue from here — this module re-exports the first and third from
parser.py and defines process_command_queue, which executes whatever
check_post_for_commands queued up.

The actual command logic now lives in:
    history.py           - command history persistence
    utils.py              - shared helpers (validation, user lookup, stack ids)
    economy_commands.py   - !register, !give, !item ..., !invest
    entity_commands.py    - !entity ..., !buy
    parser.py             - regex matching + command_queue
"""

# === QUEUE PROCESSING ===
def process_command_queue(queue):
    """
    Executes all commands in the queue.
    Returns True if any command changed the database (e.g. balance, items), otherwise False.
    """
    changed = False  # Track if anything modified the economy

    while queue:
        cmd = queue.pop(0)
        handler = cmd["handler"]
        args = cmd["args"]
        user_id = cmd["user_id"]
        username = cmd.get("username", "unknown")
        raw_command = cmd.get("raw", handler.__name__)
        topic_id = cmd.get("topic_id")

        print(f"Executing {handler.__name__} from {username} ({user_id}) with args {args}")

        try:
            # Execute command handler
            result = handler(args, user_id, username, topic_id)

            # If handler reports a change, mark as changed
            if result:
                changed = True

            record_command(username, raw_command, result)

        except Exception as e:
            print(f"Error executing {handler.__name__}: {e}")
            record_command(username, raw_command, False)

    return changed
