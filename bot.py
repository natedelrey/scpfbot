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
    print("Error: Missing required channel IDs.")
    exit()

GAME_LINK = os.getenv("GAME_LINK", "https://www.roblox.com/games/17371095768/SCP-Lambda")

# ===================== ROBLOX CONFIG =====================
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")
ROBLOX_GROUP_ID = int(os.getenv("ROBLOX_GROUP_ID"))

ROBLOX_HEADERS = {
    "Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}",
    "Content-Type": "application/json",
    "User-Agent": "SCPFbot",
}

# ===================== DISCORD ROLES =====================
EP_AND_ABOVE_ROLES = [
    "1233139781823627473",
    "1246963191699734569",
    "1233139781840670742",
    "1233139781840670743",
    "1233139781840670746",
]

DD_AND_ABOVE_ROLES = [
    "1246963191699734569",
    "1233139781840670742",
    "1233139781840670743",
    "1233139781840670746",
]

NOTIFY_AND_APP_ROLES = EP_AND_ABOVE_ROLES + ["1234517225206059019"]

DISCORD_RANK_LIMITS = {
    "1233139781823627473": 3,    # L4 -> L3
    "1246963191699734569": 4,    # L5 -> L4
    "1233139781840670743": 5,    # O5 -> L5
    "1233139781840670746": 255,  # O5 Head
    "1233139781840670749": 999,  # Administrator
}

# ===================== BOT SETUP =====================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ===================== PERMISSION CHECK =====================
def has_any_role(required_roles: List[str]):
    async def predicate(interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            return False
        return any(str(role.id) in required_roles for role in interaction.user.roles)
    return app_commands.check(predicate)

# ===================== HELPER FUNCTIONS =====================
def get_max_allowed_rank(member: discord.Member) -> int:
    return max((DISCORD_RANK_LIMITS.get(str(r.id), 0) for r in member.roles), default=0)

def resolve_roblox_user(target: str):
    if target.isdigit():
        r = requests.get(f"https://users.roblox.com/v1/users/{target}")
        if r.status_code != 200:
            raise ValueError("Invalid Roblox user ID.")
        return int(target), r.json()["name"]

    r = requests.post(
        "https://users.roblox.com/v1/usernames/users",
        json={"usernames": [target], "excludeBannedUsers": False},
    )
    data = r.json().get("data")
    if not data:
        raise ValueError("Roblox username not found.")
    return data[0]["id"], data[0]["name"]

def get_current_rank(user_id: int) -> int:
    r = requests.get(f"https://groups.roblox.com/v1/users/{user_id}/groups/roles")
    for g in r.json().get("data", []):
        if g["group"]["id"] == ROBLOX_GROUP_ID:
            return g["role"]["rank"]
    return 0

def get_role_id_for_rank(rank_number: int) -> int:
    r = requests.get(f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/roles")
    for role in r.json().get("roles", []):
        if role["rank"] == rank_number:
            return role["id"]
    raise ValueError("That rank does not exist in the group.")

# ===================== EVENTS =====================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.tree.sync()

# ===================== /RANK COMMAND =====================
ROBLOX_RANKS = {
    "Level 1 (Rank 1)": 1,
    "Level 2 (Rank 2)": 2,
    "Level 3 (Rank 3)": 3,
    "Level 4 (Rank 4)": 4,
    "Level 5 (Rank 5)": 5,
    "O5 Council (Rank 250)": 250,
    "O5 Head (Rank 255)": 255,
}

RANK_CHOICES = [
    app_commands.Choice(name=name, value=rank)
    for name, rank in ROBLOX_RANKS.items()
]

@bot.tree.command(name="rank", description="Rank a Roblox user in the group.")
@has_any_role(list(DISCORD_RANK_LIMITS.keys()))
@app_commands.choices(rank=RANK_CHOICES)
@app_commands.describe(
    target="Roblox username or user ID",
    rank="Rank to assign",
    reason="Reason for this action",
)
async def rank(
    interaction: discord.Interaction,
    target: str,
    rank: app_commands.Choice[int],
    reason: str,
):
    log_channel = bot.get_channel(RANK_LOG_CHANNEL_ID)
    max_allowed = get_max_allowed_rank(interaction.user)

    try:
        user_id, username = resolve_roblox_user(target)
        old_rank = get_current_rank(user_id)

        if rank.value > max_allowed:
            raise PermissionError(f"You may only rank up to Rank {max_allowed}.")

        role_id = get_role_id_for_rank(rank.value)

        r = requests.patch(
            f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/users/{user_id}",
            headers=ROBLOX_HEADERS,
            json={"roleId": role_id},
        )

        if r.status_code != 200:
            raise RuntimeError("Roblox API rejected the rank request.")

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
        timestamp=datetime.now(UTC),
    )
    embed.add_field(name="Staff", value=interaction.user.mention, inline=False)
    embed.add_field(name="Target", value=target, inline=False)
    embed.add_field(
        name="Old → New",
        value=f"{old_rank if 'old_rank' in locals() else 'N/A'} → {rank.value}",
        inline=False,
    )
    embed.add_field(name="Result", value=result, inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)

    if log_channel:
        await log_channel.send(embed=embed)

    await interaction.response.send_message(response, ephemeral=True)

# ===================== RUN =====================
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN not set.")
    else:
        bot.run(BOT_TOKEN)
