import discord
from discord.ext import commands
from discord import app_commands
import datetime
import json
import os
import asyncpg
from dotenv import load_dotenv
from typing import List, Optional
import re

# --- CONFIGURATION ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
try:
    ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID"))
    RECRUITMENT_CHANNEL_ID = int(os.getenv("RECRUITMENT_CHANNEL_ID"))
    SSU_CHANNEL_ID = int(os.getenv("SSU_CHANNEL_ID"))
    APPLICATION_RESULTS_CHANNEL_ID = int(os.getenv("APPLICATION_RESULTS_CHANNEL_ID"))
except (TypeError, ValueError):
    print("Error: A required Channel ID is not set correctly in your environment variables.")
    exit()
GAME_LINK = os.getenv("GAME_LINK", "https://www.roblox.com/games/17371095768/SCP-Lambda")

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

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot.db_pool = None

# --- CHOICES FOR COMMANDS ---
COLOR_CHOICES = [
    app_commands.Choice(name="Default (Blurple)", value="default"), app_commands.Choice(name="Red", value="red"),
    app_commands.Choice(name="Blue", value="blue"), app_commands.Choice(name="Green", value="green"),
    app_commands.Choice(name="Gold", value="gold"), app_commands.Choice(name="Orange", value="orange"),
    app_commands.Choice(name="Purple", value="purple"), app_commands.Choice(name="White", value="white"),
    app_commands.Choice(name="Black", value="black"),
]
PING_CHOICES = [
    app_commands.Choice(name="None", value="none"), app_commands.Choice(name="@here", value="@here"),
    app_commands.Choice(name="@everyone", value="@everyone"), app_commands.Choice(name="Class-D", value="1233139781823627465"),
    app_commands.Choice(name="Class-E", value="1233139781823627466"), app_commands.Choice(name="Foundation Personnel", value="1233139781823627469"),
    app_commands.Choice(name="Executive Personnel", value="1233139781823627473"),
    app_commands.Choice(name="Department Director", value="1246963191699734569"),
    app_commands.Choice(name="Site Director", value="1233139781840670742"), app_commands.Choice(name="O5 Council", value="1233139781840670743"),
]

# --- PERMISSION CHECKS ---
def has_any_role(required_roles: List[str]):
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member): return False
        user_role_ids = {str(role.id) for role in interaction.user.roles}
        return any(role_id in user_role_ids for role_id in required_roles)
    return app_commands.check(predicate)

# --- HELPER FUNCTIONS ---
def get_discord_color(color_name: str) -> discord.Color:
    color_map = {"red": discord.Color.red(), "blue": discord.Color.blue(), "green": discord.Color.green(), "gold": discord.Color.gold(), "orange": discord.Color.orange(), "purple": discord.Color.purple(), "white": discord.Color.from_rgb(255, 255, 255), "black": discord.Color.from_rgb(0, 0, 0), "default": discord.Color.blurple()}
    return color_map.get(color_name, discord.Color.default())

def create_button_view(buttons_data):
    if not buttons_data: return None
    view = discord.ui.View()
    for button in buttons_data:
        view.add_item(discord.ui.Button(label=button['label'], style=discord.ButtonStyle.link, url=button['url']))
    return view if view.children else None

# --- DATABASE & BOT EVENTS ---
async def setup_database():
    try:
        bot.db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with bot.db_pool.acquire() as connection:
            await connection.execute('''
                CREATE TABLE IF NOT EXISTS recruitment_posts (
                    id SERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, name TEXT NOT NULL,
                    title TEXT NOT NULL, details TEXT NOT NULL, image_url TEXT,
                    buttons JSONB, ping_role TEXT, color TEXT, UNIQUE(guild_id, name)
                );
            ''')
        print("Successfully connected to PostgreSQL and verified table.")
    except Exception as e:
        print(f"Failed to connect to PostgreSQL: {e}")
        bot.db_pool = None

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    await setup_database()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# --- AUTOCOMPLETE FUNCTION ---
async def post_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    if not bot.db_pool: return []
    async with bot.db_pool.acquire() as connection:
        rows = await connection.fetch("SELECT name FROM recruitment_posts WHERE guild_id = $1 AND name ILIKE $2 LIMIT 25", interaction.guild.id, f'%{current}%')
    return [app_commands.Choice(name=row['name'], value=row['name']) for row in rows]

