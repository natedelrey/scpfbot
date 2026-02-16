import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, UTC, timedelta
import os
import json
import textwrap
from dotenv import load_dotenv
from typing import List
import re
import requests
import time
import asyncio

# --- CONFIGURATION ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

try:
    ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID"))
    SSU_CHANNEL_ID = int(os.getenv("SSU_CHANNEL_ID"))
    APPLICATION_RESULTS_CHANNEL_ID = int(os.getenv("APPLICATION_RESULTS_CHANNEL_ID", "1471960884997001227"))
    RANK_LOG_CHANNEL_ID = int(os.getenv("RANK_LOG_CHANNEL_ID"))
    ROBLOX_GROUP_ID = int(os.getenv("ROBLOX_GROUP_ID"))
except (TypeError, ValueError):
    print("Error: A required Channel ID (or ROBLOX_GROUP_ID) is not set correctly in your environment variables.")
    exit()

GAME_LINK = os.getenv("GAME_LINK", "https://www.roblox.com/games/17371095768/SCP-Lambda")

# --- MOTION SYSTEM CONFIG (HARDCODED AS REQUESTED) ---
BOARD_ROLE_ID = 1246963191699734569
O5_ROLE_ID = 1233139781840670743
COUNCIL_CHAIRMAN_ROLE_ID = 1233139781840670746
ADMINISTRATOR_ROLE_ID = 1233139781840670749

BOARD_MOTIONS_CHANNEL_ID = 1471329253093150885
O5_MOTIONS_CHANNEL_ID = 1471329476003627038
MOTION_UPDATES_CHANNEL_ID = 1471960962805403648

MOTION_STATE_FILE = "motions_state.json"
MOTION_VOTE_OPTIONS = ("approve", "reject", "abstain")

MOTION_EMOJIS = {
    "approve": {
        "text": "<:checkmark:1471958216744374354>",
        "button": discord.PartialEmoji(name="checkmark", id=1471958216744374354),
    },
    "reject": {
        "text": "<:cross:1471957648088895488>",
        "button": discord.PartialEmoji(name="cross", id=1471957648088895488),
    },
    "abstain": {
        "text": "<:neutral:1471957837944197303>",
        "button": discord.PartialEmoji(name="neutral", id=1471957837944197303),
    },
}

# --- ROBLOX CONFIG ---
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")
ROBLOX_HEADERS_BASE = {
    "Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}",
    "Content-Type": "application/json",
    "User-Agent": "SCPFbot",
}

# --- ROLE IDs FOR PERMISSIONS ---
EP_AND_ABOVE_ROLES = [
    "1233139781823627473", "1246963191699734569", "1233139781840670742",
    "1233139781840670743", "1233139781840670746"
]
DD_AND_ABOVE_ROLES = [
    "1246963191699734569", "1233139781840670742", "1233139781840670743",
    "1233139781840670746"
]
NOTIFY_AND_APP_ROLES = EP_AND_ABOVE_ROLES + ["1234517225206059019"]

# --- DISCORD ROLE -> MAX "RANK VALUE" THEY CAN ASSIGN ---
# (These are your hierarchy values, NOT Roblox role IDs.)
DISCORD_RANK_LIMITS = {
    "1233139781823627473": 5,    # Level-4 Discord -> max Level-3 Roblox (value 5)
    "1246963191699734569": 6,    # Level-5 Discord -> max Level-4 Roblox (value 6)
    "1233139781840670743": 7,    # O5 Discord -> max Level-5 Roblox (value 7)
    "1233139781840670746": 9,    # O5 Head Discord -> max O5 Council Roblox (value 9)
    "1233139781840670749": 999,  # Administrator Discord -> unrestricted
}

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- CHOICES FOR COMMANDS ---
COLOR_CHOICES = [
    app_commands.Choice(name="Default (Blurple)", value="default"), app_commands.Choice(name="Red", value="red"),
    app_commands.Choice(name="Blue", value="blue"), app_commands.Choice(name="Green", value="green"),
    app_commands.Choice(name="Gold", value="gold"), app_commands.Choice(name="Orange", value="orange"),
    app_commands.Choice(name="Purple", value="purple"), app_commands.Choice(name="White", value="white"),
    app_commands.Choice(name="Black", value="black"),
]

# --- PERMISSION CHECKS ---
def has_any_role(required_roles: List[str]):
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        user_role_ids = {str(role.id) for role in interaction.user.roles}
        return any(role_id in user_role_ids for role_id in required_roles)
    return app_commands.check(predicate)

# --- HELPER FUNCTIONS ---
def get_discord_color(color_name: str) -> discord.Color:
    color_map = {
        "red": discord.Color.red(),
        "blue": discord.Color.blue(),
        "green": discord.Color.green(),
        "gold": discord.Color.gold(),
        "orange": discord.Color.orange(),
        "purple": discord.Color.purple(),
        "white": discord.Color.from_rgb(255, 255, 255),
        "black": discord.Color.from_rgb(0, 0, 0),
        "default": discord.Color.blurple(),
    }
    return color_map.get(color_name, discord.Color.default())

def create_button_view(buttons_data):
    if not buttons_data:
        return None
    view = discord.ui.View()
    for button in buttons_data:
        view.add_item(discord.ui.Button(label=button['label'], style=discord.ButtonStyle.link, url=button['url']))
    return view if view.children else None

def extract_buttons_from_message(message: discord.Message):
    buttons = []
    for action_row in getattr(message, "components", []) or []:
        for component in getattr(action_row, "children", []):
            if getattr(component, "style", None) == discord.ButtonStyle.link:
                label = getattr(component, "label", None)
                url = getattr(component, "url", None)
                if label and url:
                    buttons.append({"label": label, "url": url})
    return buttons

# ===================== ROBLOX HELPERS (WORKING VERSION) =====================
# These are your "rank values" (hierarchy), NOT Roblox role IDs.
ROBLOX_ROLE_VALUES = {
    "Class - D": 1,
    "Class - E": 2,
    "Level - 1": 3,
    "Level - 2": 4,
    "Level - 3": 5,
    "Level - 4": 6,
    "Level - 5": 7,
    "O5 Council": 9,
    "O5 Head": 10,
    "The Administrator": 11,
    "Group Holder": 255,
}

