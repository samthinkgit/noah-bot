import json
from http.client import HTTPSConnection
from urllib.parse import urlparse


def _perform_request(
    host: str,
    path: str,
    payload: str,
    headers: dict[str, str],
) -> tuple[int, str, dict[str, str]]:
    conn = HTTPSConnection(host, 443)
    conn.request("POST", path, payload, headers)
    response = conn.getresponse()
    body = response.read().decode("utf-8", errors="replace")
    status = response.status
    response_headers = {key.lower(): value for key, value in response.getheaders()}
    conn.close()
    return status, body, response_headers


def send_message(
    message: str,
    discord_token: str,
    discord_user_id: str,
    server_id: str,
    channel_id: str,
) -> tuple[int, str]:
    """
    Sends a message to a specified Discord channel using the Discord API.
    Args:
        message (str): The message content to send.
        discord_token (str): The Discord authorization token.
        discord_user_id (str): The Discord user ID.
        server_id (str): The ID of the Discord server (guild).
        channel_id (str): The ID of the Discord channel.
    """
    headers = {
        "content-type": "application/json",
        "authorization": discord_token,
        "user-id": discord_user_id,
        "host": "discordapp.com",
        "referrer": f"https://discord.com/channels/{server_id}/{channel_id}",
    }

    payload = json.dumps({"content": message})

    host = "discordapp.com"
    path = f"/api/v6/channels/{channel_id}/messages"

    for _ in range(3):
        status, body, response_headers = _perform_request(host, path, payload, headers)
        location = response_headers.get("location")
        if status not in {301, 302, 307, 308} or not location:
            return status, body

        redirected = urlparse(location)
        host = redirected.netloc or host
        path = redirected.path or path
        if redirected.query:
            path = f"{path}?{redirected.query}"
        headers["host"] = host

    return status, body
