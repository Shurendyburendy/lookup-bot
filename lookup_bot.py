"""Discord /lookup + /database bot
Gebruik: pip install -U discord.py
         python lookup_bot.py  (of dubbelklik start-bot.bat)
"""
import datetime
import os
import sqlite3

import aiohttp
import discord
from discord import app_commands

from keep_alive import keep_alive

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = os.getenv("GUILD_ID", "1549144439782506607").strip()
RULES_CHANNEL_ID = int(os.getenv("RULES_CHANNEL_ID", "1555156623603798036"))
RULES_ROLE_ID = int(os.getenv("RULES_ROLE_ID", "1553528202939334786"))

DB_PATH = "database.db"


def db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """CREATE TABLE IF NOT EXISTS lookups(
            user_id TEXT PRIMARY KEY,
            username TEXT, global_name TEXT, note TEXT,
            added_by TEXT, lookup_count INTEGER DEFAULT 0,
            last_lookup TEXT, updated_at TEXT)"""
    )
    return con


async def fetch_raw(user_id: str) -> dict:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://discord.com/api/v10/users/{user_id}",
                headers={"Authorization": f"Bot {TOKEN}"},
                timeout=15,
            ) as r:
                if r.status == 200:
                    return await r.json()
    except Exception:
        pass
    return {}


