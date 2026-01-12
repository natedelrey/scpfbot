import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, UTC, timedelta
import os
from dotenv import load_dotenv
from typing import List
import re
import requests
import time

# --- CONFIGURATION ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

try:
    ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID"))
    SSU_CHANNEL_ID = int(os.getenv("SSU_CHANNEL_ID"))
    APPLICATION_RESULTS_CHANNEL_ID = int(os.getenv("APPLICATION_RESULTS_CHANNEL_ID"))
    RANK_LOG_CHANNEL_ID = int(os.getenv("RANK_LOG_CHANNEL_ID"))
    ROBLOX_GROUP_ID = int(os.getenv("ROBLOX_GROUP_ID"))
except (TypeError, ValueError):
    print("Error: A required Channel ID (or ROBLOX_GROUP_ID) is not set correctly in your environment variables.")
    exit()

GAME_LINK = os.getenv("GAME_LINK", "https://www.roblox.com/games/17371095768/SCP-Lambda")

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
    max_val = 0
    for role in member.roles:
        max_val = max(max_val, DISCORD_RANK_LIMITS.get(str(role.id), 0))
    return max_val

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

        if current_value >= max_allowed_value:
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
        title="Roblox Rank Log",
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

# --- REGISTER GROUP COMMANDS ---
bot.tree.add_command(applications_group)

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
