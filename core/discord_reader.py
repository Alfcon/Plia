"""
Discord Reader - Reads Discord channel messages via the Discord REST API.

Uses a Discord Bot token (not a user token) to fetch channel history.
No persistent bot process is needed — each read is a one-shot HTTP call.

Setup (one-time):
    1. Go to https://discord.com/developers/applications
    2. Create a New Application → Bot tab → Reset Token → copy the token.
    3. Under "Privileged Gateway Intents" enable "Message Content Intent".
    4. Invite the bot to your server via OAuth2 → URL Generator:
         Scopes:      bot
         Permissions: Read Messages / View Channels
                      Read Message History
    5. Paste the token into Plia Settings → Discord → Bot Token.

Notes:
    - The bot must be a member of any server / channel you want to read.
    - Message Content Intent must be enabled or message bodies will be empty.
    - Max 100 messages per request (Discord API hard limit).
"""

import requests
from typing import Any, Dict, List, Optional

from core.settings_store import settings as app_settings

DISCORD_API = "https://discord.com/api/v10"
REQUEST_TIMEOUT = 10  # seconds


class DiscordReader:
    """
    Thin wrapper around the Discord REST API for reading channel history.
    """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> Optional[Dict[str, str]]:
        """Return auth headers, or None if the token is not configured."""
        token = app_settings.get("discord.bot_token", "").strip()
        if not token:
            return None
        return {
            "Authorization": f"Bot {token}",
            "Content-Type":  "application/json",
        }

    def _get(self, path: str, params: Dict = None) -> Any:
        """GET from the Discord API. Raises requests.HTTPError on failure."""
        hdrs = self._headers()
        if not hdrs:
            raise ValueError(
                "Discord bot token not configured. "
                "Please add your bot token in Plia Settings → Discord."
            )
        r = requests.get(
            f"{DISCORD_API}{path}",
            headers=hdrs,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Discovery helpers
    # ------------------------------------------------------------------

    def list_guilds(self) -> List[Dict]:
        """Return all guilds (servers) the bot belongs to."""
        return self._get("/users/@me/guilds")

    def list_channels(self, guild_id: str) -> List[Dict]:
        """Return all channels in a guild."""
        return self._get(f"/guilds/{guild_id}/channels")

    def find_channel(
        self,
        channel_name: str,
        guild_name: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Locate a text channel by name (fuzzy, case-insensitive).

        Args:
            channel_name: e.g. "general", "#announcements"
            guild_name:   Optional server name to narrow the search.

        Returns:
            {"channel": <channel_obj>, "guild": <guild_obj>} or None.
        """
        guilds = self.list_guilds()
        if not guilds:
            return None

        # Optionally filter by server name
        if guild_name:
            guilds = [g for g in guilds if guild_name.lower() in g["name"].lower()]
            if not guilds:
                return None

        target = channel_name.lower().lstrip("#").strip()

        for guild in guilds:
            try:
                channels = self.list_channels(guild["id"])
            except Exception:
                continue

            for ch in channels:
                # type 0 = GUILD_TEXT
                if ch.get("type") == 0 and target in ch["name"].lower():
                    return {"channel": ch, "guild": guild}

        return None

    # ------------------------------------------------------------------
    # Message fetching
    # ------------------------------------------------------------------

    def fetch_messages(self, channel_id: str, limit: int = 50) -> List[Dict]:
        """
        Return up to `limit` recent messages from a channel (newest first
        as returned by Discord; caller can reverse for chronological order).
        """
        limit = max(1, min(limit, 100))  # Discord hard cap is 100
        return self._get(f"/channels/{channel_id}/messages", {"limit": limit})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read_channel(
        self,
        channel_name: str,
        limit: int = 50,
        guild_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Read recent messages from a named Discord channel.

        Args:
            channel_name: Plain name or #name, e.g. "general".
            limit:        How many messages to fetch (1–100).
            guild_name:   Optional server name filter.

        Returns:
            Standard Plia result dict with "data" containing:
                channel      - channel name
                guild        - server name
                message_count
                messages     - newline-joined "[timestamp] author: content"
                raw          - list of formatted strings
        """
        hdrs = self._headers()
        if not hdrs:
            return {
                "success": False,
                "message": (
                    "Discord bot token not configured. "
                    "Please add your bot token in Plia Settings → Discord."
                ),
                "data": None,
            }

        try:
            found = self.find_channel(channel_name, guild_name)
            if not found:
                hint = f" in '{guild_name}'" if guild_name else ""
                return {
                    "success": False,
                    "message": f"Channel '#{channel_name}'{hint} not found. "
                               f"Make sure the bot has been invited to that server.",
                    "data": None,
                }

            ch    = found["channel"]
            guild = found["guild"]

            raw_messages = self.fetch_messages(ch["id"], limit)

            # Format oldest-first for readability
            formatted: List[str] = []
            for msg in reversed(raw_messages):
                author  = msg.get("author", {}).get("username", "Unknown")
                content = msg.get("content", "").strip()
                ts      = msg.get("timestamp", "")[:16].replace("T", " ")
                # Skip empty messages (e.g. embed-only posts)
                if content:
                    formatted.append(f"[{ts}] {author}: {content}")

            messages_text = "\n".join(formatted)

            return {
                "success": True,
                "message": (
                    f"Read {len(formatted)} messages from "
                    f"#{ch['name']} in {guild['name']}"
                ),
                "data": {
                    "channel":       ch["name"],
                    "guild":         guild["name"],
                    "message_count": len(formatted),
                    "messages":      messages_text,
                    "raw":           formatted,
                },
            }

        except ValueError as e:
            # Token not configured
            return {"success": False, "message": str(e), "data": None}

        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            if status == 401:
                msg = "Invalid Discord bot token — please check your token in Settings."
            elif status == 403:
                msg = (
                    "Bot lacks permission to read that channel. "
                    "Ensure it has 'Read Message History' permission."
                )
            elif status == 404:
                msg = "Channel or server not found."
            else:
                msg = f"Discord API error (HTTP {status}): {e}"
            return {"success": False, "message": msg, "data": None}

        except Exception as e:
            print(f"[DiscordReader] Unexpected error: {e}")
            return {"success": False, "message": f"Discord reader error: {e}", "data": None}

    def list_available_channels(self, guild_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Return a list of all text channels the bot can see.
        Useful for helping the user discover channel names.
        """
        hdrs = self._headers()
        if not hdrs:
            return {"success": False, "message": "Bot token not configured.", "data": None}

        try:
            guilds = self.list_guilds()
            if guild_name:
                guilds = [g for g in guilds if guild_name.lower() in g["name"].lower()]

            all_channels: List[Dict] = []
            for guild in guilds:
                try:
                    channels = self.list_channels(guild["id"])
                    for ch in channels:
                        if ch.get("type") == 0:
                            all_channels.append({
                                "guild":   guild["name"],
                                "channel": ch["name"],
                            })
                except Exception:
                    continue

            if not all_channels:
                return {"success": False, "message": "No text channels found.", "data": None}

            summary = "\n".join(
                f"  {r['guild']} → #{r['channel']}" for r in all_channels
            )
            return {
                "success": True,
                "message": f"Found {len(all_channels)} channels",
                "data":    {"channels": all_channels, "summary": summary},
            }

        except Exception as e:
            return {"success": False, "message": f"Error listing channels: {e}", "data": None}


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
discord_reader = DiscordReader()