# --- MODALS (FORMS) ---
class AnnounceModal(discord.ui.Modal, title='Create Announcement'):
    def __init__(self, **kwargs):
        super().__init__()
        self.kwargs = kwargs
    
    title_input = discord.ui.TextInput(label='Title', style=discord.TextStyle.short, required=True, max_length=256)
    message_input = discord.ui.TextInput(label='Message', style=discord.TextStyle.paragraph, required=True, max_length=4000)

    async def on_submit(self, interaction: discord.Interaction):
        announcement_channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if not announcement_channel: return await interaction.response.send_message("Error: Announcement channel not found.", ephemeral=True)
        
        embed_color = get_discord_color(self.kwargs.get('color') or "default")
        embed = discord.Embed(title=self.title_input.value, description=self.message_input.value, color=embed_color, timestamp=datetime.datetime.utcnow())
        
        if self.kwargs.get('image_url'): embed.set_image(url=self.kwargs['image_url'])
        if self.kwargs.get('thumbnail_url'): embed.set_thumbnail(url=self.kwargs['thumbnail_url'])
        
        footer = self.kwargs.get('footer_text') or f"Announcement by {interaction.user.display_name}"
        embed.set_footer(text=footer)
        
        buttons_data = []
        if self.kwargs.get('button1_text') and self.kwargs.get('button1_url'):
            buttons_data.append({"label": self.kwargs['button1_text'], "url": self.kwargs['button1_url']})
        if self.kwargs.get('button2_text') and self.kwargs.get('button2_url'):
            buttons_data.append({"label": self.kwargs['button2_text'], "url": self.kwargs['button2_url']})
        
        view = create_button_view(buttons_data)
        await announcement_channel.send(embed=embed, view=view)
        await interaction.response.send_message("Announcement has been sent!", ephemeral=True)

        ping_role = self.kwargs.get('ping_role')
        if ping_role and ping_role != "none":
            content = ping_role
            if ping_role.isdigit(): content = f"<@&{ping_role}>"
            await announcement_channel.send(content, allowed_mentions=discord.AllowedMentions.all())

class SaveRecruitmentModal(discord.ui.Modal, title='Save Recruitment Post'):
    def __init__(self, **kwargs):
        super().__init__()
        self.kwargs = kwargs
    
    name_input = discord.ui.TextInput(label='Save Name', style=discord.TextStyle.short, required=True, placeholder="A short, memorable name (e.g., md-recruitment)")
    title_input = discord.ui.TextInput(label='Title', style=discord.TextStyle.short, required=True, max_length=256)
    details_input = discord.ui.TextInput(label='Details', style=discord.TextStyle.paragraph, required=True, max_length=4000)

    async def on_submit(self, interaction: discord.Interaction):
        if not bot.db_pool: return await interaction.response.send_message("Error: Database is not connected.", ephemeral=True)
        name = self.name_input.value.lower().strip()
        buttons = []
        if self.kwargs.get('button1_text') and self.kwargs.get('button1_url'): buttons.append({"label": self.kwargs['button1_text'], "url": self.kwargs['button1_url']})
        if self.kwargs.get('button2_text') and self.kwargs.get('button2_url'): buttons.append({"label": self.kwargs['button2_text'], "url": self.kwargs['button2_url']})
        
        buttons_json = json.dumps(buttons)
        ping_value = self.kwargs.get('ping_role') if self.kwargs.get('ping_role') != "none" else None
        color_value = self.kwargs.get('color') or "blue"
        
        try:
            async with bot.db_pool.acquire() as connection:
                await connection.execute('''
                    INSERT INTO recruitment_posts (guild_id, name, title, details, image_url, buttons, ping_role, color) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (guild_id, name) DO UPDATE SET title = EXCLUDED.title, details = EXCLUDED.details, image_url = EXCLUDED.image_url, buttons = EXCLUDED.buttons, ping_role = EXCLUDED.ping_role, color = EXCLUDED.color;
                ''', interaction.guild.id, name, self.title_input.value, self.details_input.value, self.kwargs.get('image_url'), buttons_json, ping_value, color_value)
            await interaction.response.send_message(f"✅ Recruitment post saved/updated with the name: `{name}`", ephemeral=True)
        except Exception as e:
            print(f"Error saving post: {e}")
            await interaction.response.send_message("An error occurred while saving the post.", ephemeral=True)