RANK_CHOICES = [
    app_commands.Choice(name=f"{name} (Value {val})", value=name)
    for name, val in ROBLOX_ROLE_VALUES.items()
]

_roblox_csrf_token = None
_group_roles_cache = None
_group_roles_cache_time = 0.0
_GROUP_ROLES_CACHE_SECONDS = 300  # 5 minutes
_rank_cooldown_seconds = 15
_rank_last_used = {}

def roblox_request(method: str, url: str, json=None):
    """
    Roblox requires X-CSRF-TOKEN for state-changing requests.
    We'll auto-retry once if we receive a token.
    """
    global _roblox_csrf_token

    headers = dict(ROBLOX_HEADERS_BASE)
    if _roblox_csrf_token:
        headers["X-CSRF-TOKEN"] = _roblox_csrf_token

    r = requests.request(method, url, headers=headers, json=json)

    # If token invalid/missing, Roblox returns 403 with X-CSRF-TOKEN header
    if r.status_code == 403 and "X-CSRF-TOKEN" in r.headers:
        _roblox_csrf_token = r.headers["X-CSRF-TOKEN"]
        headers["X-CSRF-TOKEN"] = _roblox_csrf_token
        r = requests.request(method, url, headers=headers, json=json)

    return r

def get_max_allowed_rank_value(member: discord.Member) -> int:
    return max((DISCORD_RANK_LIMITS.get(str(role.id), 0) for role in member.roles), default=0)

def resolve_roblox_user(target: str):
    """
    target can be username OR userId in the same field.
    """
    if target.isdigit():
        user_id = int(target)
        r = requests.get(f"https://users.roblox.com/v1/users/{user_id}")
        if r.status_code != 200:
            raise ValueError("Invalid Roblox user ID.")
        return user_id, r.json()["name"]

    r = requests.post(
        "https://users.roblox.com/v1/usernames/users",
        json={"usernames": [target], "excludeBannedUsers": False},
    )
    data = r.json().get("data", [])
    if not data:
        raise ValueError("Roblox username not found.")
    return data[0]["id"], data[0]["name"]

