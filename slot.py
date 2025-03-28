import discord
import json
import os
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from dotenv import load_dotenv
import flask_server

flask_server.start_flask()

load_dotenv()
TOKEN = os.getenv("T")

CATEGORY_ID = 1348928375082848306
JSON_FILE = "slots.json"
YOUR_GUILD_ID = 1298020437560660028
SLOT_ROLE_ID = 1349150332713832549


intents = discord.Intents.all()

bot = commands.Bot(command_prefix="/", intents=intents)

def load_slots():
    if os.path.exists(JSON_FILE):
        with open(JSON_FILE, "r") as f:
            return json.load(f)
    return {"slots": {}}

def save_slots(data):
    with open(JSON_FILE, "w") as f:
        json.dump(data, f, indent=4)


async def is_admin(ctx):
    return ctx.user.guild_permissions.administrator

@tasks.loop(minutes=60)
async def check_expirations():
    now = datetime.utcnow()
    data = load_slots()
    to_delete = []

    for channel_id, slot in data["slots"].items():
        expire_time = datetime.fromisoformat(slot["expires_at"])
        channel = bot.get_channel(int(channel_id))

        if not channel:
            to_delete.append(channel_id)
            continue

        if expire_time - now < timedelta(hours=24) and not slot.get("warned", False):
            await channel.send("⚠️ Acest slot va expira în mai puțin de 24 de ore!")
            slot["warned"] = True

        if now >= expire_time:
            guild = bot.get_guild(YOUR_GUILD_ID)
            user = guild.get_member(int(slot["owner"]))
            role = guild.get_role(SLOT_ROLE_ID)
            if user and role:
                try:
                    await user.remove_roles(role)
                except discord.Forbidden:
                    print(f"Nu am permisiunea de a elimina rolul {role.name} de la {user.name}")
            await channel.delete()
            to_delete.append(channel_id)

    for channel_id in to_delete:
        del data["slots"][channel_id]

    save_slots(data)


@bot.event
async def on_ready():
    print(f"✅ Conectat ca {bot.user}")

    guild = bot.get_guild(YOUR_GUILD_ID)
    if not guild:
        print("❌ Botul nu este pe serverul specificat. Oprirea botului.")
        await bot.close()
        return

    check_expirations.start()
    await bot.tree.sync()
@bot.tree.command(name="addslot", description="Adaugă un slot nou")
async def addslot(interaction: discord.Interaction, user: discord.User, days: int):
    if not await is_admin(interaction):
        await interaction.response.send_message("❌ Doar administratorii serverului pot folosi această comandă!", ephemeral=True)
        return

    category = bot.get_channel(CATEGORY_ID)
    if not category:
        await interaction.response.send_message("❌ Categoria nu a fost găsită!", ephemeral=True)
        return
    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False), 
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True, mention_everyone=False),
        interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, mention_everyone=True)
    }

    channel = await category.create_text_channel(name=user.name, overwrites=overwrites)
    expires_at = datetime.utcnow() + timedelta(days=days)

    data = load_slots()
    data["slots"][str(channel.id)] = {
        "owner": str(user.id),
        "expires_at": expires_at.isoformat(),
        "warned": False,
        "warnings": 0,
        "paused": False,
        "last_used": None 
    }
    save_slots(data)

    guild = bot.get_guild(YOUR_GUILD_ID)
    role = guild.get_role(SLOT_ROLE_ID)
    if role:
        try:
            await user.add_roles(role)
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ Nu am permisiunea de a adăuga rolul {role.name} utilizatorului.", ephemeral=True)
            return

    await interaction.response.send_message(f"✅ Slotul **{channel.name}** a fost creat și va expira în {days} zile. Rolul a fost adăugat utilizatorului.")
    await channel.send(f"✅ Acest slot va expira pe {expires_at.strftime('%Y-%m-%d %H:%M:%S')} UTC.")

