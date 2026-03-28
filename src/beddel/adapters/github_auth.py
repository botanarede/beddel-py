"""Credential storage for GitHub OAuth Device Flow.

Manages reading, writing, and deleting locally-stored GitHub OAuth
credentials at an XDG-compliant path (``~/.config/beddel/credentials.json``).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, TypedDict

import httpx

from beddel.domain.errors import BeddelError
from beddel.error_codes import (
    AUTH_CREDENTIALS_FILE_ERROR,
    AUTH_DEVICE_FLOW_FAILED,
    AUTH_DEVICE_FLOW_TIMEOUT,
    AUTH_TOKEN_EXCHANGE_FAILED,
)

CREDENTIALS_PATH: Path = Path("~/.config/beddel/credentials.json").expanduser()

GITHUB_DEVICE_CODE_URL: str = "https://github.com/login/device/code"
GITHUB_TOKEN_URL: str = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL: str = "https://api.github.com/user"


class CredentialData(TypedDict):
    """Shape of the persisted credential JSON."""

    access_token: str
    github_user: str
    server_url: str | None
    created_at: str


def save_credentials(data: CredentialData) -> None:
    """Persist credentials to disk with ``0o600`` permissions.

    Creates parent directories if they do not exist.

    Raises:
        BeddelError: If the file cannot be written
            (code ``AUTH_CREDENTIALS_FILE_ERROR``).
    """
    try:
        CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
        CREDENTIALS_PATH.write_text(json.dumps(dict(data), indent=2))
        CREDENTIALS_PATH.chmod(0o600)
    except OSError as exc:
        raise BeddelError(
            code=AUTH_CREDENTIALS_FILE_ERROR,
            message=f"Cannot write credentials file: {exc}",
        ) from exc


def load_credentials() -> CredentialData | None:
    """Load credentials from disk.

    Returns:
        Parsed credential data, or ``None`` if the file does not exist.

    Raises:
        BeddelError: On JSON parse errors or permission problems
            (code ``AUTH_CREDENTIALS_FILE_ERROR``).
    """
    if not CREDENTIALS_PATH.exists():
        return None
    try:
        raw = CREDENTIALS_PATH.read_text()
        result: CredentialData = json.loads(raw)
        return result
    except (json.JSONDecodeError, OSError) as exc:
        raise BeddelError(
            code=AUTH_CREDENTIALS_FILE_ERROR,
            message=f"Cannot read credentials file: {exc}",
        ) from exc


def delete_credentials() -> bool:
    """Remove the credentials file.

    Returns:
        ``True`` if the file was deleted, ``False`` if it did not exist.
    """
    if not CREDENTIALS_PATH.exists():
        return False
    CREDENTIALS_PATH.unlink()
    return True


async def initiate_device_flow(client_id: str) -> dict[str, Any]:
    """Initiate GitHub OAuth Device Flow (RFC 8628).

    POSTs to the GitHub device code endpoint with the given ``client_id``
    and ``scope=read:user``.

    Returns:
        Response dict containing ``device_code``, ``user_code``,
        ``verification_uri``, ``expires_in``, and ``interval``.

    Raises:
        BeddelError: On non-200 response (code ``AUTH_DEVICE_FLOW_FAILED``).
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GITHUB_DEVICE_CODE_URL,
            data={"client_id": client_id, "scope": "read:user"},
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise BeddelError(
                code=AUTH_DEVICE_FLOW_FAILED,
                message=f"GitHub returned {resp.status_code}",
            )
        result: dict[str, Any] = resp.json()
        return result


async def poll_for_token(
    client_id: str,
    device_code: str,
    interval: int,
    expires_in: int,
) -> str:
    """Poll GitHub for an access token after device flow initiation.

    Polls every ``interval`` seconds until the user completes browser
    auth or ``expires_in`` seconds elapse.

    Returns:
        The GitHub access token string.

    Raises:
        BeddelError: ``AUTH_DEVICE_FLOW_TIMEOUT`` if the token expires,
            ``AUTH_TOKEN_EXCHANGE_FAILED`` if access is denied.
    """
    poll_interval = interval
    elapsed = 0

    while elapsed < expires_in:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GITHUB_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
            )

        body: dict[str, Any] = resp.json()
        error = body.get("error")

        if error is None and "access_token" in body:
            return body["access_token"]

        if error == "authorization_pending":
            continue
        if error == "slow_down":
            poll_interval += 5
            continue
        if error == "expired_token":
            raise BeddelError(
                code=AUTH_DEVICE_FLOW_TIMEOUT,
                message="User did not complete browser auth in time",
            )
        if error == "access_denied":
            raise BeddelError(
                code=AUTH_TOKEN_EXCHANGE_FAILED,
                message="User denied the authorization request",
            )

    raise BeddelError(
        code=AUTH_DEVICE_FLOW_TIMEOUT,
        message="Device flow expired before user completed auth",
    )


async def get_github_user(token: str) -> str:
    """Fetch the authenticated GitHub username.

    Args:
        token: A valid GitHub access token.

    Returns:
        The ``login`` field from the GitHub ``/user`` endpoint.

    Raises:
        BeddelError: On non-200 response (code ``AUTH_TOKEN_EXCHANGE_FAILED``).
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        if resp.status_code != 200:
            raise BeddelError(
                code=AUTH_TOKEN_EXCHANGE_FAILED,
                message=f"GitHub /user returned {resp.status_code}",
            )
        body: dict[str, Any] = resp.json()
        return body["login"]