def get_group_roles():
    """
    Returns Roblox roles for the group, cached for a short time.
    """
    global _group_roles_cache, _group_roles_cache_time
    now = time.time()
    if _group_roles_cache and (now - _group_roles_cache_time) < _GROUP_ROLES_CACHE_SECONDS:
        return _group_roles_cache

    r = requests.get(f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/roles")
    if r.status_code != 200:
        raise RuntimeError(f"Failed to fetch group roles: {r.text}")

    roles = r.json().get("roles", [])
    _group_roles_cache = roles
    _group_roles_cache_time = now
    return roles

def get_role_id_by_name(role_name: str) -> int:
    for role in get_group_roles():
        if role.get("name", "").strip().lower() == role_name.strip().lower():
            return int(role["id"])
    raise ValueError("That role does not exist in the Roblox group.")

def get_current_role_name(user_id: int) -> str:
    r = requests.get(f"https://groups.roblox.com/v1/users/{user_id}/groups/roles")
    if r.status_code != 200:
        return "Unknown"
    for g in r.json().get("data", []):
        if g.get("group", {}).get("id") == ROBLOX_GROUP_ID:
            return g.get("role", {}).get("name", "Unknown")
    return "Not in group"

def get_role_value(role_name: str) -> int | None:
    if role_name in {"Unknown", "Not in group"}:
        return 0
    return ROBLOX_ROLE_VALUES.get(role_name)

# --- BOT EVENTS ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    load_motion_state()
    restore_motion_timers()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# --- MODALS (FORMS) ---
class EditAnnouncementModal(discord.ui.Modal):
    def __init__(self, message: discord.Message, original_embed: discord.Embed, **kwargs):
        super().__init__(title='Edit Announcement')
        self.message = message
        self.original_embed = original_embed
        self.kwargs = kwargs

        default_title = original_embed.title or ""
        default_description = original_embed.description or ""

        self.title_input = discord.ui.TextInput(
            label='Title', style=discord.TextStyle.short, required=True, max_length=256, default=default_title
        )
        self.message_input = discord.ui.TextInput(
            label='Message', style=discord.TextStyle.paragraph, required=True, max_length=4000, default=default_description
        )

        self.add_item(self.title_input)
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        existing_color = self.original_embed.color or discord.Color.default()
        embed_color = get_discord_color(self.kwargs.get('color')) if self.kwargs.get('color') else existing_color

        new_embed = discord.Embed(
            title=self.title_input.value,
            description=self.message_input.value,
            color=embed_color,
            timestamp=datetime.now(UTC)
        )

        existing_image_url = getattr(self.original_embed.image, 'url', None)
        existing_thumbnail_url = getattr(self.original_embed.thumbnail, 'url', None)

        if self.kwargs.get('remove_image'):
            pass
        elif self.kwargs.get('image_url'):
            new_embed.set_image(url=self.kwargs['image_url'])
        elif existing_image_url:
            new_embed.set_image(url=existing_image_url)

        if self.kwargs.get('remove_thumbnail'):
            pass
        elif self.kwargs.get('thumbnail_url'):
            new_embed.set_thumbnail(url=self.kwargs['thumbnail_url'])
        elif existing_thumbnail_url:
            new_embed.set_thumbnail(url=existing_thumbnail_url)

        footer_text = None
        if self.kwargs.get('clear_footer'):
            footer_text = None
        elif self.kwargs.get('footer_text'):
            footer_text = self.kwargs['footer_text']
        else:
            footer_text = getattr(self.original_embed.footer, 'text', None)

        if footer_text:
            new_embed.set_footer(text=footer_text)

        buttons_list = list(self.kwargs.get('existing_buttons', []))
        if self.kwargs.get('clear_buttons'):
            buttons_list = []
        else:
            while len(buttons_list) < 2:
                buttons_list.append({})
            if self.kwargs.get('button1_text') or self.kwargs.get('button1_url'):
                buttons_list[0] = {
                    "label": self.kwargs.get('button1_text') or buttons_list[0].get('label'),
                    "url": self.kwargs.get('button1_url') or buttons_list[0].get('url')
                }
            if self.kwargs.get('button2_text') or self.kwargs.get('button2_url'):
                buttons_list[1] = {
                    "label": self.kwargs.get('button2_text') or buttons_list[1].get('label'),
                    "url": self.kwargs.get('button2_url') or buttons_list[1].get('url')
                }
            buttons_list = [b for b in buttons_list if b.get('label') and b.get('url')]

        view = create_button_view(buttons_list)

        try:
            await self.message.edit(embed=new_embed, view=view)
            await interaction.response.send_message("Announcement has been updated!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to edit the announcement: {e}", ephemeral=True)

# --- APPLICATION & NOTIFICATION COMMANDS ---
@bot.tree.command(name="notify", description="Sends a Class-E or Blacklist notification to a user.")
@has_any_role(NOTIFY_AND_APP_ROLES)
@app_commands.describe(
    user="The user to notify.",
    type="The type of notification.",
    reason="The reason for this action.",
    duration="The duration of this action.",
    trello_card="Link to the user's Trello card.",
    appealable="Whether the user can appeal this action.",
    notifier_department="The department issuing the notification."
)
@app_commands.choices(
    type=[app_commands.Choice(name="Class-E", value="Class-E"), app_commands.Choice(name="Blacklist", value="Blacklist")],
    notifier_department=[app_commands.Choice(name="IA", value="IA"), app_commands.Choice(name="EC", value="EC")]
)
async def notify(
    interaction: discord.Interaction,
    user: discord.Member,
    type: app_commands.Choice[str],
    reason: str,
    duration: str,
    trello_card: str,
    appealable: bool,
    notifier_department: app_commands.Choice[str]
):
    embed = discord.Embed(title=f"Notification of {type.name}", color=discord.Color.orange(), timestamp=datetime.now(UTC))
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Duration", value=duration, inline=False)
    embed.add_field(name="Trello Card", value=f"[View Card]({trello_card})", inline=False)

    view = discord.ui.View()
    if appealable:
        appeal_text = f"You must appeal to **{notifier_department.name}** as you were disciplined by **{notifier_department.name}**."
        embed.add_field(name="Appeals", value=appeal_text, inline=False)
        if notifier_department.value == "IA":
            view.add_item(discord.ui.Button(label="IA Server", style=discord.ButtonStyle.link, url="https://discord.gg/rQwMDFbfEg"))
        elif notifier_department.value == "EC":
            view.add_item(discord.ui.Button(label="EC Server", style=discord.ButtonStyle.link, url="https://discord.gg/pAWjndT9jF"))
    else:
        embed.add_field(name="Appeals", value="This decision is **unappealable**.", inline=False)

    try:
        await user.send(embed=embed, view=view if appealable else None)
        await interaction.response.send_message(f"✅ Successfully sent a {type.name} notification to {user.mention}.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(f"⚠️ Could not send a DM to {user.mention}. Their DMs are likely closed.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)

async def process_application(interaction: discord.Interaction, message_link: str, applicant: discord.Member, accepted: bool, details: str):
    results_channel = bot.get_channel(APPLICATION_RESULTS_CHANNEL_ID)
    if not results_channel:
        return await interaction.response.send_message("Error: Application results channel not found.", ephemeral=True)

    match = re.match(r"https://discord.com/channels/\d+/(\d+)/(\d+)", message_link)
    if not match:
        return await interaction.response.send_message("Invalid message link format.", ephemeral=True)

    channel_id, message_id = map(int, match.groups())

    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        message = await channel.fetch_message(message_id)
    except (discord.NotFound, discord.Forbidden):
        return await interaction.response.send_message("Could not find the application message. Please check the link.", ephemeral=True)

    reaction = "✅" if accepted else "❌"
    try:
        await message.add_reaction(reaction)
    except discord.Forbidden:
        print(f"Could not add reaction to message {message_id}. Missing permissions.")

    app_level = ""
    if "level-1" in channel.name.lower():
        app_level = "Level-1 "
    elif "level-2" in channel.name.lower():
        app_level = "Level-2 "
    elif "level-3" in channel.name.lower():
        app_level = "Level-3 "

    status = "Accepted" if accepted else "Denied"
    color = discord.Color.green() if accepted else discord.Color.red()

    embed = discord.Embed(
        title=f"{applicant.display_name} | {app_level}Application {status}",
        color=color,
        timestamp=datetime.now(UTC)
    )
    embed.description = f"{applicant.mention}'s {app_level.lower()}application has been **{status}**."
    embed.add_field(name="Reason", value=details, inline=False)
    embed.set_footer(text=f"Processed by {interaction.user.display_name}")

    allowed_mentions = discord.AllowedMentions(users=[applicant]) if accepted else None
    content = applicant.mention if accepted else None
    await results_channel.send(content=content, embed=embed, allowed_mentions=allowed_mentions)
    await interaction.response.send_message(f"Application for {applicant.mention} has been processed.", ephemeral=True)

applications_group = app_commands.Group(name="applications", description="Manage application results.")

@applications_group.command(name="accept", description="Accept a user's application and log the result.")
@has_any_role(NOTIFY_AND_APP_ROLES)
@app_commands.describe(message_link="Link to the application message.", applicant="The user who applied.", reason="Optional reason for acceptance.")
async def applications_accept(interaction: discord.Interaction, message_link: str, applicant: discord.Member, reason: str = "Not provided."):
    await process_application(interaction, message_link, applicant, accepted=True, details=reason)

@applications_group.command(name="reject", description="Reject a user's application and log the result.")
@has_any_role(NOTIFY_AND_APP_ROLES)
@app_commands.describe(message_link="Link to the application message.", applicant="The user who applied.", reason="Optional reason for rejection.")
async def applications_reject(interaction: discord.Interaction, message_link: str, applicant: discord.Member, reason: str = "Not provided."):
    await process_application(interaction, message_link, applicant, accepted=False, details=reason)

# --- CORE BOT COMMANDS ---
@bot.tree.command(name="ssu", description="Announce a Server Start Up (SSU).")
@app_commands.checks.cooldown(1, 600, key=lambda i: i.guild_id)
@has_any_role(EP_AND_ABOVE_ROLES)
async def ssu(interaction: discord.Interaction):
    ssu_channel = bot.get_channel(SSU_CHANNEL_ID)
    if not ssu_channel:
        return await interaction.response.send_message("Error: SSU channel not found.", ephemeral=True)

    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Join Game", style=discord.ButtonStyle.link, url=GAME_LINK))

    embed = discord.Embed(
        title="🚀 Server Start Up (SSU) Hosted!",
        description=f"A Server Start Up has been started by {interaction.user.mention}. Join us now!",
        color=discord.Color.green(),
        timestamp=datetime.now(UTC)
    )
    embed.set_footer(text=f"Hosted by {interaction.user.display_name}")

    await ssu_channel.send(content="@everyone", embed=embed, view=view)
    await interaction.response.send_message("SSU announcement has been sent!", ephemeral=True)

@bot.tree.command(name="announce_edit", description="Edit an existing server announcement.")
@has_any_role(DD_AND_ABOVE_ROLES)
@app_commands.choices(color=COLOR_CHOICES)
@app_commands.describe(
    message_link="Link to the announcement message.",
    color="New color for the embed.",
    image_url="New image URL.",
    thumbnail_url="New thumbnail URL.",
    footer_text="New footer text.",
    button1_text="Updated text for button 1.",
    button1_url="Updated URL for button 1.",
    button2_text="Updated text for button 2.",
    button2_url="Updated URL for button 2.",
    clear_buttons="Remove all buttons from the announcement.",
    remove_image="Remove the embed image.",
    remove_thumbnail="Remove the embed thumbnail.",
    clear_footer="Remove the embed footer."
)
async def announce_edit(
    interaction: discord.Interaction,
    message_link: str,
    color: app_commands.Choice[str] = None,
    image_url: str = None,
    thumbnail_url: str = None,
    footer_text: str = None,
    button1_text: str = None,
    button1_url: str = None,
    button2_text: str = None,
    button2_url: str = None,
    clear_buttons: bool = False,
    remove_image: bool = False,
    remove_thumbnail: bool = False,
    clear_footer: bool = False,
):
    match = re.match(r"https://discord.com/channels/\d+/(\d+)/(\d+)", message_link)
    if not match:
        return await interaction.response.send_message("Invalid message link format.", ephemeral=True)

    channel_id, message_id = map(int, match.groups())

    if channel_id != ANNOUNCEMENT_CHANNEL_ID:
        return await interaction.response.send_message("That message is not in the announcement channel.", ephemeral=True)

    announcement_channel = bot.get_channel(channel_id)
    if not announcement_channel:
        try:
            announcement_channel = await bot.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden):
            announcement_channel = None
    if not announcement_channel:
        return await interaction.response.send_message("Announcement channel could not be found.", ephemeral=True)

    try:
        message = await announcement_channel.fetch_message(message_id)
    except (discord.NotFound, discord.Forbidden):
        return await interaction.response.send_message("Announcement message could not be found.", ephemeral=True)

    if message.author != bot.user:
        return await interaction.response.send_message("I can only edit announcements sent by me.", ephemeral=True)

    if not message.embeds:
        return await interaction.response.send_message("This message does not contain an embed to edit.", ephemeral=True)

    original_embed = message.embeds[0]
    existing_buttons = extract_buttons_from_message(message)

    modal_kwargs = {
        'color': color.value if color else None,
        'image_url': image_url,
        'thumbnail_url': thumbnail_url,
        'footer_text': footer_text,
        'button1_text': button1_text,
        'button1_url': button1_url,
        'button2_text': button2_text,
        'button2_url': button2_url,
        'clear_buttons': clear_buttons,
        'remove_image': remove_image,
        'remove_thumbnail': remove_thumbnail,
        'clear_footer': clear_footer,
        'existing_buttons': existing_buttons,
    }

    await interaction.response.send_modal(EditAnnouncementModal(message=message, original_embed=original_embed, **modal_kwargs))