class EditRecruitmentModal(discord.ui.Modal, title='Edit Recruitment Post'):
    def __init__(self, name: str, post_data: asyncpg.Record, **kwargs):
        super().__init__()
        self.name = name
        self.post_data = post_data
        self.kwargs = kwargs
        
        self.title_input = discord.ui.TextInput(label='Title', style=discord.TextStyle.short, required=True, max_length=256, default=post_data['title'])
        self.details_input = discord.ui.TextInput(label='Details', style=discord.TextStyle.paragraph, required=True, max_length=4000, default=post_data['details'])
        self.add_item(self.title_input)
        self.add_item(self.details_input)
        
    async def on_submit(self, interaction: discord.Interaction):
        if not bot.db_pool: return await interaction.response.send_message("Error: Database is not connected.", ephemeral=True)
        
        new_image_url = self.kwargs.get('image_url') or self.post_data['image_url']
        buttons_list = json.loads(self.post_data.get("buttons", "[]"))
        if len(buttons_list) == 0: buttons_list = [{}, {}]
        elif len(buttons_list) == 1: buttons_list.append({})

        buttons_list[0] = {"label": self.kwargs.get('button1_text') or buttons_list[0].get('label'), "url": self.kwargs.get('button1_url') or buttons_list[0].get('url')}
        buttons_list[1] = {"label": self.kwargs.get('button2_text') or buttons_list[1].get('label'), "url": self.kwargs.get('button2_url') or buttons_list[1].get('url')}
        buttons_list = [b for b in buttons_list if b.get('label') and b.get('url')]
        
        buttons_json = json.dumps(buttons_list)
        new_ping_role = self.kwargs.get('ping_role')
        if new_ping_role is None: new_ping_role = self.post_data['ping_role']
        if new_ping_role == "none": new_ping_role = None

        new_color = self.kwargs.get('color') or self.post_data['color']
        
        async with bot.db_pool.acquire() as connection:
            await connection.execute('''
                UPDATE recruitment_posts SET title = $1, details = $2, image_url = $3, buttons = $4, ping_role = $5, color = $6
                WHERE guild_id = $7 AND name = $8
            ''', self.title_input.value, self.details_input.value, new_image_url, buttons_json, new_ping_role, new_color, interaction.guild.id, self.name)
        await interaction.response.send_message(f"✅ Successfully edited recruitment post: `{self.name}`", ephemeral=True)

# --- APPLICATION & NOTIFICATION COMMANDS ---

