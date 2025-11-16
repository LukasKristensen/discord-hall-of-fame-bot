import base64
import requests
from urllib.parse import urlparse
import os
from dotenv import load_dotenv

dev_test = os.getenv('DEV_TEST') == "True"
load_dotenv()
if dev_test:
    TOKEN = os.getenv('DEV_KEY')
else:
    TOKEN = os.getenv('KEY')


def custom_bot_profile_for_guild(guild_id: str, image_url: str = None, cover_url: str = None):
    encoded_avatar = encode_image_to_base64(image_url) if image_url and is_valid_url(image_url) else None
    encoded_banner = encode_image_to_base64(cover_url) if cover_url and is_valid_url(cover_url) else None
    url = f"https://discord.com/api/v10/guilds/{guild_id}/members/@me"

    payload = {}
    if encoded_avatar:
        payload["avatar"] = encoded_avatar
    if encoded_banner:
        payload["banner"] = encoded_banner

    headers = {
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": "application/json",
        "X-Audit-Log-Reason": "Updating bot profile picture",
    }

    response = requests.patch(url, json=payload, headers=headers)
    if response.status_code == 200:
        print("Bot profile updated successfully.")
    else:
        print(f"Failed to update bot profile. Status code: {response.status_code}, Response: {response.text}")


def encode_image_to_base64(image_url):
    response = requests.get(image_url, stream=True)
    if int(response.headers.get('Content-Length', 0)) > 1_000_000:
        raise Exception("Image size exceeds 1 MB limit.")
    if response.status_code == 200:
        return f"data:image/png;base64,{base64.b64encode(response.content).decode('utf-8')}"
    else:
        raise Exception("Failed to fetch image")


def is_valid_url(url):
    try:
        parsed = urlparse(url)
        return all([parsed.scheme, parsed.netloc])
    except ValueError:
        return False


if __name__ == "__main__":
    guild_id = int(input("Enter the guild ID: "))
    profile_picture_url = input("Enter the avatar image URL (or leave blank): ")
    cover_picture_url = input("Enter the banner image URL (or leave blank): ")

    print(f"\nGuild ID: {guild_id}")
    print(f"Avatar URL: {profile_picture_url if profile_picture_url else 'No change'}")
    print(f"Banner URL: {cover_picture_url if cover_picture_url else 'No change'}")
    confirmed = input("CONFIRM?")
    if not confirmed.lower() == "confirm":
        print("Operation cancelled.")

    custom_bot_profile_for_guild(guild_id, profile_picture_url if profile_picture_url else None, cover_picture_url if cover_picture_url else None)