def pretty_embed(user: discord.User, raw: dict, count: int, note: str | None,
                 requester: discord.abc.User) -> discord.Embed:
    accent = raw.get("accent_color") or 0x5865F2
    created_dt = discord.utils.snowflake_time(int(user.id))
    created_str = created_dt.strftime("%d-%m-%Y %H:%M UTC")
    e = discord.Embed(
        title=f"🔍 {user.global_name or user.name}",
        description=f"@{user.name} • `{user.id}`",
        color=accent,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    if user.avatar:
        e.set_thumbnail(url=user.avatar.with_size(1024).url)
    banner = raw.get("banner")
    if banner:
        e.set_image(url=f"https://cdn.discordapp.com/banners/{user.id}/{banner}.png?size=1024")
    e.add_field(name="👤 Username", value=str(user.name), inline=True)
    e.add_field(name="✨ Display", value=str(user.global_name or "-"), inline=True)
    e.add_field(name="🤖 Bot", value="ja" if user.bot else "nee", inline=True)
    e.add_field(name="📅 Aangemaakt", value=created_str, inline=True)
    e.add_field(name="🔁 Opgezocht", value=str(count), inline=True)
    clan = (raw.get("clan") or {}).get("tag") or (raw.get("primary_guild") or {}).get("tag")
    if clan:
        e.add_field(name="🏷️ Clan", value=str(clan), inline=True)
    if note:
        e.add_field(name="📝 Notitie", value=note[:1024], inline=False)
    if user.avatar:
        e.add_field(name="🖼️ Avatar", value=f"[open]({user.avatar.with_size(1024).url})", inline=True)
    e.add_field(name="🔗 Profiel", value=f"[open](https://discord.com/users/{user.id})", inline=True)
    e.set_footer(text=f"Opgevraagd door {requester}")
    return e


class AcceptView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ Accepteren", style=discord.ButtonStyle.green,
                       custom_id="regels:accepteer")
    async def accepteer(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = interaction.guild.get_role(RULES_ROLE_ID) if interaction.guild else None
        if role is None:
            await interaction.response.send_message("Rol niet gevonden.", ephemeral=True)
            return
        if role in getattr(interaction.user, "roles", []):
            await interaction.response.send_message("Je hebt de rol al.", ephemeral=True)
            return
        try:
            await interaction.user.add_roles(role, reason="Regels geaccepteerd")
            await interaction.response.send_message(f"Bedankt! Je hebt nu {role.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "Ik heb geen rechten. Zet mijn bot-rol HOGER dan de te geven rol en geef me 'Manage Roles'.",
                ephemeral=True)


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.add_view(AcceptView())
        self.tree.add_command(database)
        if GUILD_ID.isdigit():
            guild = discord.Object(id=int(GUILD_ID))
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                print(f"Commands gesynct naar guild {GUILD_ID}")
            except discord.Forbidden:
                print(f"Geen toegang tot guild {GUILD_ID} (403 Missing Access). Bot zit niet in die server.")
                print("Sync nu globaal. Nodig de bot uit of pas GUILD_ID aan.")
                try:
                    await self.tree.sync()
                except Exception as e:
                    print(f"Globale sync ook mislukt: {e}")
        else:
            await self.tree.sync()
            print("Commands globaal gesynct (kan tot 1 uur duren)")


bot = Bot()


@bot.tree.command(name="lookup", description="Zoek een Discord user op via ID")
@app_commands.describe(user_id="Discord user ID", stijl="modern of compact")
@app_commands.choices(stijl=[
    app_commands.Choice(name="modern", value="modern"),
    app_commands.Choice(name="compact", value="compact"),
])
async def lookup(interaction: discord.Interaction, user_id: str, stijl: str = "modern"):
    await interaction.response.defer()
    if not user_id.isdigit():
        await interaction.followup.send("Geef een numerieke ID op.")
        return
    try:
        user = await interaction.client.fetch_user(int(user_id))
    except discord.NotFound:
        await interaction.followup.send("User niet gevonden (404).")
        return
    except discord.HTTPException as ex:
        await interaction.followup.send(f"Discord API fout: {getattr(ex, 'status', '?')}")
        return

    raw = await fetch_raw(user_id)
    con = db()
    row = con.execute("SELECT note, lookup_count FROM lookups WHERE user_id=?",
                      (user_id,)).fetchone()
    note, count = (row[0], row[1] + 1) if row else (None, 1)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    con.execute(
        """INSERT INTO lookups(user_id, username, global_name, note, added_by,
           lookup_count, last_lookup, updated_at)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             username=excluded.username, global_name=excluded.global_name,
             lookup_count=lookups.lookup_count+1,
             last_lookup=excluded.last_lookup, updated_at=excluded.updated_at""",
        (user_id, user.name, user.global_name, note,
         str(interaction.user.id), count, now, now),
    )
    con.commit()
    con.close()

    if stijl == "compact":
        await interaction.followup.send(
            f"`{user.id}` @{user.name} ({user.global_name or '-'})"
            f"{' | 📝 ' + note if note else ''}"
        )
        return
    await interaction.followup.send(embed=pretty_embed(user, raw, count, note, interaction.user))


database = app_commands.Group(name="database", description="Opgeslagen users")


@database.command(name="add", description="Voeg iemand handmatig toe met notitie")
@app_commands.describe(user_id="Discord user ID", notitie="Reden / notitie")
async def db_add(interaction: discord.Interaction, user_id: str, notitie: str):
    await interaction.response.defer(ephemeral=True)
    if not user_id.isdigit():
        await interaction.followup.send("Geef een numerieke ID op.")
        return
    try:
        user = await interaction.client.fetch_user(int(user_id))
        uname, gname = user.name, user.global_name
    except Exception:
        uname, gname = "-", "-"
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    con = db()
    con.execute(
        """INSERT INTO lookups(user_id, username, global_name, note, added_by,
           lookup_count, last_lookup, updated_at)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             username=excluded.username, global_name=excluded.global_name,
             note=excluded.note, added_by=excluded.added_by,
             updated_at=excluded.updated_at""",
        (user_id, uname, gname, notitie[:1000], str(interaction.user.id), 0, now, now),
    )
    con.commit()
    con.close()
    await interaction.followup.send(f"Opgeslagen `{user_id}` met notitie.")


@database.command(name="zoek", description="Zoek iemand op in de database")
@app_commands.describe(user_id="Discord user ID of deel van naam/notitie")
async def db_zoek(interaction: discord.Interaction, user_id: str):
    await interaction.response.defer(ephemeral=True)
    con = db()
    row = con.execute("SELECT * FROM lookups WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        row = con.execute(
            "SELECT * FROM lookups WHERE username LIKE ? OR global_name LIKE ? OR note LIKE ? LIMIT 1",
            (f"%{user_id}%", f"%{user_id}%", f"%{user_id}%")).fetchone()
    con.close()
    if not row:
        await interaction.followup.send("Niks gevonden in database.")
        return
    await interaction.followup.send(
        f"`{row[0]}` **{row[2] or row[1]}** (@{row[1]})\n"
        f"📝 {row[3] or '-'}\n🔁 {row[5]}x opgezocht, laatst: {row[6] or '-'}"
    )


@database.command(name="lijst", description="Toon laatste 10 opgeslagen users")
async def db_lijst(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    con = db()
    rows = con.execute(
        "SELECT user_id, username, global_name, note FROM lookups "
        "ORDER BY updated_at DESC LIMIT 10").fetchall()
    con.close()
    if not rows:
        await interaction.followup.send("Database is nog leeg.")
        return
    txt = "\n".join(
        f"`{r[0]}` **{r[2] or r[1]}** {('— ' + r[3][:80]) if r[3] else ''}" for r in rows)
    await interaction.followup.send(txt[:1900])


@database.command(name="verwijder", description="Verwijder iemand uit de database")
@app_commands.describe(user_id="Discord user ID")
async def db_verwijder(interaction: discord.Interaction, user_id: str):
    await interaction.response.defer(ephemeral=True)
    con = db()
    cur = con.execute("DELETE FROM lookups WHERE user_id=?", (user_id,))
    con.commit()
    con.close()
    await interaction.followup.send(
        "Verwijderd." if cur.rowcount else "ID stond niet in database.")


@bot.tree.command(name="setup-regels", description="Post regels + accepteer-knop (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def setup_regels(interaction: discord.Interaction):
    channel = interaction.client.get_channel(RULES_CHANNEL_ID)
    if channel is None:
        try:
            channel = await interaction.client.fetch_channel(RULES_CHANNEL_ID)
        except Exception:
            await interaction.response.send_message("Kanaal niet gevonden.", ephemeral=True)
            return
    embed = discord.Embed(
        title="📜 Regels",
        description=(
            "1. Geen spam of schelden\n"
            "2. Deel geen privé-gegevens van anderen\n"
            "3. Geen NSFW\n"
            "4. Reclame alleen met toestemming van staff\n"
            "5. Misbruik = ban\n\n"
            "Klik op **✅ Accepteren** om toegang te krijgen."
        ),
        color=0x5865F2,
    )
    await channel.send(embed=embed, view=AcceptView())
    await interaction.response.send_message(f"Gepost in {channel.mention}", ephemeral=True)


@bot.event
async def on_ready():
    db().close()
    print(f"Ingelogd als {bot.user} - /lookup + /database klaar")


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN ontbreekt. Zet hem als Environment Variable (zie .env.example).")
    keep_alive()
    bot.run(TOKEN)
