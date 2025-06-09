import requests
import os
from dotenv import load_dotenv

load_dotenv()
auth_key = os.getenv('TOPGG_API_KEY')


def get_top_1000_votes(api_key: str):
    """
    Get the top 1000 votes for the bot
    :param api_key:
    :return:
    """
    url = "https://top.gg/api/bots/1177041673352663070/votes"
    headers = {
        "Content-Type": "application/json",
        "Authorization": api_key
    }
    response = requests.get(url, headers=headers)
    return response.json()


def post_bot_stats(server_count: int, api_key: str, shards=None, shard_id=None, shard_count=None):
    """
    Post the bot stats to top.gg
    :param server_count:
    :param api_key:
    :param shards:
    :param shard_id:
    :param shard_count:
    :return:
    """
    url = "https://top.gg/api/bots/1177041673352663070/stats"
    headers = {
        "Content-Type": "application/json",
        "Authorization": api_key
    }
    payload = {
        "server_count": server_count
    }
    if shards is not None:
        payload["shards"] = shards
    if shard_id is not None:
        payload["shard_id"] = shard_id
    if shard_count is not None:
        payload["shard_count"] = shard_count

    response = requests.post(url, headers=headers, json=payload)
    try:
        return response.status_code, response.json()
    except requests.exceptions.JSONDecodeError:
        return response.status_code, {"error": "Invalid JSON response from server"}


def get_user_vote(api_key: str, user_id: int):
    """
    Check if a user has voted for the bot
    :param api_key:
    :param user_id:
    :return:
    """
    url = "https://top.gg/api/bots/:1177041673352663070/check"
    headers = {
        "Content-Type": "application/json",
        "Authorization": api_key
    }
    # add parameter for user_id
    payload = {
        "userId": user_id
    }
    response = requests.get(url, headers=headers, params=payload)
    return response.json()


if __name__ == "__main__":
    print(get_top_1000_votes(auth_key))
    print(get_user_vote(auth_key, 230698327589650432))
