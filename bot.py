import discord
from discord.ext import commands
from discord import app_commands
import datetime
import json
import os
import asyncpg
from dotenv import load_dotenv

# --- CONFIGURATION ---
# Load variables from .env file for local development
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Get channel IDs from environment variables and convert them to integers
try:
    ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID"))
    RECRUITMENT_CHANNEL_ID = int(os.getenv("RECRUITMENT_CHANNEL_ID"))
    SSU_CHANNEL_ID = int(os.getenv("SSU_CHANNEL_ID"))
except (TypeError, ValueError):
    print("Error: Channel IDs are not set correctly in your environment variables.")
    exit()

GAME_LINK = os.getenv("GAME_LINK", "https://www.roblox.com/games/17371095768/SCP-Lambda")

# --- BOT SETUP ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
bot.db_pool = None # To hold the database connection pool

# --- HELPER FUNCTIONS ---

def create_button_view(buttons_data):
    """Creates a view with buttons from a list of dictionaries."""
    if not buttons_data:
        return None
    view = discord.ui.View()
    for button in buttons_data:
        view.add_item(discord.ui.Button(label=button['label'], style=discord.ButtonStyle.link, url=button['url']))
    return view if len(view.children) > 0 else None

# --- DATABASE SETUP & BOT EVENTS ---

async def setup_database():
    """Connects to the database and creates the necessary table if it doesn't exist."""
    try:
        bot.db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with bot.db_pool.acquire() as connection:
            await connection.execute('''
                CREATE TABLE IF NOT EXISTS recruitment_posts (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    details TEXT NOT NULL,
                    image_url TEXT,
                    buttons JSONB,
                    UNIQUE(guild_id, name)
                );
            ''')
        print("Successfully connected to PostgreSQL and verified table.")
    except Exception as e:
        print(f"Failed to connect to PostgreSQL: {e}")
        bot.db_pool = None # Ensure pool is None if connection fails

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    await setup_database()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# --- SLASH COMMANDS ---

# 1. SSU Command
@bot.tree.command(name="ssu", description="Announce a Server Start Up (SSU).")
@app_commands.checks.cooldown(1, 600, key=lambda i: i.guild_id)
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
        timestamp=datetime.datetime.utcnow()
    )
    embed.set_footer(text=f"Hosted by {interaction.user.display_name}")
    await ssu_channel.send(content="@everyone", embed=embed, view=view)
    await interaction.response.send_message("SSU announcement has been sent!", ephemeral=True)

# 2. Save Recruitment Post Command
@bot.tree.command(name="saverecruitmentpost", description="Saves a recruitment post template to the database.")
@app_commands.describe(
    name="A short, unique name to save this post as (e.g., 'md-recruitment').",
    title="The title of the recruitment post.",
    details="The main body of the message. Use '\\n' for new lines."
)
async def saverecruitmentpost(interaction: discord.Interaction, name: str, title: str, details: str, image_url: str = None, button1_text: str = None, button1_url: str = None, button2_text: str = None, button2_url: str = None):
    if not bot.db_pool:
        return await interaction.response.send_message("Error: Database is not connected.", ephemeral=True)
    
    name = name.lower().strip()
    buttons = []
    if button1_text and button1_url:
        buttons.append({"label": button1_text, "url": button1_url})
    if button2_text and button2_url:
        buttons.append({"label": button2_text, "url": button2_url})
    
    # Convert buttons list to a JSON string for storing in the database
    buttons_json = json.dumps(buttons)

    try:
        async with bot.db_pool.acquire() as connection:
            await connection.execute(
                '''
                INSERT INTO recruitment_posts (guild_id, name, title, details, image_url, buttons)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (guild_id, name) DO UPDATE SET
                    title = EXCLUDED.title,
                    details = EXCLUDED.details,
                    image_url = EXCLUDED.image_url,
                    buttons = EXCLUDED.buttons;
                ''',
                interaction.guild.id, name, title, details, image_url, buttons_json
            )
        await interaction.response.send_message(f"✅ Recruitment post saved/updated with the name: `{name}`", ephemeral=True)
    except Exception as e:
        print(f"Error saving post: {e}")
        await interaction.response.send_message("An error occurred while saving the post.", ephemeral=True)

# 3. Repost Command
@bot.tree.command(name="repost", description="Posts a saved recruitment announcement from the database.")
@app_commands.describe(name="The name of the saved post you want to send.")
async def repost(interaction: discord.Interaction, name: str):
    if not bot.db_pool:
        return await interaction.response.send_message("Error: Database is not connected.", ephemeral=True)
    
    recruitment_channel = bot.get_channel(RECRUITMENT_CHANNEL_ID)
    if not recruitment_channel:
        return await interaction.response.send_message("Error: Recruitment channel not found.", ephemeral=True)

    async with bot.db_pool.acquire() as connection:
        post_data = await connection.fetchrow(
            'SELECT * FROM recruitment_posts WHERE guild_id = $1 AND name = $2',
            interaction.guild.id, name.lower().strip()
        )

    if not post_data:
        return await interaction.response.send_message(f"Error: No recruitment post found with the name '{name}'.", ephemeral=True)
    
    embed = discord.Embed(
        title=post_data["title"],
        description=post_data["details"].replace("\\n", "\n"),
        color=discord.Color.blue(),
        timestamp=datetime.datetime.utcnow()
    )
    embed.set_footer(text=f"Posted by {interaction.user.display_name}")
    
    if post_data.get("image_url"):
        embed.set_image(url=post_data["image_url"])
        
    # The 'buttons' column is stored as a JSON string, so we load it back into a Python list
    buttons_list = json.loads(post_data.get("buttons", "[]"))
    view = create_button_view(buttons_list)

    await recruitment_channel.send(embed=embed, view=view)
    await interaction.response.send_message(f"Successfully reposted '{name}'!", ephemeral=True)

# Autocomplete for the /repost command
@repost.autocomplete('name')
async def repost_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    if not bot.db_pool:
        return []
    
    async with bot.db_pool.acquire() as connection:
        query = "SELECT name FROM recruitment_posts WHERE guild_id = $1 AND name ILIKE $2 LIMIT 25"
        rows = await connection.fetch(query, interaction.guild.id, f'%{current}%')
    
    return [app_commands.Choice(name=row['name'], value=row['name']) for row in rows]

# 4. Announce Command
@bot.tree.command(name="announce", description="Create a highly customizable server announcement.")
@app_commands.describe(
    title="The title of the announcement.",
    message="The main content. Use '\\n' for new lines."
)
async def announce(interaction: discord.Interaction, title: str, message: str, color: str = None, image_url: str = None, thumbnail_url: str = None, footer_text: str = None, button1_text: str = None, button1_url: str = None, button2_text: str = None, button2_url: str = None):
    announcement_channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    if not announcement_channel:
        return await interaction.response.send_message("Error: Announcement channel not found.", ephemeral=True)
    embed_color = discord.Color.default()
    if color:
        try:
            embed_color = discord.Color(int(color.lstrip('#'), 16))
        except ValueError:
            return await interaction.response.send_message("Invalid hex color format.", ephemeral=True)
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

# --- ERROR HANDLING ---
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        time_left = str(datetime.timedelta(seconds=int(error.retry_after)))
        await interaction.response.send_message(f"This command is on cooldown for everyone. Please try again in **{time_left}**.", ephemeral=True)
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
    elif not DATABASE_URL:
        print("Error: DATABASE_URL is not set in the environment variables.")
    else:
        bot.run(BOT_TOKEN)
