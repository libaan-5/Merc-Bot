import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import aiohttp

from keep_alive import keep_alive

keep_alive()


ROBLX_GROUP_ID = 35171555  # <--- replace with your Roblox group ID

RANK_NAME_TO_NUMBER = {
    "Grunt": 2,
    "Recruit": 3,
    "Privateer": 4
}

RANK_CREDIT_REQUIREMENTS = {
    2: 1,
    3: 2,
    4: 3
}


# === Configuration ===
AUTHORIZED_ROLE = "Non Commissioned Officer"
DATA_FILE = "data/user_files.json"

# === Intents and Bot Setup ===
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree  # easier alias

GUILD_ID = 1296570266272665660

# === Ensure Data Directory Exists ===
if not os.path.exists("data"):
    os.makedirs("data")
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

# === Helper Functions ===
def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

async def get_roblox_avatar_url(roblox_id):
    url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={roblox_id}&size=150x150&format=Png&isCircular=false"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data["data"]:
                    return data["data"][0]["imageUrl"]
    return None

def is_authorized(interaction: discord.Interaction) -> bool:
    guild = interaction.guild
    if guild is None:
        return False  # or True, depends on your needs

    # Get the minimum required role by name
    min_role = discord.utils.get(guild.roles, name=AUTHORIZED_ROLE)
    if min_role is None:
        return False

    # Check if user has any role higher than min_role
    return any(role.position > min_role.position for role in interaction.user.roles)



