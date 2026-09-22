import re
import unicodedata

# The bounds a server's settings may take. Discord enforces them in the command picker, and they are
# checked again here because a client is free to send anything
REACTION_THRESHOLD_MIN = 1
REACTION_THRESHOLD_MAX = 1000
POST_DUE_DATE_MIN = 1
POST_DUE_DATE_MAX = 3650

# A whitelist is read on every reaction, and past this it has stopped being a whitelist
WHITELIST_MAX_SIZE = 100

custom_emoji_pattern = re.compile(r"^<(a?):([A-Za-z0-9_]{2,32}):([0-9]{15,21})>$")
emoji_name_pattern = re.compile(r"^:([A-Za-z0-9_]{2,32}):$")

zero_width_joiner = "‍"
keycap = "⃣"
# Emoji that Unicode files under punctuation rather than symbols
punctuation_emojis = {"‼", "⁉", "〰", "〽"}


def _is_regional_indicator(character: str) -> bool:
    return "\U0001F1E6" <= character <= "\U0001F1FF"


def _is_emoji_base(character: str) -> bool:
    if character in punctuation_emojis:
        return True
    if character.isascii():
        # Only the start of a keycap such as 1️⃣, and _count_unicode_emojis checks the keycap follows
        return character in "0123456789#*"
    return unicodedata.category(character) in ("So", "Sm")


def _is_emoji_modifier(character: str) -> bool:
    """Characters that change the emoji before them rather than starting a new one"""
    if character in (zero_width_joiner, keycap):
        return True
    if "\U0001F3FB" <= character <= "\U0001F3FF":  # Skin tones
        return True
    if "\U000E0020" <= character <= "\U000E007F":  # Tags, as in the subdivision flags
        return True
    return unicodedata.category(character) == "Mn"  # Variation selectors


def _count_unicode_emojis(text: str) -> int | None:
    """
    Count the emojis a string is made of, treating a sequence such as a family, a flag or a skin
    tone as the one emoji it displays as
    :param text: The string to count
    :return: The number of emojis, or None when the string holds anything that is not an emoji
    """
    count = 0
    previous = ""
    pending_regional_indicator = False
    for index, character in enumerate(text):
        if _is_emoji_modifier(character):
            if count == 0:
                return None
        elif _is_regional_indicator(character):
            # A flag is two of these, so only every other one starts a new emoji
            if not pending_regional_indicator and previous != zero_width_joiner:
                count += 1
            pending_regional_indicator = not pending_regional_indicator
        elif _is_emoji_base(character):
            if character.isascii() and keycap not in text[index + 1:index + 3]:
                return None
            if previous != zero_width_joiner:
                count += 1
            pending_regional_indicator = False
        else:
            return None
        previous = character
    return count


def parse_emoji(raw: str, guild_emojis=()) -> tuple[str | None, str | None]:
    """
    Turn what a member typed into the form a reaction on a message is compared against
    :param raw: The text from the command
    :param guild_emojis: The server's own custom emojis, so that :name: can be looked up
    :return: The emoji and None, or None and the reason it was not accepted
    """
    text = (raw or "").strip()
    if not text:
        return None, "No emoji was given."

    match = custom_emoji_pattern.match(text)
    if match is not None:
        animated, name, emoji_id = match.groups()
        return f"<{animated}:{name}:{emoji_id}>", None

    # The client only turns :name: into a custom emoji when the member picks it from the list, and
    # typed out by hand it arrives as text. For this server's emojis that is still unambiguous
    name_match = emoji_name_pattern.match(text)
    if name_match is not None:
        name = name_match.group(1)
        for emoji in guild_emojis:
            if emoji.name == name:
                return str(emoji), None
        return None, (f"`{text}` is not an emoji in this server. Pick the emoji from the emoji "
                      f"list instead of typing its name.")

    count = _count_unicode_emojis(text)
    if count is None or count == 0:
        return None, f"`{text}` is not an emoji. Send a single emoji, like 🔥 or a custom one from this server."
    if count > 1:
        return None, "Only one emoji can be added at a time. Run the command again for each one."
    return text, None


def custom_emoji_id(emoji: str) -> str | None:
    """
    :param emoji: An emoji as stored in the whitelist
    :return: Its ID when it is a custom emoji, which survives the emoji being renamed
    """
    match = custom_emoji_pattern.match(emoji or "")
    return match.group(3) if match is not None else None


def find_in_whitelist(whitelist, raw: str, guild_emojis=()) -> str | None:
    """
    Find the whitelist entry a member means, for taking it off the list
    :param whitelist: The server's whitelist
    :param raw: The text from the command
    :param guild_emojis: The server's own custom emojis
    :return: The entry exactly as stored, or None when it is not on the list
    """
    text = (raw or "").strip()
    # Exact first, so an entry that would not pass validation today can still be removed
    if text in whitelist:
        return text

    emoji, _ = parse_emoji(text, guild_emojis)
    if emoji is None:
        return None
    if emoji in whitelist:
        return emoji

    emoji_id = custom_emoji_id(emoji)
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
