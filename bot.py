import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, UTC
import os
from dotenv import load_dotenv
from typing import List
import re
import requests

# ===================== CONFIGURATION =====================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

try:
    ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID"))
    SSU_CHANNEL_ID = int(os.getenv("SSU_CHANNEL_ID"))
    APPLICATION_RESULTS_CHANNEL_ID = int(os.getenv("APPLICATION_RESULTS_CHANNEL_ID"))
    RANK_LOG_CHANNEL_ID = int(os.getenv("RANK_LOG_CHANNEL_ID"))
except (TypeError, ValueError):
    print("Missing required channel IDs in .env")
    exit()

GAME_LINK = os.getenv("GAME_LINK", "https://www.roblox.com/games/17371095768/SCP-Lambda")

# ===================== ROBLOX CONFIG =====================
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")
ROBLOX_GROUP_ID = int(os.getenv("ROBLOX_GROUP_ID"))

ROBLOX_HEADERS = {
    "Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}",
    "Content-Type": "application/json",
    "User-Agent": "SCPFbot"
}

# ===================== DISCORD ROLES =====================
EP_AND_ABOVE_ROLES = [
    "1233139781823627473", "1246963191699734569",
    "1233139781840670742", "1233139781840670743",
    "1233139781840670746"
]

DD_AND_ABOVE_ROLES = [
    "1246963191699734569", "1233139781840670742",
    "1233139781840670743", "1233139781840670746"
]

NOTIFY_AND_APP_ROLES = EP_AND_ABOVE_ROLES + ["1234517225206059019"]

# Discord role → max Roblox roleId
DISCORD_RANK_LIMITS = {
    "1233139781823627473": 5,   # Level 4 → Level 3
    "1246963191699734569": 6,   # Level 5 → Level 4
    "1233139781840670743": 7,   # O5 → Level 5
    "1233139781840670746": 9,   # O5 Head → O5 Council
    "1233139781840670749": 255, # Administrator → unrestricted
}

# ===================== ROBLOX ROLE IDS =====================
ROBLOX_ROLES = {
    "Class - D": 1,
    "Class - E": 2,
    "Level - 1": 3,
    "Level - 2": 4,
    "Level - 3": 5,
    "Level - 4": 6,
    "Level - 5": 7,
    "O5 Council": 9,
    "O5 Head": 10,
    "Administrator": 11,
    "Group Holder": 255,
}

RANK_CHOICES = [
    app_commands.Choice(name=f"{name} (ID {rid})", value=rid)
    for name, rid in ROBLOX_ROLES.items()
]

# ===================== BOT SETUP =====================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ===================== PERMISSION CHECK =====================
def has_any_role(required_roles: List[str]):
    async def predicate(interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            return False
        return any(str(r.id) in required_roles for r in interaction.user.roles)
    return app_commands.check(predicate)

# ===================== HELPERS =====================
def get_max_allowed_role(member: discord.Member) -> int:
    return max((DISCORD_RANK_LIMITS.get(str(r.id), 0) for r in member.roles), default=0)

def resolve_roblox_user(target: str):
    if target.isdigit():
        r = requests.get(f"https://users.roblox.com/v1/users/{target}")
        if r.status_code != 200:
            raise ValueError("Invalid Roblox user ID.")
        return int(target), r.json()["name"]

    r = requests.post(
        "https://users.roblox.com/v1/usernames/users",
        json={"usernames": [target], "excludeBannedUsers": False}
    )
    data = r.json().get("data")
    if not data:
        raise ValueError("Roblox username not found.")
    return data[0]["id"], data[0]["name"]

def get_current_role(user_id: int):
    r = requests.get(f"https://groups.roblox.com/v1/users/{user_id}/groups/roles")
    for g in r.json().get("data", []):
        if g["group"]["id"] == ROBLOX_GROUP_ID:
            return g["role"]["name"], g["role"]["id"]
    return "Not in group", 0

# ===================== EVENTS =====================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.tree.sync()

# ===================== /RANK COMMAND =====================
@bot.tree.command(name="rank", description="Rank a Roblox user in the group.")
@has_any_role(list(DISCORD_RANK_LIMITS.keys()))
@app_commands.choices(rank=RANK_CHOICES)
@app_commands.describe(
    target="Roblox username or user ID",
    rank="Rank to assign",
    reason="Reason (required)"
)
async def rank(
    interaction: discord.Interaction,
    target: str,
    rank: app_commands.Choice[int],
    reason: str
):
    log_channel = bot.get_channel(RANK_LOG_CHANNEL_ID)
    max_allowed = get_max_allowed_role(interaction.user)

    try:
        user_id, username = resolve_roblox_user(target)
        old_role_name, old_role_id = get_current_role(user_id)

        if rank.value > max_allowed:
            raise PermissionError("You are not authorized to assign that rank.")

        r = requests.patch(
            f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/users/{user_id}",
            headers=ROBLOX_HEADERS,
            json={"roleId": rank.value}
        )

        if r.status_code != 200:
            raise RuntimeError(r.text)

        result = "✅ Success"
        color = discord.Color.green()
        response = f"Successfully ranked **{username}**."

    except Exception as e:
        result = "❌ Failed"
        color = discord.Color.red()
        response = str(e)

    embed = discord.Embed(
        title="Roblox Rank Log",
        color=color,
        timestamp=datetime.now(UTC)
    )
    embed.add_field(name="Staff", value=interaction.user.mention, inline=False)
    embed.add_field(name="Target", value=username if 'username' in locals() else target, inline=False)
    embed.add_field(name="Old → New", value=f"{old_role_name} → {rank.name}", inline=False)
    embed.add_field(name="Result", value=result, inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)

    if log_channel:
        await log_channel.send(embed=embed)

    await interaction.response.send_message(response, ephemeral=True)

# ===================== RUN =====================
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("BOT_TOKEN missing.")
    else:
        bot.run(BOT_TOKEN)