def get_progress_bar(current, maximum, length=10):
    if maximum == 0:
        return "N/A"
    filled_length = int(length * current // maximum)
    bar = "█" * filled_length + "░" * (length - filled_length)
    return f"```{bar} {current}/{maximum} credits```"

# === /viewfile ===
@tree.command(name="viewfile", description="View your own or another member’s file")
@app_commands.describe(user="Optional: user to view (default is yourself)")
async def viewfile(interaction: discord.Interaction, user: discord.Member = None):
    user = user or interaction.user
    data = load_data()

    if str(user.id) not in data:
        await interaction.response.send_message("No file found for this member.", ephemeral=True)
        return

    user_data = data[str(user.id)]
    avatar_url = await get_roblox_avatar_url(user_data["roblox_id"])

    # Resolve last editor mention
    last_editor_id = user_data.get("last_edited_by")
    if last_editor_id is None or last_editor_id == "Unknown":
        last_editor = "Unknown"
    else:
        member = interaction.guild.get_member(int(last_editor_id))
        if member:
            last_editor = member.mention
        else:
            last_editor = f"<@{last_editor_id}>"

    embed = discord.Embed(
        title=f"User File: {user_data['username']}",
        description=f"{user.mention}",
        color=discord.Color.blue()
    )
    embed.add_field(name="Roblox ID", value=user_data["roblox_id"], inline=True)
    embed.add_field(name="Rank", value=user_data["rank"].capitalize(), inline=True)
    embed.add_field(name="Credits", value=str(user_data["credits"]), inline=True)
    embed.add_field(name="Last Edited By", value=last_editor, inline=False)

    rank_num = RANK_NAME_TO_NUMBER.get(user_data["rank"].capitalize())
    required_credits = RANK_CREDIT_REQUIREMENTS.get(rank_num)

    if required_credits is not None:
        progress_bar = get_progress_bar(user_data["credits"], required_credits)
        embed.add_field(name="Progress to Next Promotion", value=progress_bar, inline=False)

        eligible_emoji = "✅" if user_data["credits"] >= required_credits else "❌"
        embed.add_field(name="Eligible for Promotion", value=eligible_emoji, inline=True)

    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    await interaction.response.send_message(embed=embed)

# === /createfile ===
@tree.command(name="createfile", description="Create a user file", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(member="Discord member", roblox_id="Roblox ID")
async def createfile(interaction: discord.Interaction, member: discord.Member, roblox_id: str):
    if not is_authorized(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    # Fetch Roblox group rank for this user
    async with aiohttp.ClientSession() as session:
        url = f"https://groups.roblox.com/v2/users/{roblox_id}/groups/roles"
        async with session.get(url) as resp:
            if resp.status != 200:
                await interaction.response.send_message("Failed to fetch Roblox group data.", ephemeral=True)
                return

            group_data = await resp.json()
            user_groups = group_data.get("data", [])
            group_info = next((g for g in user_groups if g["group"]["id"] == ROBLX_GROUP_ID), None)

            if not group_info:
                await interaction.response.send_message("User is not in the Roblox group.", ephemeral=True)
                return

            role_name = group_info["role"]["name"]

    # Load existing data and add the new file
    data = load_data()
    data[str(member.id)] = {
        "username": str(member),
        "roblox_id": roblox_id,
        "rank": role_name,
        "credits": 0,
        "last_edited_by": interaction.user.id
    }
    save_data(data)

    await interaction.response.send_message(f"File created for {member.mention} with rank **{role_name}**.")

# === /deletefile ===
@tree.command(name="deletefile", description="Delete a member's file", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(member="Member whose file you want to delete")
async def deletefile(interaction: discord.Interaction, member: discord.Member):
    if not is_authorized(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    data = load_data()
    user_id = str(member.id)
    if user_id not in data:
        await interaction.response.send_message("No file found for this member.", ephemeral=True)
        return

    del data[user_id]
    save_data(data)
    await interaction.response.send_message(f"🗑️ Deleted the file for {member.mention}.")

# === /addcredits ===
@tree.command(name="addcredits", description="Add credits to a member's file", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(member="Member to credit", amount="Amount to add")
async def addcredits(interaction: discord.Interaction, member: discord.Member, amount: int):
    if not is_authorized(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    data = load_data()
    if str(member.id) not in data:
        await interaction.response.send_message("No file found for this member.", ephemeral=True)
        return

    user_data = data[str(member.id)]
    user_data["credits"] += amount
    user_data["last_edited_by"] = interaction.user.id

    rank_name_lower = user_data["rank"].lower()
    rank_num = RANK_NAME_TO_NUMBER.get(rank_name_lower)

    required_credits = RANK_CREDIT_REQUIREMENTS.get(rank_num, 100)  # fallback default

    save_data(data)

    await interaction.response.send_message(
        f"✅ Added {amount} credits to {member.mention}. Total: {user_data['credits']}."
    )

    if user_data["credits"] >= required_credits:
        await interaction.followup.send(f"{member.mention} is **eligible for promotion!**", ephemeral=False)

# === /removecredits ===
@tree.command(name="removecredits", description="Remove credits from a member's file", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(member="Member to modify", amount="Amount to remove")
async def removecredits(interaction: discord.Interaction, member: discord.Member, amount: int):
    if not is_authorized(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    data = load_data()
    if str(member.id) not in data:
        await interaction.response.send_message("No file found for this member.", ephemeral=True)
        return

    data[str(member.id)]["credits"] = max(0, data[str(member.id)]["credits"] - amount)
    data[str(member.id)]["last_edited_by"] = interaction.user.id
    save_data(data)

    await interaction.response.send_message(f"➖ Removed {amount} credits from {member.mention}. Total: {data[str(member.id)]['credits']}.")

# === /promote ===
@tree.command(name="promote", description="Promote a member and reset credits", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(member="Member to promote", new_rank="New rank after promotion")
async def promote(interaction: discord.Interaction, member: discord.Member, new_rank: str):
    if not is_authorized(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    data = load_data()
    if str(member.id) not in data:
        await interaction.response.send_message("No file found for this member.", ephemeral=True)
        return

    data[str(member.id)]["rank"] = new_rank
    data[str(member.id)]["credits"] = 0
    data[str(member.id)]["last_edited_by"] = interaction.user.id
    save_data(data)

    await interaction.response.send_message(f"🎉 {member.mention} has been promoted to **{new_rank}** and credits reset.")

# === /syncfile ===
@tree.command(name="syncfile", description="Sync the user's Roblox rank from the group", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(member="Discord member to sync (default: yourself)")
async def syncfile(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    data = load_data()

    if str(member.id) not in data:
        await interaction.response.send_message("No file found for this member.", ephemeral=True)
        return

    roblox_id = data[str(member.id)]["roblox_id"]

    async with aiohttp.ClientSession() as session:
        url = f"https://groups.roblox.com/v2/users/{roblox_id}/groups/roles"
        async with session.get(url) as resp:
            if resp.status != 200:
                await interaction.response.send_message("Failed to fetch Roblox group data.", ephemeral=True)
                return

            group_data = await resp.json()
            user_groups = group_data.get("data", [])
            group_info = next((g for g in user_groups if g["group"]["id"] == ROBLX_GROUP_ID), None)

            if not group_info:
                await interaction.response.send_message("User is not in the Roblox group.", ephemeral=True)
                return

            role_name = group_info["role"]["name"]
            role_rank = group_info["role"]["rank"]

            user_data = data[str(member.id)]
            user_data["rank"] = role_name
            user_data["last_edited_by"] = interaction.user.id
            save_data(data)

            await interaction.response.send_message(
                f"✅ Synced {member.mention}'s Roblox rank to **{role_name}** (Rank {role_rank})."
            )


# === /commands ===
@tree.command(name="commands", description="List all available bot commands", guild=discord.Object(id=GUILD_ID))
async def show_commands(interaction: discord.Interaction):
    help_text = """
**📋 Available Slash Commands**

__🔧 Admin Commands (require 'NCO+' roles)__:
- `/createfile @user [RobloxID]` — Create a new user file (rank set automatically)
- `/addcredits @user [amount]` — Add credits to a user
- `/removecredits @user [amount]` — Remove credits from a user
- `/promote @user [NewRank]` — Promote a user and reset credits
- `/deletefile @user` — Delete a user's file

__👤 User Commands__:
- `/viewfile [@user]` — View your own or another member’s file (shows if eligible for promotion)
- `/commands` — Show this help menu
"""
    await interaction.response.send_message(help_text, ephemeral=True)

# === On Ready ===
@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    await tree.sync(guild=guild) 
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("Slash commands synced.")

# === Run the Bot ===
bot.run(os.environ["DISCORD_TOKEN"])