@bot.tree.command(name="notify", description="Sends a Class-E or Blacklist notification to a user.")
@has_any_role(NOTIFY_AND_APP_ROLES)
@app_commands.describe(user="The user to notify.", type="The type of notification.", reason="The reason for this action.", duration="The duration of this action.", trello_card="Link to the user's Trello card.", appealable="Whether the user can appeal this action.", notifier_department="The department issuing the notification.")
@app_commands.choices(
    type=[app_commands.Choice(name="Class-E", value="Class-E"), app_commands.Choice(name="Blacklist", value="Blacklist")],
    notifier_department=[app_commands.Choice(name="IA", value="IA"), app_commands.Choice(name="EC", value="EC")]
)
async def notify(interaction: discord.Interaction, user: discord.Member, type: app_commands.Choice[str], reason: str, duration: str, trello_card: str, appealable: bool, notifier_department: app_commands.Choice[str]):
    embed = discord.Embed(title=f"Notification of {type.name}", color=discord.Color.orange(), timestamp=datetime.datetime.utcnow())
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
    if not match: return await interaction.response.send_message("Invalid message link format.", ephemeral=True)
    
    channel_id, message_id = map(int, match.groups())
    
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        message = await channel.fetch_message(message_id)
    except (discord.NotFound, discord.Forbidden):
        return await interaction.response.send_message("Could not find the application message. Please check the link.", ephemeral=True)

    reaction = "✅" if accepted else "❌"
    try: await message.add_reaction(reaction)
    except discord.Forbidden: print(f"Could not add reaction to message {message_id}. Missing permissions.")

    app_level = ""
    if "level-1" in channel.name.lower(): app_level = "Level-1 "
    elif "level-2" in channel.name.lower(): app_level = "Level-2 "
    elif "level-3" in channel.name.lower(): app_level = "Level-3 "

    status = "Accepted" if accepted else "Denied"
    color = discord.Color.green() if accepted else discord.Color.red()
    
    embed = discord.Embed(title=f"{applicant.display_name} | {app_level}Application {status}", color=color, timestamp=datetime.datetime.utcnow())
    embed.description = f"{applicant.mention}'s {app_level.lower()}application has been **{status}**."
    embed.add_field(name="Reason", value=details, inline=False)
    embed.set_footer(text=f"Processed by {interaction.user.display_name}")

    await results_channel.send(embed=embed)
    await interaction.response.send_message(f"Application for {applicant.mention} has been processed.", ephemeral=True)

@bot.tree.command(name="accept", description="Accept a user's application.")
@has_any_role(NOTIFY_AND_APP_ROLES)
@app_commands.describe(message_link="Link to the application message.", applicant="The user who applied.", reason="Optional reason for acceptance.")
async def accept(interaction: discord.Interaction, message_link: str, applicant: discord.Member, reason: str = "Not provided."):
    await process_application(interaction, message_link, applicant, accepted=True, details=reason)

@bot.tree.command(name="reject", description="Reject a user's application.")
@has_any_role(NOTIFY_AND_APP_ROLES)
@app_commands.describe(message_link="Link to the application message.", applicant="The user who applied.", reason="Optional reason for rejection.")
async def reject(interaction: discord.Interaction, message_link: str, applicant: discord.Member, reason: str = "Not provided."):
    await process_application(interaction, message_link, applicant, accepted=False, details=reason)

# --- CORE BOT COMMANDS ---

@bot.tree.command(name="ssu", description="Announce a Server Start Up (SSU).")
@app_commands.checks.cooldown(1, 600, key=lambda i: i.guild_id)
@has_any_role(EP_AND_ABOVE_ROLES)
async def ssu(interaction: discord.Interaction):
    ssu_channel = bot.get_channel(SSU_CHANNEL_ID)
    if not ssu_channel: return await interaction.response.send_message("Error: SSU channel not found.", ephemeral=True)
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Join Game", style=discord.ButtonStyle.link, url=GAME_LINK))
    embed = discord.Embed(title="🚀 Server Start Up (SSU) Hosted!", description=f"A Server Start Up has been started by {interaction.user.mention}. Join us now!", color=discord.Color.green(), timestamp=datetime.datetime.utcnow())
    embed.set_footer(text=f"Hosted by {interaction.user.display_name}")
    await ssu_channel.send(content="@everyone", embed=embed, view=view)
    await interaction.response.send_message("SSU announcement has been sent!", ephemeral=True)

@bot.tree.command(name="announce", description="Create a server announcement using a form.")
@has_any_role(DD_AND_ABOVE_ROLES)
@app_commands.choices(color=COLOR_CHOICES, ping_role=PING_CHOICES)
@app_commands.describe(color="The color of the embed sidebar.", image_url="URL for a large image.", thumbnail_url="URL for a small top-right image.", footer_text="Custom footer text.", button1_text="Text for the first button.", button1_url="URL for the first button.", button2_text="Text for the second button.", button2_url="URL for the second button.", ping_role="Role to ping after sending.")
async def announce(interaction: discord.Interaction, color: app_commands.Choice[str] = None, image_url: str = None, thumbnail_url: str = None, footer_text: str = None, button1_text: str = None, button1_url: str = None, button2_text: str = None, button2_url: str = None, ping_role: app_commands.Choice[str] = None):
    modal_kwargs = {
        'color': color.value if color else None, 'image_url': image_url, 'thumbnail_url': thumbnail_url,
        'footer_text': footer_text, 'button1_text': button1_text, 'button1_url': button1_url,
        'button2_text': button2_text, 'button2_url': button2_url,
        'ping_role': ping_role.value if ping_role else None
    }
    await interaction.response.send_modal(AnnounceModal(**modal_kwargs))

