import discord
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import pytz
import asyncio
import os
import json
import re
import aiohttp

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
# Date Parser
# ============================================================
def parse_date(date_str):
    date_str = date_str.strip()
    if not date_str:
        return None

    # Format: "Jun , 7 Sunday  , 2026"
    m = re.match(r"(\w+)\s*,\s*(\d+)\s+\w+\s*,\s*(\d{4})", date_str)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%b %d %Y").strftime("%Y-%m-%d")
        except:
            pass

    # Format: "6/8/2026" M/D/YYYY
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", date_str)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)}/{m.group(2)}/{m.group(3)}", "%m/%d/%Y").strftime("%Y-%m-%d")
        except:
            pass

    # Format: "2026-06-08"
    if re.match(r"^\d{4}-\d{2}-\d{2}", date_str):
        return date_str[:10]

    return None

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
    rows = sheet.get_all_values()
headers = rows[0]
# بنمسح الأعمدة الفاضية من الـ headers
clean_headers = [h.strip() for h in headers]
data = []
for row in rows[1:]:
    if not any(cell.strip() for cell in row):
        continue  # بنتخطى الصفوف الفاضية خالص
    row_dict = {}
    for i, val in enumerate(row):
        if i < len(clean_headers):
            key = clean_headers[i] if clean_headers[i] else f"_col_{i}"
            row_dict[key] = val
    data.append(row_dict)

    today = datetime.now(CAIRO_TZ).strftime("%Y-%m-%d")
    print(f"🗓️ Today = {today} | Total rows = {len(data)}")

    caller_map = {}

    for row in data:
        full_name    = str(row.get("Full Name", "")).strip()
        company      = str(row.get("Company Name you are applying for", "")).strip()
        caller       = str(row.get("Caller", "")).strip()
        date_of_call = str(row.get("Date of Call", "")).strip()
        call_time    = str(row.get("Call Time", "")).strip()

        if not full_name or not caller or not date_of_call:
            continue

        parsed_date = parse_date(date_of_call)
        if not parsed_date:
            print(f"⚠️ Can't parse date: '{date_of_call}'")
            continue

        if parsed_date != today:
            continue

        print(f"✅ Match: {full_name} | {caller} | {parsed_date}")

        try:
            parsed_time = datetime.strptime(call_time, "%H:%M:%S")
            time_str = parsed_time.strftime("%I:%M %p")
        except:
            try:
                parsed_time = datetime.strptime(call_time, "%I:%M:%S %p")
                time_str = parsed_time.strftime("%I:%M %p")
            except:
                time_str = call_time or "N/A"

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

    try:
        caller_map = get_todays_interviews()
    except Exception as e:
        print(f"❌ Error reading sheet: {e}")
        await client.close()
        return

    if not caller_map:
        print("No interviews today.")
        await send_webhook({"content": "✅ No call interviews scheduled for today."})
        await client.close()
        return

    for caller_name, interviews in caller_map.items():

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
                chunks = [interviews[i:i+24] for i in range(0, len(interviews), 24)]
                for idx, chunk in enumerate(chunks):
                    embed = build_embed(caller_name, chunk, today, continued=(idx > 0))
                    try:
                        await member.send(embed=discord.Embed.from_dict(embed["embeds"][0]))
                        await asyncio.sleep(0.3)
                    except discord.Forbidden:
                        print(f"⚠️ Can't DM {member.name}")
                print(f"✅ DM sent to {caller_name} ({member.name})")

        chunks = [interviews[i:i+24] for i in range(0, len(interviews), 24)]
        for idx, chunk in enumerate(chunks):
            await send_webhook(build_embed(caller_name, chunk, today, continued=(idx > 0)))
            await asyncio.sleep(0.3)

        await asyncio.sleep(0.5)

    print("✅ All reminders sent.")
    await client.close()

client.run(DISCORD_TOKEN)