# ===================== NEW: /RANK (WORKING) =====================
@bot.tree.command(name="rank", description="Rank a Roblox user in the group (username or userId).")
@has_any_role(list(DISCORD_RANK_LIMITS.keys()))
@app_commands.checks.cooldown(10, 3600, key=lambda i: i.user.id)
@app_commands.choices(rank=RANK_CHOICES)
@app_commands.describe(
    target="Roblox username or userId",
    rank="Rank to assign",
    reason="Reason for this action (required)"
)
async def rank(interaction: discord.Interaction, target: str, rank: app_commands.Choice[str], reason: str):
    log_channel = bot.get_channel(RANK_LOG_CHANNEL_ID)
    max_allowed_value = get_max_allowed_rank_value(interaction.user)
    now = time.time()
    last_used = _rank_last_used.get(interaction.user.id, 0)
    remaining_cooldown = _rank_cooldown_seconds - (now - last_used)
    if remaining_cooldown > 0:
        await interaction.response.send_message(
            f"Please wait {int(remaining_cooldown)} more seconds before ranking again.",
            ephemeral=True
        )
        return
    _rank_last_used[interaction.user.id] = now

    try:
        user_id, username = resolve_roblox_user(target)
        old_role_name = get_current_role_name(user_id)
        current_value = get_role_value(old_role_name)

        desired_role_name = rank.value
        desired_value = ROBLOX_ROLE_VALUES.get(desired_role_name)

        if current_value is None:
            raise ValueError("That user's current rank is not configured correctly.")

        if current_value > max_allowed_value:
            raise PermissionError("You are not authorized to change the rank of a user with that rank.")

        if desired_value is None:
            raise ValueError("That rank choice is not configured correctly.")

        if desired_value > max_allowed_value:
            raise PermissionError("You are not authorized to assign that rank.")

        role_id = get_role_id_by_name(desired_role_name)

        r = roblox_request(
            "PATCH",
            f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/users/{user_id}",
            json={"roleId": role_id}
        )

        if r.status_code != 200:
            raise RuntimeError(r.text)

        result = "✅ Success"
        color = discord.Color.green()
        response = f"✅ Ranked **{username}** to **{desired_role_name}**."

    except Exception as e:
        result = "❌ Failed"
        color = discord.Color.red()
        response = f"❌ {e}"

    embed = discord.Embed(
        title="Rank Log",
        color=color,
        timestamp=datetime.now(UTC)
    )
    embed.add_field(name="Executive", value=interaction.user.mention, inline=False)
    embed.add_field(name="Target", value=username if 'username' in locals() else target, inline=False)
    embed.add_field(name="Old → New", value=f"{old_role_name if 'old_role_name' in locals() else 'Unknown'} → {rank.value}", inline=False)
    embed.add_field(name="Result", value=result, inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)

    if log_channel:
        await log_channel.send(embed=embed)

    await interaction.response.send_message(response, ephemeral=True)



