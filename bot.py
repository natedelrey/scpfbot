import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, UTC
import os
from dotenv import load_dotenv
from typing import List
import re
import requests

# ===================== CONFIG =====================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID"))
SSU_CHANNEL_ID = int(os.getenv("SSU_CHANNEL_ID"))
APPLICATION_RESULTS_CHANNEL_ID = int(os.getenv("APPLICATION_RESULTS_CHANNEL_ID"))
RANK_LOG_CHANNEL_ID = int(os.getenv("RANK_LOG_CHANNEL_ID"))

GAME_LINK = os.getenv("GAME_LINK")

ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")
ROBLOX_GROUP_ID = int(os.getenv("ROBLOX_GROUP_ID"))

ROBLOX_HEADERS = {
    "Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}",
    "Content-Type": "application/json",
    "User-Agent": "SCPFbot",
}

# ===================== DISCORD ROLE LIMITS =====================
DISCORD_RANK_LIMITS = {
    "1233139781823627473": 3,    # L4 → Level-3
    "1246963191699734569": 4,    # L5 → Level-4
    "1233139781840670743": 5,    # O5 → Level-5
    "1233139781840670746": 9,    # O5 Head → O5 Council
    "1233139781840670749": 999,  # Administrator
}

# ===================== ROBLOX ROLE NAMES =====================
ROBLOX_ROLE_NAMES = {
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
    app_commands.Choice(name=f"{name}", value=name)
    for name in ROBLOX_ROLE_NAMES.keys()
]

# ===================== BOT =====================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ===================== PERMS =====================
def has_any_role(required_roles: List[str]):
    async def predicate(interaction: discord.Interaction):
        return any(str(r.id) in required_roles for r in interaction.user.roles)
    return app_commands.check(predicate)

# ===================== ROBLOX REQUEST =====================
def roblox_request(method, url, json=None):
    headers = ROBLOX_HEADERS.copy()
    r = requests.request(method, url, headers=headers, json=json)

    if r.status_code == 403 and "X-CSRF-TOKEN" in r.headers:
        headers["X-CSRF-TOKEN"] = r.headers["X-CSRF-TOKEN"]
        r = requests.request(method, url, headers=headers, json=json)

    return r

# ===================== HELPERS =====================
def get_max_allowed(member: discord.Member) -> int:
    return max((DISCORD_RANK_LIMITS.get(str(r.id), 0) for r in member.roles), default=0)

def resolve_roblox_user(target: str):
    if target.isdigit():
        r = requests.get(f"https://users.roblox.com/v1/users/{target}")
        return int(target), r.json()["name"]

    r = requests.post(
        "https://users.roblox.com/v1/usernames/users",
        json={"usernames": [target], "excludeBannedUsers": False}
    )
    data = r.json()["data"][0]
    return data["id"], data["name"]

def get_group_roles():
    r = requests.get(f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/roles")
    return r.json()["roles"]

def get_role_id_by_name(role_name: str) -> int:
    for role in get_group_roles():
        if role["name"].lower() == role_name.lower():
            return role["id"]
    raise ValueError("That role does not exist in the Roblox group.")

def get_current_role(user_id: int):
    r = requests.get(f"https://groups.roblox.com/v1/users/{user_id}/groups/roles")
    for g in r.json()["data"]:
        if g["group"]["id"] == ROBLOX_GROUP_ID:
            return g["role"]["name"]
    return "Not in group"

# ===================== EVENTS =====================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.tree.sync()

# ===================== /RANK =====================
@bot.tree.command(name="rank", description="Rank a Roblox user.")
@has_any_role(list(DISCORD_RANK_LIMITS.keys()))
@app_commands.choices(rank=RANK_CHOICES)
async def rank(
    interaction: discord.Interaction,
    target: str,
    rank: app_commands.Choice[str],
    reason: str
):
    log_channel = bot.get_channel(RANK_LOG_CHANNEL_ID)
    max_allowed = get_max_allowed(interaction.user)

    try:
        user_id, username = resolve_roblox_user(target)
        old_role = get_current_role(user_id)

        intended_rank_value = ROBLOX_ROLE_NAMES[rank.value]
        if intended_rank_value > max_allowed:
            raise PermissionError("You cannot assign that rank.")

        role_id = get_role_id_by_name(rank.value)

        r = roblox_request(
            "PATCH",
            f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/users/{user_id}",
            json={"roleId": role_id}
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
    embed.add_field(name="Old → New", value=f"{old_role} → {rank.value}", inline=False)
    embed.add_field(name="Result", value=result, inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)

    if log_channel:
        await log_channel.send(embed=embed)

    await interaction.response.send_message(response, ephemeral=True)

# ===================== RUN =====================
if __name__ == "__main__":
    bot.run(BOT_TOKEN)
