import json
from http.client import HTTPSConnection
from urllib.parse import urlparse


def _perform_request(
    method: str,
    host: str,
    path: str,
    payload: str,
    headers: dict[str, str],
) -> tuple[int, str, dict[str, str]]:
    conn = HTTPSConnection(host, 443)
    conn.request(method, path, payload, headers)
    response = conn.getresponse()
    body = response.read().decode("utf-8", errors="replace")
    status = response.status
    response_headers = {key.lower(): value for key, value in response.getheaders()}
    conn.close()
    return status, body, response_headers


def _request_with_redirects(
    method: str,
    host: str,
    path: str,
    payload: str,
    headers: dict[str, str],
) -> tuple[int, str]:
    for _ in range(3):
        status, body, response_headers = _perform_request(
            method,
            host,
            path,
            payload,
            headers,
        )
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


def _build_headers(
    discord_token: str,
    discord_user_id: str,
    server_id: str,
    channel_id: str,
) -> dict[str, str]:
    return {
        "content-type": "application/json",
        "authorization": discord_token,
        "user-id": discord_user_id,
        "host": "discordapp.com",
        "referrer": f"https://discord.com/channels/{server_id}/{channel_id}",
    }


def _format_noah_content(message: str) -> str:
    escaped_message = message.replace("`", "\\`")
    return f"[𝑵𝒐𝒂𝒉] `{escaped_message}`"


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
    headers = _build_headers(
        discord_token,
        discord_user_id,
        server_id,
        channel_id,
    )
    payload = json.dumps({"content": message})
    host = "discordapp.com"
    path = f"/api/v6/channels/{channel_id}/messages"
    status, body = _request_with_redirects("POST", host, path, payload, headers)
    if not 200 <= status < 300:
        return status, body

    try:
        message_data = json.loads(body)
        message_id = message_data["id"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return status, body

    edit_headers = _build_headers(
        discord_token,
        discord_user_id,
        server_id,
        channel_id,
    )
    edit_payload = json.dumps({"content": _format_noah_content(message)})
    edit_path = f"/api/v6/channels/{channel_id}/messages/{message_id}"
    edit_status, edit_body = _request_with_redirects(
        "PATCH",
        "discordapp.com",
        edit_path,
        edit_payload,
        edit_headers,
    )
    if 200 <= edit_status < 300:
        return edit_status, edit_body

    return edit_status, edit_body


def delete_message(
    message_id: str,
    discord_token: str,
    discord_user_id: str,
    server_id: str,
    channel_id: str,
) -> tuple[int, str]:
    headers = _build_headers(
        discord_token,
        discord_user_id,
        server_id,
        channel_id,
    )
    path = f"/api/v6/channels/{channel_id}/messages/{message_id}"
    return _request_with_redirects("DELETE", "discordapp.com", path, "", headers)
