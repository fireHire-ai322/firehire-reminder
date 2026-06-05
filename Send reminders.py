import discord
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import pytz
import asyncio
import os
import json

# ============================================================
# Config
# ============================================================
DISCORD_TOKEN   = os.environ["DISCORD_TOKEN"]
GUILD_ID        = int(os.environ["GUILD_ID"])
WEBHOOK_URL     = os.environ["CALLERS_WEBHOOK_URL"]
SPREADSHEET_ID  = os.environ["SPREADSHEET_ID"]
SHEET_NAME      = os.environ.get("SHEET_NAME", "The Validation")
GOOGLE_CREDS    = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])

CAIRO_TZ = pytz.timezone("Africa/Cairo")

# ============================================================
# Google Sheets
# ============================================================
def get_todays_interviews():
    creds = Credentials.from_service_account_info(
        GOOGLE_CREDS,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    client = gspread.authorize(creds)
    sheet  = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
    data   = sheet.get_all_records()

    today = datetime.now(CAIRO_TZ).strftime("%Y-%m-%d")

    caller_map = {}  # { "Amir": [ {name, company, time} ] }

    for row in data:
        full_name   = str(row.get("Full Name", "")).strip()
        company     = str(row.get("Company Name you are applying for", "")).strip()
        caller      = str(row.get("Caller", "")).strip()
        date_of_call = str(row.get("Date of Call", "")).strip()
        call_time    = str(row.get("Call Time", "")).strip()

        if not full_name or not caller or not date_of_call:
            continue

        # normalize date
        try:
            parsed_date = datetime.strptime(date_of_call[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except:
            continue

        if parsed_date != today:
            continue

        # format time
        try:
            parsed_time = datetime.strptime(call_time, "%H:%M:%S")
            time_str = parsed_time.strftime("%I:%M %p")
        except:
            time_str = call_time or "6:00 PM"

        if caller not in caller_map:
            caller_map[caller] = []
        caller_map[caller].append({
            "name": full_name,
            "company": company,
            "time": time_str
        })

    return caller_map

# ============================================================
# Discord
# ============================================================
intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)

async def send_webhook(payload):
    import aiohttp
    async with aiohttp.ClientSession() as session:
        await session.post(WEBHOOK_URL, json=payload)

def build_embed(caller_name, interviews, today, continued=False):
    fields = [
        {
            "name": f"👤 {iv['name']}",
            "value": f"🏢 **{iv['company']}**\n⏰ **{iv['time']}**",
            "inline": True
        }
        for iv in interviews
    ]

    return {
        "embeds": [{
            "title": f"📞 {caller_name} — {'Continued' if continued else 'Your Interviews Today'}",
            "description": None if continued else (
                f"Hey **{caller_name}**! 👋\n"
                f"Here are your **{len(interviews)} call interview(s)** scheduled for today **{today}**.\n\n"
                f"Be ready and on time — candidates are counting on you! 💪🔥"
            ),
            "color": 0x5865F2,
            "fields": fields,
            "footer": {"text": "FireHire Recruitment | Daily Call Reminder • 3:00 PM"}
        }]
    }

@client.event
async def on_ready():
    print(f"✅ Bot online: {client.user}")

    guild = client.get_guild(GUILD_ID)
    if not guild:
        print("❌ Guild not found")
        await client.close()
        return

    today = datetime.now(CAIRO_TZ).strftime("%Y-%m-%d")

    # جيب الانترفيوز من الشيت
    caller_map = get_todays_interviews()

    if not caller_map:
        print("No interviews today.")
        await send_webhook({"content": "✅ No call interviews scheduled for today."})
        await client.close()
        return

    for caller_name, interviews in caller_map.items():

        # دور على الـ member بالـ Role Caller-{Name}
        role_name = f"Caller-{caller_name}"
        role = discord.utils.get(guild.roles, name=role_name)

        if not role:
            print(f"⚠️ Role '{role_name}' not found — skipping DM for {caller_name}")
        else:
            members = [m for m in role.members if not m.bot]
            if not members:
                print(f"⚠️ No members with role '{role_name}'")
            else:
                member = members[0]
                # قسّم لو أكتر من 24 انترفيو
                chunks = [interviews[i:i+24] for i in range(0, len(interviews), 24)]
                for idx, chunk in enumerate(chunks):
                    embed = build_embed(caller_name, chunk if idx == 0 else chunk, today, continued=(idx > 0))
                    try:
                        await member.send(embed=discord.Embed.from_dict(embed["embeds"][0]))
                        await asyncio.sleep(0.3)
                    except discord.Forbidden:
                        print(f"⚠️ Can't DM {member.name}")

                print(f"✅ DM sent to {caller_name} ({member.name})")

        # بعت في القناة العامة
        chunks = [interviews[i:i+24] for i in range(0, len(interviews), 24)]
        for idx, chunk in enumerate(chunks):
            await send_webhook(build_embed(caller_name, chunk, today, continued=(idx > 0)))
            await asyncio.sleep(0.3)

        await asyncio.sleep(0.5)

    print("✅ All reminders sent.")
    await client.close()

client.run(DISCORD_TOKEN)
