import re

# The bounds a server's settings may take. Discord enforces them in the command picker, and they are
# checked again here because a client is free to send anything
REACTION_THRESHOLD_MIN = 1
REACTION_THRESHOLD_MAX = 1000
POST_DUE_DATE_MIN = 1
POST_DUE_DATE_MAX = 3650

# A whitelist is read on every reaction, and past this it has stopped being a whitelist
WHITELIST_MAX_SIZE = 100

custom_emoji_pattern = re.compile(r"^<(a?):([A-Za-z0-9_]{2,32}):([0-9]{15,21})>$")


def normalize_emoji(raw: str) -> str | None:
    """
    Trim what a member typed for /whitelist_emoji. Whatever they send is stored as-is; if it is not
    how Discord itself writes that emoji it simply never matches a reaction, rather than being
    refused up front.
    :param raw: The text from the command
    :return: The trimmed text, or None when nothing was given
    """
    text = (raw or "").strip()
    return text or None


def custom_emoji_id(emoji: str) -> str | None:
    """
    :param emoji: An emoji as stored in the whitelist
    :return: Its ID when it is a custom emoji, which survives the emoji being renamed
    """
    match = custom_emoji_pattern.match(emoji or "")
    return match.group(3) if match is not None else None


def find_in_whitelist(whitelist, raw: str) -> str | None:
    """
    Find the whitelist entry a member means, for taking it off the list
    :param whitelist: The server's whitelist
    :param raw: The text from the command
    :return: The entry exactly as stored, or None when it is not on the list
    """
    text = (raw or "").strip()
    if text in whitelist:
        return text

    # A custom emoji keeps its ID when it is renamed, so a member can still remove it by pasting the
    # emoji's current tag even though the whitelist stored it under the old name
    emoji_id = custom_emoji_id(text)
    if emoji_id is not None:
        for entry in whitelist:
            if custom_emoji_id(entry) == emoji_id:
                return entry
    return None


def out_of_range_message(label: str, value: int, minimum: int, maximum: int) -> str | None:
    """
    :return: Why the value was refused, or None when it is within the bounds
    """
    if minimum <= value <= maximum:
        return None
    return f"{label} must be between {minimum} and {maximum}, but got {value}."