@bot.tree.command(name="saverecruitmentpost", description="Saves a recruitment post using a form.")
@has_any_role(EP_AND_ABOVE_ROLES)
@app_commands.choices(ping_role=PING_CHOICES, color=COLOR_CHOICES)
@app_commands.describe(image_url="URL for an image.", button1_text="Text for the first button.", button1_url="URL for the first button.", button2_text="Text for the second button.", button2_url="URL for the second button.", ping_role="Role to save for pinging.", color="Color for the embed.")
async def saverecruitmentpost(interaction: discord.Interaction, image_url: str = None, button1_text: str = None, button1_url: str = None, button2_text: str = None, button2_url: str = None, ping_role: app_commands.Choice[str] = None, color: app_commands.Choice[str] = None):
    modal_kwargs = {
        'image_url': image_url, 'button1_text': button1_text, 'button1_url': button1_url,
        'button2_text': button2_text, 'button2_url': button2_url,
        'ping_role': ping_role.value if ping_role else None,
        'color': color.value if color else None
    }
    await interaction.response.send_modal(SaveRecruitmentModal(**modal_kwargs))

@bot.tree.command(name="editrecruitmentpost", description="Edits a saved recruitment post using a form.")
@has_any_role(EP_AND_ABOVE_ROLES)
@app_commands.autocomplete(name=post_autocomplete)
@app_commands.choices(ping_role=PING_CHOICES, color=COLOR_CHOICES)
@app_commands.describe(name="The name of the post to edit.", image_url="New image URL.", button1_text="New text for button 1.", button1_url="New URL for button 1.", button2_text="New text for button 2.", button2_url="New URL for button 2.", ping_role="New ping role.", color="New embed color.")
async def editrecruitmentpost(interaction: discord.Interaction, name: str, image_url: str = None, button1_text: str = None, button1_url: str = None, button2_text: str = None, button2_url: str = None, ping_role: app_commands.Choice[str] = None, color: app_commands.Choice[str] = None):
    if not bot.db_pool: return await interaction.response.send_message("Error: Database is not connected.", ephemeral=True)
    async with bot.db_pool.acquire() as connection:
        post_data = await connection.fetchrow('SELECT * FROM recruitment_posts WHERE guild_id = $1 AND name = $2', interaction.guild.id, name.lower().strip())
    if not post_data: return await interaction.response.send_message(f"Error: No post found with the name '{name}'.", ephemeral=True)
    
    modal_kwargs = {
        'image_url': image_url, 'button1_text': button1_text, 'button1_url': button1_url,
        'button2_text': button2_text, 'button2_url': button2_url,
        'ping_role': ping_role.value if ping_role else None,
        'color': color.value if color else None
    }
    await interaction.response.send_modal(EditRecruitmentModal(name=name.lower().strip(), post_data=post_data, **modal_kwargs))

