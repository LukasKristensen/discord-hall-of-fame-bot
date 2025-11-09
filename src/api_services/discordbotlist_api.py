import requests
import os
from dotenv import load_dotenv

load_dotenv()
auth_key = os.getenv('DISCORD_BOT_LIST_API_KEY')


def post_command_list():
    """
    Post the list of commands to discordbotlist.com
    :return: Response status code and JSON response
    """
    url = "https://discordbotlist.com/api/v1/bots/1177041673352663070/commands"
    headers = {
        "Content-Type": "application/json",
        "Authorization": auth_key
    }
    payload = [
        {
            "name": "help",
            "description": "List of commands",
            "type": 1
        },
        {
            "name": "set_reaction_threshold",
            "description": "Set the amount of reactions needed for a post to reach hall of fame",
            "type": 1
        },
        {
            "name": "include_authors_reaction",
            "description": "Should the author of a message be included in the reaction count?",
            "type": 1
        },
        {
            "name": "allow_messages_in_hof_channel",
            "description": "Allow anyone to type in the Hall of Fame channel",
            "type": 1
        },
        {
            "name": "custom_emoji_check_logic",
            "description": "Use only whitelisted emojis for the reaction count",
            "type": 1
        },
        {
            "name": "whitelist_emoji",
            "description": "Add a whitelisted emoji to the list [custom_emoji_check_logic]",
            "type": 1
        },
        {
            "name": "unwhitelist_emoji",
            "description": "Remove a whitelisted emoji from the list [custom_emoji_check_logic]",
            "type": 1
        },
        {
            "name": "clear_whitelist",
            "description": "Clear the whitelist of emojis [custom_emoji_check_logic]",
            "type": 1
        },
        {
            "name": "get_server_config",
            "description": "Get the current bot configuration for the server",
            "type": 1
        },
        {
            "name": "ignore_bot_messages",
            "description": "Should the bot ignore messages from other bots?",
            "type": 1
        },
        {
            "name": "hide_hof_post_below_threshold",
            "description": "Should hall of fame posts be hidden when they go below the reaction threshold?",
            "type": 1
        },
        {
            "name": "calculation_method",
            "description": "Change the calculation method for reactions",
            "type": 1
        },
        {
            "name": "user_profile",
            "description": "Get the Hall of Fame profile for a user",
            "type": 1
        },
        {
            "name": "feedback",
            "description": "Got a feature request or bug report? Let us know!",
            "type": 1
        }
    ]

    req_response = requests.post(url, headers=headers, json=payload)
    try:
        return req_response.status_code, req_response.json()
    except requests.exceptions.JSONDecodeError:
        return req_response.status_code, {"error": "Invalid JSON response from server"}


def post_bot_stats(server_count: int):
    """
    Post the bot stats to discordbotlist.com
    :param server_count:
    :return:
    """

    url = "https://discordbotlist.com/api/v1/bots/1177041673352663070/stats"
    headers = {
        "Content-Type": "application/json",
        "Authorization": auth_key
    }
    payload = {
        "guilds": server_count
    }

    req_response = requests.post(url, headers=headers, json=payload)
    try:
        return req_response.status_code, req_response.json()
    except requests.exceptions.JSONDecodeError:
        return req_response.status_code, {"error": "Invalid JSON response from server"}


if __name__ == "__main__":
    status_code, response = post_command_list()
    print(f"Status Code: {status_code}")
    print(f"Response: {response}")