@bot.tree.command(name="send_alert", description="Trimite o alertă @everyone sau @here")
async def send_alert(interaction: discord.Interaction, channel: discord.TextChannel, alert_type: str):
    if not await is_admin(interaction):
        await interaction.response.send_message("❌ Doar administratorii serverului pot trimite alerte @everyone sau @here!", ephemeral=True)
        return

    data = load_slots()
    slot = data["slots"].get(str(channel.id))

    if not slot:
        await interaction.response.send_message("❌ Acest canal nu este un slot valid.", ephemeral=True)
        return

    last_used = slot["last_used"]
    now = datetime.utcnow()

    if last_used and (now - datetime.fromisoformat(last_used)) < timedelta(days=1):
        await interaction.response.send_message("❌ Nu poți folosi @everyone sau @here mai mult de o dată pe zi.", ephemeral=True)
        return

    if alert_type not in ["everyone", "here"]:
        await interaction.response.send_message("❌ Tipul de alertă nu este valid. Folosește `everyone` sau `here`.", ephemeral=True)
        return

    await channel.send(f"@{alert_type} Aceasta este o alertă importantă!")
    slot["last_used"] = now.isoformat()
    save_slots(data)

    await interaction.response.send_message(f"✅ Alerta @{alert_type} a fost trimisă în canalul **{channel.name}**.")