# ===================== MOTION SYSTEM =====================
motion_state = {"next_motion_number": 1, "motions": {}}
motion_timer_tasks: dict[str, asyncio.Task] = {}


def _motion_vote_snapshot(motion: dict) -> dict:
    return {
        "board": {option: list(motion["board_votes"][option]) for option in MOTION_VOTE_OPTIONS},
        "o5": {option: list(motion["o5_votes"][option]) for option in MOTION_VOTE_OPTIONS},
    }


def append_motion_audit_entry(motion: dict, action: str, actor_id: int | None = None, extra: dict | None = None):
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "action": action,
        "actor_id": actor_id,
    }
    if extra:
        entry.update(extra)
    motion.setdefault("audit_log", []).append(entry)


def save_motion_state():
    with open(MOTION_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(motion_state, f, indent=2)


def load_motion_state():
    global motion_state
    if os.path.exists(MOTION_STATE_FILE):
        with open(MOTION_STATE_FILE, "r", encoding="utf-8") as f:
            motion_state = json.load(f)
    else:
        save_motion_state()

    motion_state.setdefault("next_motion_number", 1)
    motion_state.setdefault("motions", {})

    max_motion_number = 0
    for motion_id, motion in motion_state["motions"].items():
        try:
            max_motion_number = max(max_motion_number, int(motion.get("motion_number", int(motion_id))))
        except (TypeError, ValueError):
            continue
        motion.setdefault("audit_log", [])

    motion_state["next_motion_number"] = max(motion_state["next_motion_number"], max_motion_number + 1)


def member_has_any_role(member: discord.Member, role_ids: list[int]) -> bool:
    member_role_ids = {r.id for r in member.roles}
    return any(role_id in member_role_ids for role_id in role_ids)


def can_manage_motions(member: discord.Member) -> bool:
    return member_has_any_role(member, [COUNCIL_CHAIRMAN_ROLE_ID, ADMINISTRATOR_ROLE_ID])


def can_vote_stage(member: discord.Member, stage: str) -> bool:
    if stage == "board":
        return member_has_any_role(member, [BOARD_ROLE_ID, COUNCIL_CHAIRMAN_ROLE_ID, ADMINISTRATOR_ROLE_ID])
    if stage == "o5":
        return member_has_any_role(member, [O5_ROLE_ID, COUNCIL_CHAIRMAN_ROLE_ID, ADMINISTRATOR_ROLE_ID])
    return False


def format_vote_block(label: str, emoji: str, user_ids: list[int]) -> str:
    if user_ids:
        voters = "\n".join(f"• <@{uid}>" for uid in user_ids)
    else:
        voters = "• None"
    return f"▎{emoji} **{label} ({len(user_ids)})**\n{voters}"


def normalize_motion_content(content: str) -> str:
    """
    Preserve readable formatting from pasted text while removing accidental
    slash-command/clipboard whitespace issues.
    """
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    normalized = textwrap.dedent(normalized)
    lines = [line.rstrip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()


def get_motion_stage_ping(stage: str) -> str:
    stage_role_map = {
        "board": BOARD_ROLE_ID,
        "o5": O5_ROLE_ID,
    }
    role_id = stage_role_map.get(stage)
    return f"<@&{role_id}>" if role_id else ""


def build_motion_embed(motion: dict) -> discord.Embed:
    status_map = {
        "board_voting": "Board of Directors Voting",
        "o5_voting": "O5 Council Voting",
        "passed": "PASSED",
        "failed_board": "Failed at Board",
        "failed_o5": "Failed at O5 Council",
        "vetoed": "Vetoed",
    }
    color_map = {
        "board_voting": discord.Color.gold(),
        "o5_voting": discord.Color.orange(),
        "passed": discord.Color.green(),
        "failed_board": discord.Color.red(),
        "failed_o5": discord.Color.red(),
        "vetoed": discord.Color.dark_red(),
    }

    status_text = status_map.get(motion["status"], motion["status"])
    description = (
        f"`{status_text}`\n\n"
        f"{normalize_motion_content(motion['content'])}"
    )

    embed = discord.Embed(
        title=f"Motion #{int(motion['motion_number']):03d} || {motion['title']}",
        description=description,
        color=color_map.get(motion["status"], discord.Color.blurple()),
        timestamp=datetime.now(UTC),
    )
    current_stage = "Board of Directors" if motion["status"] == "board_voting" else "Overseer Council"
    embed.add_field(name="📩 Proposed by", value=f"<@{motion['proposer_id']}>", inline=True)
    embed.add_field(name="🚩 Stage", value=current_stage, inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=False)

    board_votes = motion["board_votes"]
    o5_votes = motion["o5_votes"]

    board_summary = "\n\n".join([
        format_vote_block("Approvals", MOTION_EMOJIS["approve"]["text"], board_votes["approve"]),
        format_vote_block("Rejections", MOTION_EMOJIS["reject"]["text"], board_votes["reject"]),
        format_vote_block("Abstentions", MOTION_EMOJIS["abstain"]["text"], board_votes["abstain"]),
    ])

    if motion["status"] == "board_voting":
        board_summary += "\n\n**Awaiting Board decision.**"
    elif motion["status"] == "passed":
        board_summary += "\n\nPassed **Board of Directors**."
    else:
        board_summary += "\n\nBoard stage complete."

    embed.add_field(
        name="Board of Directors Vote",
        value=board_summary,
        inline=True,
    )

    if motion["status"] == "board_voting":
        o5_summary = "Overseer Council vote opens after Board approval."
    else:
        o5_summary = "\n\n".join([
            format_vote_block("Approvals", MOTION_EMOJIS["approve"]["text"], o5_votes["approve"]),
            format_vote_block("Rejections", MOTION_EMOJIS["reject"]["text"], o5_votes["reject"]),
            format_vote_block("Abstentions", MOTION_EMOJIS["abstain"]["text"], o5_votes["abstain"]),
        ])

        if motion["status"] == "o5_voting":
            o5_summary += "\n\nAwaiting **Overseer Council** decision."
        elif motion["status"] == "passed":
            o5_summary += "\n\nPassed **Council**."
        elif motion["status"] in {"failed_o5", "vetoed"}:
            o5_summary += "\n\nFailed at **Council** stage."
        else:
            o5_summary += "\n\nCouncil stage closed."

    embed.add_field(
        name="Overseer Council Vote",
        value=o5_summary,
        inline=True,
    )

    if motion["status"] in {"board_voting", "o5_voting"}:
        embed.set_footer(text="Vote buttons remain active only during the current stage.")
    return embed


async def get_channel_by_id(channel_id: int):
    channel = bot.get_channel(channel_id)
    if channel:
        return channel
    try:
        return await bot.fetch_channel(channel_id)
    except (discord.NotFound, discord.Forbidden):
        return None


async def update_motion_messages(motion_id: str):
    motion = motion_state["motions"].get(motion_id)
    if not motion:
        return

    embed = build_motion_embed(motion)

    board_channel = await get_channel_by_id(motion["board_channel_id"])
    if board_channel and motion.get("board_message_id"):
        try:
            board_msg = await board_channel.fetch_message(motion["board_message_id"])
            board_view = MotionVoteView(motion_id, "board") if motion["status"] == "board_voting" else None
            await board_msg.edit(embed=embed, view=board_view)
        except (discord.NotFound, discord.Forbidden):
            pass

    if motion.get("o5_message_id") and motion.get("o5_channel_id"):
        o5_channel = await get_channel_by_id(motion["o5_channel_id"])
        if o5_channel:
            try:
                o5_msg = await o5_channel.fetch_message(motion["o5_message_id"])
                o5_view = MotionVoteView(motion_id, "o5") if motion["status"] == "o5_voting" else None
                await o5_msg.edit(embed=embed, view=o5_view)
            except (discord.NotFound, discord.Forbidden):
                pass


def build_motion_update_embed(motion: dict, headline: str) -> discord.Embed:
    embed = build_motion_embed(motion)
    embed.title = f"Motion {int(motion['motion_number']):03d}"
    embed.description = (
        f"**{motion['title']}**\n"
        f"`{headline}`\n\n"
        f"{normalize_motion_content(motion['content'])}"
    )
    return embed


async def send_bulletin_update(motion: dict, headline: str):
    updates_channel = await get_channel_by_id(MOTION_UPDATES_CHANNEL_ID)
    if not updates_channel:
        return

    embed = build_motion_update_embed(motion, headline)

    existing_message_id = motion.get("updates_message_id")
    if existing_message_id:
        try:
            existing_message = await updates_channel.fetch_message(existing_message_id)
            await existing_message.edit(embed=embed)
            return
        except (discord.NotFound, discord.Forbidden):
            pass

    sent_message = await updates_channel.send(embed=embed)
    motion["updates_message_id"] = sent_message.id
    save_motion_state()


async def move_motion_to_o5(motion_id: str, actor: discord.abc.User | None = None):
    motion = motion_state["motions"].get(motion_id)
    if not motion or motion["status"] != "board_voting":
        return

    motion["status"] = "o5_voting"
    motion["o5_started_at"] = datetime.now(UTC).isoformat()
    motion["o5_deadline"] = (datetime.now(UTC) + timedelta(hours=24)).isoformat()

    append_motion_audit_entry(
        motion,
        action="advanced_to_o5",
        actor_id=actor.id if actor else None,
        extra={"votes": _motion_vote_snapshot(motion)},
    )

    o5_channel = await get_channel_by_id(O5_MOTIONS_CHANNEL_ID)
    if o5_channel:
        embed = build_motion_embed(motion)
        content = get_motion_stage_ping("o5")
        o5_msg = await o5_channel.send(content=content, embed=embed, view=MotionVoteView(motion_id, "o5"))
        motion["o5_channel_id"] = o5_channel.id
        motion["o5_message_id"] = o5_msg.id

    save_motion_state()
    await update_motion_messages(motion_id)
    await send_bulletin_update(motion, "Motion advanced to O5 Council")
    schedule_motion_timer(motion_id)


async def finalize_motion(motion_id: str, result: str, actor: discord.abc.User | None = None):
    motion = motion_state["motions"].get(motion_id)
    if not motion:
        return

    motion["status"] = result
    motion["finalized_at"] = datetime.now(UTC).isoformat()
    if actor:
        motion["finalized_by"] = actor.id

    append_motion_audit_entry(
        motion,
        action="finalized",
        actor_id=actor.id if actor else None,
        extra={"result": result, "votes": _motion_vote_snapshot(motion)},
    )

    save_motion_state()
    await update_motion_messages(motion_id)

    if result == "passed":
        await send_bulletin_update(motion, "Motion passed")
    elif result == "failed_board":
        await send_bulletin_update(motion, "Motion failed at Board")
    elif result == "failed_o5":
        await send_bulletin_update(motion, "Motion failed at O5 Council")
    elif result == "vetoed":
        await send_bulletin_update(motion, "Motion vetoed")

    task = motion_timer_tasks.pop(motion_id, None)
    if task:
        task.cancel()


async def handle_motion_timeout(motion_id: str):
    motion = motion_state["motions"].get(motion_id)
    if not motion:
        return

    now = datetime.now(UTC)
    deadline_key = "board_deadline" if motion["status"] == "board_voting" else "o5_deadline"
    deadline = datetime.fromisoformat(motion[deadline_key])
    wait_seconds = max((deadline - now).total_seconds(), 0)
    await asyncio.sleep(wait_seconds)

    motion = motion_state["motions"].get(motion_id)
    if not motion:
        return

    if motion["status"] == "board_voting":
        board_votes = motion["board_votes"]
        if len(board_votes["approve"]) > len(board_votes["reject"]):
            await move_motion_to_o5(motion_id)
        else:
            await finalize_motion(motion_id, "failed_board")
    elif motion["status"] == "o5_voting":
        o5_votes = motion["o5_votes"]
        if len(o5_votes["approve"]) > len(o5_votes["reject"]):
            await finalize_motion(motion_id, "passed")
        else:
            await finalize_motion(motion_id, "failed_o5")


def schedule_motion_timer(motion_id: str):
    task = motion_timer_tasks.get(motion_id)
    if task and not task.done():
        task.cancel()

    motion = motion_state["motions"].get(motion_id)
    if not motion or motion["status"] not in {"board_voting", "o5_voting"}:
        return

    motion_timer_tasks[motion_id] = asyncio.create_task(handle_motion_timeout(motion_id))


def restore_motion_timers():
    for motion_id, motion in motion_state["motions"].items():
        if motion["status"] in {"board_voting", "o5_voting"}:
            schedule_motion_timer(motion_id)


async def process_vote(interaction: discord.Interaction, motion_id: str, stage: str, vote_type: str):
    motion = motion_state["motions"].get(motion_id)
    if not motion:
        await interaction.response.send_message("Motion data not found.", ephemeral=True)
        return

    expected_status = "board_voting" if stage == "board" else "o5_voting"
    if motion["status"] != expected_status:
        await interaction.response.send_message("That voting stage is no longer active.", ephemeral=True)
        return

    if not isinstance(interaction.user, discord.Member) or not can_vote_stage(interaction.user, stage):
        await interaction.response.send_message("You do not have permission to vote in this stage.", ephemeral=True)
        return

    stage_votes = motion["board_votes"] if stage == "board" else motion["o5_votes"]

    user_id = interaction.user.id
    for vote_option in MOTION_VOTE_OPTIONS:
        if user_id in stage_votes[vote_option]:
            stage_votes[vote_option].remove(user_id)
    stage_votes[vote_type].append(user_id)

    append_motion_audit_entry(
        motion,
        action="vote_cast",
        actor_id=user_id,
        extra={"stage": stage, "vote": vote_type},
    )

    save_motion_state()
    await update_motion_messages(motion_id)
    await interaction.response.send_message(f"Vote recorded: **{vote_type}**.", ephemeral=True)


class MotionVoteView(discord.ui.View):
    def __init__(self, motion_id: str, stage: str):
        super().__init__(timeout=None)
        self.motion_id = motion_id
        self.stage = stage

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji=MOTION_EMOJIS["approve"]["button"])
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_vote(interaction, self.motion_id, self.stage, "approve")

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji=MOTION_EMOJIS["reject"]["button"])
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_vote(interaction, self.motion_id, self.stage, "reject")

    @discord.ui.button(label="Abstain", style=discord.ButtonStyle.secondary, emoji=MOTION_EMOJIS["abstain"]["button"])
    async def abstain_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await process_vote(interaction, self.motion_id, self.stage, "abstain")