@bot.tree.command(name="repost", description="Posts a saved recruitment announcement from the database.")
@has_any_role(EP_AND_ABOVE_ROLES)
@app_commands.autocomplete(name=post_autocomplete)
@app_commands.choices(ping_override=PING_CHOICES)
async def repost(interaction: discord.Interaction, name: str, ping_override: app_commands.Choice[str] = None):
    if not bot.db_pool: return await interaction.response.send_message("Error: Database is not connected.", ephemeral=True)
    recruitment_channel = bot.get_channel(RECRUITMENT_CHANNEL_ID)
    if not recruitment_channel: return await interaction.response.send_message("Error: Recruitment channel not found.", ephemeral=True)
    async with bot.db_pool.acquire() as connection:
        post_data = await connection.fetchrow('SELECT * FROM recruitment_posts WHERE guild_id = $1 AND name = $2', interaction.guild.id, name.lower().strip())
    if not post_data: return await interaction.response.send_message(f"Error: No post found with the name '{name}'.", ephemeral=True)
    embed_color = get_discord_color(post_data.get("color") or "blue")
    embed = discord.Embed(title=post_data["title"], description=post_data["details"], color=embed_color, timestamp=datetime.datetime.utcnow())
    embed.set_footer(text=f"Posted by {interaction.user.display_name}")
    if post_data.get("image_url"): embed.set_image(url=post_data["image_url"])
    buttons_list = json.loads(post_data.get("buttons", "[]"))
    view = create_button_view(buttons_list)
    await recruitment_channel.send(embed=embed, view=view)
    await interaction.response.send_message(f"Successfully reposted '{name}'!", ephemeral=True)
    ping_value = None
    if ping_override:
        if ping_override.value != "none": ping_value = ping_override.value
    elif post_data.get("ping_role"):
        ping_value = post_data["ping_role"]
    if ping_value:
        content = ping_value
        if ping_value.isdigit(): content = f"<@&{ping_value}>"
        await recruitment_channel.send(content, allowed_mentions=discord.AllowedMentions.all())

@bot.tree.command(name="testrepost", description="Previews a saved recruitment announcement privately.")
@has_any_role(EP_AND_ABOVE_ROLES)
@app_commands.autocomplete(name=post_autocomplete)
async def testrepost(interaction: discord.Interaction, name: str):
    if not bot.db_pool: return await interaction.response.send_message("Error: Database is not connected.", ephemeral=True)
    async with bot.db_pool.acquire() as connection:
        post_data = await connection.fetchrow('SELECT * FROM recruitment_posts WHERE guild_id = $1 AND name = $2', interaction.guild.id, name.lower().strip())
    if not post_data: return await interaction.response.send_message(f"Error: No post found with the name '{name}'.", ephemeral=True)
    
    embed_color = get_discord_color(post_data.get("color") or "blue")
    embed = discord.Embed(title=post_data["title"], description=post_data["details"], color=embed_color, timestamp=datetime.datetime.utcnow())
    embed.set_footer(text=f"Posted by {interaction.user.display_name}")
    if post_data.get("image_url"): embed.set_image(url=post_data["image_url"])
    
    buttons_list = json.loads(post_data.get("buttons", "[]"))
    view = create_button_view(buttons_list)

    ping_value = post_data.get("ping_role")
    preview_text = "This is a preview. No pings will be sent."
    if ping_value:
        ping_name = ping_value 
        for choice in PING_CHOICES:
            if choice.value == ping_value:
                ping_name = choice.name
                break
        preview_text = f"This is a preview. When posted, this will ping **{ping_name}**."
        
    await interaction.response.send_message(content=preview_text, embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="deleterecruitmentpost", description="Deletes a saved recruitment post.")
@has_any_role(EP_AND_ABOVE_ROLES)
@app_commands.autocomplete(name=post_autocomplete)
async def deleterecruitmentpost(interaction: discord.Interaction, name: str):
    if not bot.db_pool: return await interaction.response.send_message("Error: Database is not connected.", ephemeral=True)
    async with bot.db_pool.acquire() as connection:
        result = await connection.execute('DELETE FROM recruitment_posts WHERE guild_id = $1 AND name = $2', interaction.guild.id, name.lower().strip())
    if result == "DELETE 1":
        await interaction.response.send_message(f"✅ Successfully deleted recruitment post: `{name}`", ephemeral=True)
    else:
        await interaction.response.send_message(f"Error: No post found with the name '{name}' to delete.", ephemeral=True)

# --- ERROR HANDLING ---
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        time_left = str(datetime.timedelta(seconds=int(error.retry_after)))
        await interaction.response.send_message(f"This command is on cooldown for everyone. Please try again in **{time_left}**.", ephemeral=True)
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
    if not BOT_TOKEN: print("Error: BOT_TOKEN is not set in the environment variables.")
    elif not DATABASE_URL: print("Error: DATABASE_URL is not set in the environment variables.")
    else: bot.run(BOT_TOKEN)

