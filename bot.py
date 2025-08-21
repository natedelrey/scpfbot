import discord
from discord.ext import commands
from discord import app_commands
import datetime
import json
import os
import asyncpg
from dotenv import load_dotenv
from typing import List

# --- CONFIGURATION ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
try:
    ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID"))
    RECRUITMENT_CHANNEL_ID = int(os.getenv("RECRUITMENT_CHANNEL_ID"))
    SSU_CHANNEL_ID = int(os.getenv("SSU_CHANNEL_ID"))
except (TypeError, ValueError):
    print("Error: Channel IDs are not set correctly in your environment variables.")
    exit()
GAME_LINK = os.getenv("GAME_LINK", "https://www.roblox.com/games/17371095768/SCP-Lambda")

# --- ROLE IDs FOR PERMISSIONS ---
# Note: These are stored as strings to match Discord's API results
EP_AND_ABOVE_ROLES = [
    "1233139781823627473", # Executive Personnel
    "1246963191699734569", # Department Director
    "1233139781840670742", # Site Director
    "1233139781840670743", # O5 Council
    "1233139781840670746", # Other High Rank
]
DD_AND_ABOVE_ROLES = [
    "1246963191699734569", # Department Director
    "1233139781840670742", # Site Director
    "1233139781840670743", # O5 Council
    "1233139781840670746", # Other High Rank
]

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True # Required for potential future features
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
    """Custom check to see if a user has any of the specified roles."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        user_role_ids = {str(role.id) for role in interaction.user.roles}
        return any(role_id in user_role_ids for role_id in required_roles)
    return app_commands.check(predicate)

# --- HELPER FUNCTIONS & CLASSES ---

def get_discord_color(color_name: str) -> discord.Color:
    color_map = {"red": discord.Color.red(), "blue": discord.Color.blue(), "green": discord.Color.green(), "gold": discord.Color.gold(), "orange": discord.Color.orange(), "purple": discord.Color.purple(), "white": discord.Color.from_rgb(255, 255, 255), "black": discord.Color.from_rgb(0, 0, 0), "default": discord.Color.blurple()}
    return color_map.get(color_name, discord.Color.default())

def create_button_view(buttons_data):
    if not buttons_data: return None
    view = discord.ui.View()
    for button in buttons_data:
        view.add_item(discord.ui.Button(label=button['label'], style=discord.ButtonStyle.link, url=button['url']))
    return view if view.children else None

class FormatModal(discord.ui.Modal, title='Text Formatter'):
    text_to_format = discord.ui.TextInput(label='Paste your multi-line text here', style=discord.TextStyle.paragraph, placeholder='Your announcement text...\n...with multiple lines...', required=True, max_length=2000)
    async def on_submit(self, interaction: discord.Interaction):
        formatted_text = self.text_to_format.value.replace('\n', '\\n')
        await interaction.response.send_message(f"**Formatted Text (copy this):**\n```\n{formatted_text}\n```", ephemeral=True)

# --- DATABASE & BOT EVENTS ---

async def setup_database():
    try:
        bot.db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with bot.db_pool.acquire() as connection:
            await connection.execute('''
                CREATE TABLE IF NOT EXISTS recruitment_posts (
                    id SERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, name TEXT NOT NULL,
                    title TEXT NOT NULL, details TEXT NOT NULL, image_url TEXT,
                    buttons JSONB, ping_role TEXT, UNIQUE(guild_id, name)
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
        query = "SELECT name FROM recruitment_posts WHERE guild_id = $1 AND name ILIKE $2 LIMIT 25"
        rows = await connection.fetch(query, interaction.guild.id, f'%{current}%')
    return [app_commands.Choice(name=row['name'], value=row['name']) for row in rows]

# --- GENERAL COMMANDS ---

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

@bot.tree.command(name="announce", description="Create a highly customizable server announcement.")
@has_any_role(DD_AND_ABOVE_ROLES)
@app_commands.describe(title="The title of the announcement.", message="The main content. Use '\\n' for new lines.")
@app_commands.choices(color=COLOR_CHOICES, ping_role=PING_CHOICES)
async def announce(interaction: discord.Interaction, title: str, message: str, color: app_commands.Choice[str] = None, image_url: str = None, thumbnail_url: str = None, footer_text: str = None, button1_text: str = None, button1_url: str = None, button2_text: str = None, button2_url: str = None, ping_role: app_commands.Choice[str] = None):
    announcement_channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    if not announcement_channel: return await interaction.response.send_message("Error: Announcement channel not found.", ephemeral=True)
    embed_color = get_discord_color(color.value if color else "default")
    embed = discord.Embed(title=title, description=message.replace("\\n", "\n"), color=embed_color, timestamp=datetime.datetime.utcnow())
    if image_url: embed.set_image(url=image_url)
    if thumbnail_url: embed.set_thumbnail(url=thumbnail_url)
    footer = footer_text if footer_text else f"Announcement by {interaction.user.display_name}"
    embed.set_footer(text=footer)
    buttons_data = []
    if button1_text and button1_url: buttons_data.append({"label": button1_text, "url": button1_url})
    if button2_text and button2_url: buttons_data.append({"label": button2_text, "url": button2_url})
    view = create_button_view(buttons_data)
    await announcement_channel.send(embed=embed, view=view)
    await interaction.response.send_message("Announcement has been sent!", ephemeral=True)

    # Handle the ping
    if ping_role and ping_role.value != "none":
        ping_value = ping_role.value
        content = ping_value
        if ping_value.isdigit(): # It's a role ID
            content = f"<@&{ping_value}>"
        await announcement_channel.send(content, allowed_mentions=discord.AllowedMentions.all())

# --- RECRUITMENT POST MANAGEMENT COMMANDS ---

@bot.tree.command(name="formattext", description="Formats multi-line text with '\\n' for use in other commands.")
async def formattext(interaction: discord.Interaction):
    await interaction.response.send_modal(FormatModal())

@bot.tree.command(name="saverecruitmentpost", description="Saves a recruitment post template to the database.")
@has_any_role(EP_AND_ABOVE_ROLES)
@app_commands.describe(name="A short, unique name to save this post as (e.g., 'md-recruitment').")
@app_commands.choices(ping_role=PING_CHOICES)
async def saverecruitmentpost(interaction: discord.Interaction, name: str, title: str, details: str, image_url: str = None, button1_text: str = None, button1_url: str = None, button2_text: str = None, button2_url: str = None, ping_role: app_commands.Choice[str] = None):
    if not bot.db_pool: return await interaction.response.send_message("Error: Database is not connected.", ephemeral=True)
    name = name.lower().strip()
    buttons = []
    if button1_text and button1_url: buttons.append({"label": button1_text, "url": button1_url})
    if button2_text and button2_url: buttons.append({"label": button2_text, "url": button2_url})
    buttons_json = json.dumps(buttons)
    ping_value = ping_role.value if ping_role and ping_role.value != "none" else None
    try:
        async with bot.db_pool.acquire() as connection:
            await connection.execute('''
                INSERT INTO recruitment_posts (guild_id, name, title, details, image_url, buttons, ping_role) VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (guild_id, name) DO UPDATE SET title = EXCLUDED.title, details = EXCLUDED.details, image_url = EXCLUDED.image_url, buttons = EXCLUDED.buttons, ping_role = EXCLUDED.ping_role;
            ''', interaction.guild.id, name, title, details, image_url, buttons_json, ping_value)
        await interaction.response.send_message(f"✅ Recruitment post saved/updated with the name: `{name}`", ephemeral=True)
    except Exception as e:
        print(f"Error saving post: {e}")
        await interaction.response.send_message("An error occurred while saving the post.", ephemeral=True)

@bot.tree.command(name="editrecruitmentpost", description="Edits an existing saved recruitment post.")
@has_any_role(EP_AND_ABOVE_ROLES)
@app_commands.autocomplete(name=post_autocomplete)
@app_commands.describe(name="The name of the post to edit.")
@app_commands.choices(ping_role=PING_CHOICES)
async def editrecruitmentpost(interaction: discord.Interaction, name: str, title: str = None, details: str = None, image_url: str = None, button1_text: str = None, button1_url: str = None, button2_text: str = None, button2_url: str = None, ping_role: app_commands.Choice[str] = None):
    if not bot.db_pool: return await interaction.response.send_message("Error: Database is not connected.", ephemeral=True)
    async with bot.db_pool.acquire() as connection:
        post_data = await connection.fetchrow('SELECT * FROM recruitment_posts WHERE guild_id = $1 AND name = $2', interaction.guild.id, name.lower().strip())
        if not post_data: return await interaction.response.send_message(f"Error: No post found with the name '{name}'.", ephemeral=True)
        new_title = title if title is not None else post_data['title']
        new_details = details if details is not None else post_data['details']
        new_image_url = image_url if image_url is not None else post_data['image_url']
        buttons_list = json.loads(post_data.get("buttons", "[]"))
        if button1_text is not None or button1_url is not None:
             buttons_list[0] = {"label": button1_text or buttons_list[0]['label'], "url": button1_url or buttons_list[0]['url']}
        if button2_text is not None or button2_url is not None:
             buttons_list[1] = {"label": button2_text or buttons_list[1]['label'], "url": button2_url or buttons_list[1]['url']}
        buttons_json = json.dumps(buttons_list)
        new_ping_role = ping_role.value if ping_role else post_data['ping_role']
        if ping_role and ping_role.value == "none": new_ping_role = None
        await connection.execute('''
            UPDATE recruitment_posts SET title = $1, details = $2, image_url = $3, buttons = $4, ping_role = $5
            WHERE guild_id = $6 AND name = $7
        ''', new_title, new_details, new_image_url, buttons_json, new_ping_role, interaction.guild.id, name.lower().strip())
    await interaction.response.send_message(f"✅ Successfully edited recruitment post: `{name}`", ephemeral=True)

@bot.tree.command(name="repost", description="Posts a saved recruitment announcement from the database.")
@has_any_role(EP_AND_ABOVE_ROLES)
@app_commands.autocomplete(name=post_autocomplete)
@app_commands.describe(name="The name of the saved post to send.", ping_override="Optional: Choose a different ping for this time only.")
@app_commands.choices(ping_override=PING_CHOICES)
async def repost(interaction: discord.Interaction, name: str, ping_override: app_commands.Choice[str] = None):
    if not bot.db_pool: return await interaction.response.send_message("Error: Database is not connected.", ephemeral=True)
    recruitment_channel = bot.get_channel(RECRUITMENT_CHANNEL_ID)
    if not recruitment_channel: return await interaction.response.send_message("Error: Recruitment channel not found.", ephemeral=True)
    async with bot.db_pool.acquire() as connection:
        post_data = await connection.fetchrow('SELECT * FROM recruitment_posts WHERE guild_id = $1 AND name = $2', interaction.guild.id, name.lower().strip())
    if not post_data: return await interaction.response.send_message(f"Error: No post found with the name '{name}'.", ephemeral=True)
    embed = discord.Embed(title=post_data["title"], description=post_data["details"].replace("\\n", "\n"), color=discord.Color.blue(), timestamp=datetime.datetime.utcnow())
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

@bot.tree.command(name="deleterecruitmentpost", description="Deletes a saved recruitment post.")
@has_any_role(EP_AND_ABOVE_ROLES)
@app_commands.autocomplete(name=post_autocomplete)
@app_commands.describe(name="The name of the post to delete.")
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