@bot.tree.command(name="dslot", description="Afișează detaliile unui slot")
async def slotdetails(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await is_admin(interaction):
        await interaction.response.send_message("❌ **Doar administratorii serverului** pot verifica detaliile unui slot!", ephemeral=True)
        return

    data = load_slots()
    slot = data["slots"].get(str(channel.id))

    if not slot:
        await interaction.response.send_message("❌ **Acest canal nu este un slot valid.**", ephemeral=True)
        return

    expires_at = datetime.fromisoformat(slot["expires_at"])
    paused = "✅ Da" if slot["paused"] else "❌ Nu"
    warnings = slot["warnings"]

    embed = discord.Embed(
        title=f"🎮 Detalii slot pentru {channel.name}",
        description=f"⏳ **Slotul este activ până la**: {expires_at.strftime('%Y-%m-%d %H:%M:%S')} UTC",
        color=discord.Color.blue()
    )
    embed.add_field(name="🛑 Este pe pauză?", value=paused, inline=False)
    embed.add_field(name="⚠️ Avertismente", value=str(warnings), inline=False)
    embed.set_footer(text="🔒 Siguranța este prioritatea noastră!")

    await interaction.response.send_message(embed=embed)
    
@bot.tree.command(name="wslot", description="Avertizează un slot")
async def wslot(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await is_admin(interaction):
        await interaction.response.send_message("❌ Doar administratorii serverului pot acorda avertismente!", ephemeral=True)
        return

    data = load_slots()
    slot = data["slots"].get(str(channel.id))

    if not slot:
        await interaction.response.send_message("❌ Acest canal nu este un slot valid.", ephemeral=True)
        return

    slot["warnings"] += 1
    save_slots(data)

    await channel.send(f"⚠️ {interaction.user.mention} a acordat un avertisment acestui slot. Total avertismente: **{slot['warnings']}/3**.")

    if slot["warnings"] >= 3:
        await channel.send("❌ Acest slot a fost șters automat pentru că a primit 3 avertismente!")
        await channel.delete()
        del data["slots"][str(channel.id)]
        save_slots(data)

    await interaction.response.send_message(f"✅ Ai adăugat un avertisment slotului **{channel.name}**.")

@bot.tree.command(name="pslot", description="Pune un slot pe pauză pentru verificare")
async def pslot(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await is_admin(interaction):
        await interaction.response.send_message("❌ Doar administratorii serverului pot pune slotul pe pauză!", ephemeral=True)
        return

    data = load_slots()
    slot = data["slots"].get(str(channel.id))

    if not slot:
        await interaction.response.send_message("❌ Acest canal nu este un slot valid.", ephemeral=True)
        return

    if slot["paused"]:
        await interaction.response.send_message("❌ Acest slot este deja pe pauză!", ephemeral=True)
        return

    await channel.set_permissions(interaction.guild.default_role, send_messages=False)
    slot["paused"] = True
    save_slots(data)

    await channel.send("⚠️ Acest slot este suspect de scam și este în verificare.")
    await interaction.response.send_message(f"✅ Slotul **{channel.name}** a fost pus pe pauză.")

@bot.tree.command(name="eslot", description="Prelungește timpul unui slot")
async def eslot(interaction: discord.Interaction, channel: discord.TextChannel, days: int):
    if not await is_admin(interaction):
        await interaction.response.send_message("❌ Doar administratorii serverului pot prelungi sloturile!", ephemeral=True)
        return

    data = load_slots()
    slot = data["slots"].get(str(channel.id))

    if not slot:
        await interaction.response.send_message("❌ Acest canal nu este un slot valid.", ephemeral=True)
        return

    new_expire = datetime.fromisoformat(slot["expires_at"]) + timedelta(days=days)
    slot["expires_at"] = new_expire.isoformat()
    slot["warned"] = False  
    save_slots(data)

    await interaction.response.send_message(f"✅ Slotul **{channel.name}** a fost prelungit cu {days} zile.")
    await channel.send(f"⏳ Acest slot a fost prelungit și acum va expira pe {new_expire.strftime('%Y-%m-%d %H:%M:%S')} UTC.")

@bot.tree.command(name="rslot", description="Șterge un slot manual")
async def rslot(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await is_admin(interaction):
        await interaction.response.send_message("❌ Doar administratorii serverului pot șterge sloturile!", ephemeral=True)
        return

    data = load_slots()

    if str(channel.id) not in data["slots"]:
        await interaction.response.send_message("❌ Acest canal nu este un slot valid.", ephemeral=True)
        return

    slot = data["slots"][str(channel.id)]
    guild = bot.get_guild(YOUR_GUILD_ID)
    user = guild.get_member(int(slot["owner"]))
    role = guild.get_role(SLOT_ROLE_ID)

    if user and role:
        try:
            await user.remove_roles(role)
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ Nu am permisiunea de a elimina rolul {role.name} de la {user.name}.", ephemeral=True)
            return

    await channel.delete()
    del data["slots"][str(channel.id)]
    save_slots(data)

    await interaction.response.send_message(f"✅ Slotul **{channel.name}** a fost șters și rolul utilizatorului a fost eliminat.")

@bot.tree.command(name="aslot", description="Trimite un mesaj de avertizare într-un slot")
async def aslot(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await is_admin(interaction):
        await interaction.response.send_message("❌ Doar administratorii serverului pot folosi această comandă!", ephemeral=True)
        return

    data = load_slots()
    slot = data["slots"].get(str(channel.id))

    if not slot:
        await interaction.response.send_message("❌ Acest canal nu este un slot valid.", ephemeral=True)
        return

    embed = discord.Embed(
        title="⚠️ Atenție la înșelătorii!",
        description="Pentru a evita orice probleme, **folosiți middleman** atunci când faceți tranzacții.\n\n"
                    "Dacă aveți nevoie de middleman, **deschideți un ticket** – este complet **GRATUIT**! 🎟️",
        color=discord.Color.yellow()
    )
    embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/833/833472.png") 
    embed.set_footer(text="Siguranța ta este prioritatea noastră! 🔒")

    await channel.send(embed=embed)
    await interaction.response.send_message(f"✅ Mesajul de avertizare a fost trimis în **{channel.name}**.", ephemeral=True)
    
@bot.tree.command(name="help", description="Afișează lista de comenzi disponibile")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Lista de comenzi disponibile",
        description="Iată o listă cu toate comenzile pe care le poți folosi:",
        color=discord.Color.green()
    )

    commands_list = [
        {"name": "addslot", "description": "Adaugă un slot nou pentru un utilizator."},
        {"name": "send_alert", "description": "Trimite o alertă @everyone sau @here într-un slot."},
        {"name": "dslot", "description": "Afișează detaliile unui slot."},
        {"name": "wslot", "description": "Avertizează un slot."},
        {"name": "pslot", "description": "Pune un slot pe pauză pentru verificare."},
        {"name": "eslot", "description": "Prelungește timpul unui slot."},
        {"name": "rslot", "description": "Șterge un slot manual."},
        {"name": "aslot", "description": "Trimite un mesaj de avertizare într-un slot."},
         {"name": "unpslot", "description": "Scoate de pe pauza un slot."},
        {"name": "help", "description": "Afișează această listă de comenzi."}
    ]

    for cmd in commands_list:
        embed.add_field(name=f"/{cmd['name']}", value=cmd['description'], inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="unpslot", description="Scoate un slot de pe pauză")
async def unpslot(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await is_admin(interaction):
        await interaction.response.send_message("❌ Doar administratorii serverului pot scoate slotul de pe pauză!", ephemeral=True)
        return

    data = load_slots()
    slot = data["slots"].get(str(channel.id))

    if not slot:
        await interaction.response.send_message("❌ Acest canal nu este un slot valid.", ephemeral=True)
        return

    if not slot["paused"]:
        await interaction.response.send_message("❌ Acest slot nu este pe pauză!", ephemeral=True)
        return

    await channel.set_permissions(interaction.guild.default_role, send_messages=True)
    slot["paused"] = False
    save_slots(data)

    await channel.send("✅ Acest slot a fost scos de pe pauză.")
    await interaction.response.send_message(f"✅ Slotul **{channel.name}** a fost scos de pe pauză.")  
            
bot.run(TOKEN)
