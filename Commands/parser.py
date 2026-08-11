import re
from API.API import OsuApi

from Commands.economy_commands import (
    cmd_register, cmd_give, cmd_item_create, cmd_item_give,
    cmd_item_delete, cmd_item_upgrade, cmd_invest
)
from Commands.entity_commands import (
    cmd_entity_create, cmd_entity_hire, cmd_entity_fire, cmd_entity_deposit,
    cmd_entity_withdraw, cmd_entity_item_create, cmd_entity_sell, cmd_buy,
    cmd_entity_transfer, cmd_entity_permission_grant, cmd_entity_permission_revoke
)

"""
Scans raw forum post text for commands:
- strip_code_and_quotes removes [quote]...[/quote] blocks so quoted commands
  don't get re-triggered.
- COMMANDS maps a regex pattern to the handler it should queue.
- check_post_for_commands() runs every new post against COMMANDS and appends
  matches to command_queue, which process_command_queue() (in commands.py)
  later executes.
"""

command_queue = []


# === QUOTE STRIPPING ===
def strip_code_and_quotes(text: str) -> str:
    '''Removes the `[c]`, `[code]` and `[quote]` blocks and their content from string.'''
    # Regex expressions
    REGEX_PATTERNS: list[str] = [
        r"\[c\](?!.*\[c*\]).*?\[/c\]|\[code\](?!.*\[code*\]).*?\[/code\]",  # clear [c] and [code] blocks
        r"(?<=\[quote)=\"[^\"]*\"(?=\])",  # remove arg in [quote] blocks
        r"\[quote\](?!.*\[quote\]).*?\[/quote\]"  # remove [quote] blocks
    ]

    # Removal loop, in order of the list
    for pattern_str in REGEX_PATTERNS:
        pattern: re.Pattern[str] = re.compile(pattern_str, re.DOTALL)
        m: re.Match[str] | None = pattern.search(text)
        while m is not None:
            text = text[:m.start()] + text[m.end():]
            m = pattern.search(text)
    return text


# === COMMAND REGEX ===
# UINT_REGEX  — captures a non-negative integer
# STR_REGEX   — captures either a quoted string ('...' or "...") allowing spaces,
#               or a plain single word (min 1 char, must not start with a quote).
#               The [^\s\"'] first-char class prevents whitespace and mismatched quotes.
UINT_REGEX = r"(\d+)"
STR_REGEX  = r"((?:\")[^\"\v\f\r]+(?:\")|(?:')[^\'\v\f\r]+(?:')|[^\s\"']\S*)"

COMMANDS = [
    (r"^\s*!register\s*$",                                                                                          cmd_register),
    (r"^\s*!give\s+"          + UINT_REGEX + r"\s+" + STR_REGEX + r"\s*$",                                         cmd_give),
    (r"^\s*!item\s+create\s+" + STR_REGEX  + r"(?:\s+" + UINT_REGEX + r")?\s*$",                                   cmd_item_create),
    (r"^\s*!item\s+give\s+"   + STR_REGEX  + r"\s+" + STR_REGEX + r"(?:\s+" + UINT_REGEX + r"(?:\s+" + UINT_REGEX + r")?)?\s*$",              cmd_item_give),
    (r"^\s*!item\s+delete\s+" + STR_REGEX  + r"\s+" + UINT_REGEX + r"(?:\s+" + UINT_REGEX + r")?\s*$",             cmd_item_delete),
    (r"^\s*!item\s+upgrade\s+rarity\s+" + STR_REGEX + r"\s+" + UINT_REGEX + r"(?:\s+" + UINT_REGEX + r")?\s*$",   cmd_item_upgrade),
    (r"^\s*!invest\s+"        + UINT_REGEX + r"\s+" + UINT_REGEX + r"\s+" + UINT_REGEX + r"\s*$",                  cmd_invest),
    # --- Entity commands ---
    (r"^\s*!entity\s+create\s+"      + STR_REGEX + r"\s*$",                                                                                                              cmd_entity_create),
    (r"^\s*!entity\s+hire\s+"        + STR_REGEX + r"\s+" + STR_REGEX + r"\s*$",                                                                                         cmd_entity_hire),
    (r"^\s*!entity\s+fire\s+"        + STR_REGEX + r"\s+" + STR_REGEX + r"\s*$",                                                                                         cmd_entity_fire),
    (r"^\s*!entity\s+deposit\s+"     + STR_REGEX + r"\s+" + UINT_REGEX + r"\s*$",                                                                                        cmd_entity_deposit),
    (r"^\s*!entity\s+withdraw\s+"    + STR_REGEX + r"\s+" + UINT_REGEX + r"\s*$",                                                                                        cmd_entity_withdraw),
    (r"^\s*!entity\s+item\s+create\s+" + STR_REGEX + r"\s+" + STR_REGEX + r"(?:\s+" + UINT_REGEX + r")?\s*$",                                                           cmd_entity_item_create),
    (r"^\s*!entity\s+sell\s+"        + STR_REGEX + r"\s+" + UINT_REGEX + r"\s+" + STR_REGEX + r"(?:\s+" + UINT_REGEX + r"(?:\s+" + UINT_REGEX + r")?)?\s*$",            cmd_entity_sell),
    (r"^\s*!entity\s+permission\s+grant\s+withdraw\s+"  + STR_REGEX + r"\s+" + STR_REGEX + r"\s*$",  cmd_entity_permission_grant),
    (r"^\s*!entity\s+permission\s+revoke\s+withdraw\s+" + STR_REGEX + r"\s+" + STR_REGEX + r"\s*$",  cmd_entity_permission_revoke),
    (r"^\s*!entity\s+transfer\s+ownership\s+" + STR_REGEX + r"\s+" + STR_REGEX + r"\s*$",                           cmd_entity_transfer),
    (r"^\s*!buy\s+"                  + STR_REGEX + r"\s+" + STR_REGEX + r"(?:\s+" + UINT_REGEX + r"(?:\s+" + UINT_REGEX + r")?)?\s*$",                                  cmd_buy),
]


# === COMMAND DETECTION ===
def check_post_for_commands(postList):
    if not postList:
        return None

    for post in postList:
        raw_text = post.get("raw", "")
        dequoted_text = strip_code_and_quotes(raw_text.replace('\r\n', '\n').replace('\r', '\n')).strip()

        for pattern, handler in COMMANDS:
            for line in dequoted_text.split("\n"):
                for match in re.finditer(pattern, line, flags=re.IGNORECASE):
                    args = [arg for arg in match.groups() if arg is not None]
                    # Strip surrounding ' or " from quoted string arguments
                    args = [arg[1:-1] if arg and arg[0] in "'\"" else arg for arg in args]
                    command_queue.append({
                        "post_id": post.get("id"),
                        "topic_id": post.get("topic_id"),
                        "user_id": post.get("user_id"),
                        "command": handler.__name__,
                        "username": "".join(OsuApi.get_username(post.get("user_id")).split()),
                        "args": args,
                        "raw": match.group(0).strip(),
                        "handler": handler
                    })
    return command_queue