async def create_motion_post(
    interaction: discord.Interaction,
    title: str,
    content: str,
):
    initial_status = "board_voting"
    target_channel_id = BOARD_MOTIONS_CHANNEL_ID
    target_channel_name = "Board motions"

    target_channel = await get_channel_by_id(target_channel_id)
    if not target_channel:
        error_message = f"{target_channel_name} channel not found."
        if interaction.response.is_done():
            await interaction.followup.send(error_message, ephemeral=True)
        else:
            await interaction.response.send_message(error_message, ephemeral=True)
        return

    motion_number = int(motion_state["next_motion_number"])
    motion_id = str(motion_number)
    motion = {
        "motion_number": motion_number,
        "title": title,
        "content": normalize_motion_content(content),
        "proposer_id": interaction.user.id,
        "status": initial_status,
        "created_at": datetime.now(UTC).isoformat(),
        "board_deadline": (datetime.now(UTC) + timedelta(hours=24)).isoformat() if initial_status == "board_voting" else None,
        "board_channel_id": BOARD_MOTIONS_CHANNEL_ID,
        "board_message_id": None,
        "o5_started_at": None,
        "o5_deadline": None,
        "o5_channel_id": None,
        "o5_message_id": None,
        "board_votes": {"approve": [], "reject": [], "abstain": []},
        "o5_votes": {"approve": [], "reject": [], "abstain": []},
        "audit_log": [],
    }

    append_motion_audit_entry(
        motion,
        action="created",
        actor_id=interaction.user.id,
        extra={"proposer_id": interaction.user.id, "initial_status": initial_status},
    )

    embed = build_motion_embed(motion)
    opening_message = get_motion_stage_ping("board")

    motion_msg = await target_channel.send(
        content=opening_message,
        embed=embed,
        view=MotionVoteView(motion_id, "board"),
    )

    motion["board_message_id"] = motion_msg.id
    motion_state["motions"][motion_id] = motion
    motion_state["next_motion_number"] = motion_number + 1
    save_motion_state()
    schedule_motion_timer(motion_id)

    if interaction.response.is_done():
        await interaction.followup.send(
            f"Created motion **#{motion_number:03d}** and posted it in <#{target_channel_id}>.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            f"Created motion **#{motion_number:03d}** and posted it in <#{target_channel_id}>.",
            ephemeral=True,
        )


class MotionCreateModal(discord.ui.Modal, title="Create Motion"):
    motion_content = discord.ui.TextInput(
        label="Motion content",
        style=discord.TextStyle.paragraph,
        placeholder="Paste your full motion text here. Formatting/new lines are preserved.",
        required=True,
        max_length=4000,
    )

    def __init__(self, motion_title: str):
        super().__init__()
        self.motion_title = motion_title

    async def on_submit(self, interaction: discord.Interaction):
        await create_motion_post(interaction, self.motion_title, str(self.motion_content))


motion_group = app_commands.Group(name="motion", description="Motion lifecycle and voting commands")


@motion_group.command(name="create", description="Create a new motion for Board review.")
@app_commands.describe(
    title="Motion title",
    content="Optional. If omitted, a popup opens for easier multi-line formatting.",
)
async def motion_create(interaction: discord.Interaction, title: str, content: str | None = None):
    if not isinstance(interaction.user, discord.Member) or not member_has_any_role(
        interaction.user, [BOARD_ROLE_ID, O5_ROLE_ID, COUNCIL_CHAIRMAN_ROLE_ID, ADMINISTRATOR_ROLE_ID]
    ):
        await interaction.response.send_message("You do not have permission to create motions.", ephemeral=True)
        return

    if content is None:
        await interaction.response.send_modal(MotionCreateModal(motion_title=title))
        return

    await create_motion_post(interaction, title, content)


@motion_group.command(name="pass", description="Manually pass a motion to next stage or final pass.")
@app_commands.describe(motion_number="Motion number (e.g. 1 for #001)")
async def motion_pass(interaction: discord.Interaction, motion_number: int):
    if not isinstance(interaction.user, discord.Member) or not can_manage_motions(interaction.user):
        await interaction.response.send_message("You do not have permission to pass motions.", ephemeral=True)
        return

    motion_id = str(motion_number)
    motion = motion_state["motions"].get(motion_id)
    if not motion:
        await interaction.response.send_message("Motion not found.", ephemeral=True)
        return

    if motion["status"] == "board_voting":
        await move_motion_to_o5(motion_id, interaction.user)
        await interaction.response.send_message("Motion passed Board and moved to O5 voting.", ephemeral=True)
    elif motion["status"] == "o5_voting":
        await finalize_motion(motion_id, "passed", interaction.user)
        await interaction.response.send_message("Motion marked as passed.", ephemeral=True)
    else:
        await interaction.response.send_message("This motion is already finalized.", ephemeral=True)


@motion_group.command(name="reject", description="Manually reject a motion in its current stage.")
@app_commands.describe(motion_number="Motion number (e.g. 1 for #001)")
async def motion_reject(interaction: discord.Interaction, motion_number: int):
    if not isinstance(interaction.user, discord.Member) or not can_manage_motions(interaction.user):
        await interaction.response.send_message("You do not have permission to reject motions.", ephemeral=True)
        return

    motion_id = str(motion_number)
    motion = motion_state["motions"].get(motion_id)
    if not motion:
        await interaction.response.send_message("Motion not found.", ephemeral=True)
        return

    if motion["status"] == "board_voting":
        await finalize_motion(motion_id, "failed_board", interaction.user)
        await interaction.response.send_message("Motion rejected at Board stage.", ephemeral=True)
    elif motion["status"] == "o5_voting":
        await finalize_motion(motion_id, "failed_o5", interaction.user)
        await interaction.response.send_message("Motion rejected at O5 stage.", ephemeral=True)
    else:
        await interaction.response.send_message("This motion is already finalized.", ephemeral=True)


@motion_group.command(name="veto", description="Veto a motion and stop it immediately.")
@app_commands.describe(motion_number="Motion number (e.g. 1 for #001)")
async def motion_veto(interaction: discord.Interaction, motion_number: int):
    if not isinstance(interaction.user, discord.Member) or not can_manage_motions(interaction.user):
        await interaction.response.send_message("You do not have permission to veto motions.", ephemeral=True)
        return

    motion_id = str(motion_number)
    motion = motion_state["motions"].get(motion_id)
    if not motion:
        await interaction.response.send_message("Motion not found.", ephemeral=True)
        return

    if motion["status"] in {"passed", "failed_board", "failed_o5", "vetoed"}:
        await interaction.response.send_message("This motion is already finalized.", ephemeral=True)
        return

    await finalize_motion(motion_id, "vetoed", interaction.user)
    await interaction.response.send_message("Motion vetoed.", ephemeral=True)


@motion_group.command(name="status", description="View motion status and vote breakdown.")
@app_commands.describe(motion_number="Motion number (e.g. 1 for #001)")
async def motion_status(interaction: discord.Interaction, motion_number: int):
    motion = motion_state["motions"].get(str(motion_number))
    if not motion:
        await interaction.response.send_message("Motion not found.", ephemeral=True)
        return

    await interaction.response.send_message(embed=build_motion_embed(motion), ephemeral=True)

# --- REGISTER GROUP COMMANDS ---
bot.tree.add_command(applications_group)
bot.tree.add_command(motion_group)

# --- ERROR HANDLING ---
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        time_left = str(timedelta(seconds=int(error.retry_after)))  # fine for display
        await interaction.response.send_message(
            f"This command is on cooldown for everyone. Please try again in **{time_left}**.",
            ephemeral=True
        )
    elif isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You do not have the required permissions to use this command.", ephemeral=True)
    else:
        print(f"An unhandled error occurred in the command tree: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)
        else:
            await interaction.followup.send("An unexpected error occurred.", ephemeral=True)

# --- RUN THE BOT ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN is not set in the environment variables.")
    else:
        bot.run(BOT_TOKEN)
