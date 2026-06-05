const { google } = require("googleapis");
const fetch = require("node-fetch");

// ============================================================
// Config من Environment Variables
// ============================================================
const SPREADSHEET_ID  = process.env.SPREADSHEET_ID;
const SHEET_NAME      = process.env.SHEET_NAME || "The Validation";
const CALLERS_WEBHOOK = process.env.CALLERS_WEBHOOK_URL;
const BOT_TOKEN       = process.env.DISCORD_TOKEN;
const GOOGLE_CREDS    = JSON.parse(process.env.GOOGLE_SERVICE_ACCOUNT_JSON);

// ============================================================
// Google Sheets Auth
// ============================================================
async function getSheetData() {
  const auth = new google.auth.GoogleAuth({
    credentials: GOOGLE_CREDS,
    scopes: ["https://www.googleapis.com/auth/spreadsheets.readonly"],
  });

  const sheets = google.sheets({ version: "v4", auth });
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: SHEET_NAME,
  });

  return res.data.values;
}

// ============================================================
// فورمات التاريخ
// ============================================================
function toDateStr(val) {
  if (!val) return "";
  const d = new Date(val);
  if (isNaN(d)) return "";
  return d.toISOString().split("T")[0]; // yyyy-MM-dd
}

function toTimeStr(val) {
  if (!val) return "6:00 PM";
  const d = new Date(val);
  if (isNaN(d)) return "6:00 PM";
  return d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
    timeZone: "Africa/Cairo",
  });
}

function todayStr() {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Africa/Cairo" }); // yyyy-MM-dd
}

// ============================================================
// بناء الـ callerMap
// ============================================================
function buildCallerMap(data) {
  const headers = data[0].map((h) => h.toString().trim());
  const col = {};
  headers.forEach((h, i) => (col[h] = i));

  const today = todayStr();
  const callerMap = {};      // { callerName: [ {name, company, time} ] }
  const callerIds  = {};     // { callerName: discordUserId }

  for (let i = 1; i < data.length; i++) {
    const row      = data[i];
    const fullName = (row[col["Full Name"]] || "").toString().trim();
    const company  = (row[col["Company Name you are applying for"]] || "").toString().trim();
    const caller   = (row[col["Caller"]] || "").toString().trim();
    const dateOfCall = row[col["Date of Call"]];
    const callTime   = row[col["Call Time"]];
    const discordId  = (row[col["Discord User ID"]] || "").toString().trim();

    if (!fullName || !caller || !dateOfCall) continue;
    if (toDateStr(dateOfCall) !== today) continue;

    if (!callerMap[caller]) callerMap[caller] = [];
    callerMap[caller].push({
      name: fullName,
      company,
      time: toTimeStr(callTime),
    });

    if (discordId && !callerIds[caller]) callerIds[caller] = discordId;
  }

  return { callerMap, callerIds };
}

// ============================================================
// بناء الـ Embed payload
// ============================================================
function buildEmbedPayload(callerName, interviews, today, index = 0) {
  const fields = interviews.map((iv) => ({
    name: `👤 ${iv.name}`,
    value: `🏢 **${iv.company}**\n⏰ **${iv.time}**`,
    inline: true,
  }));

  const chunks = [];
  for (let i = 0; i < fields.length; i += 24) chunks.push(fields.slice(i, i + 24));

  return chunks.map((chunk, idx) => ({
    embeds: [
      {
        title:
          idx === 0
            ? `📞 ${callerName} — Your Interviews Today`
            : `📞 ${callerName} — Continued`,
        description:
          idx === 0
            ? `Hey **${callerName}**! 👋\nHere are your **${interviews.length} call interview(s)** scheduled for today **${today}**.\n\nBe ready and on time — candidates are counting on you! 💪🔥`
            : null,
        color: 0x5865f2,
        fields: chunk,
        footer: { text: "FireHire Recruitment | Daily Call Reminder • 3:00 PM" },
      },
    ],
  }));
}

// ============================================================
// إرسال على Webhook (القناة)
// ============================================================
async function sendToWebhook(payload) {
  await fetch(CALLERS_WEBHOOK, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// ============================================================
// فتح DM Channel
// ============================================================
async function openDMChannel(userId) {
  const res = await fetch("https://discord.com/api/v10/users/@me/channels", {
    method: "POST",
    headers: {
      Authorization: `Bot ${BOT_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ recipient_id: userId }),
  });
  const data = await res.json();
  return data.id || null;
}

// ============================================================
// إرسال على Channel (DM أو عادي)
// ============================================================
async function sendToChannel(channelId, payload) {
  await fetch(`https://discord.com/api/v10/channels/${channelId}/messages`, {
    method: "POST",
    headers: {
      Authorization: `Bot ${BOT_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

// ============================================================
// sleep helper
// ============================================================
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ============================================================
// Main
// ============================================================
async function main() {
  console.log("🚀 FireHire Caller Reminder starting...");

  const data = await getSheetData();
  if (!data || data.length < 2) {
    console.log("No data found in sheet.");
    return;
  }

  const { callerMap, callerIds } = buildCallerMap(data);
  const today = todayStr();

  if (Object.keys(callerMap).length === 0) {
    console.log("✅ No interviews today.");
    await sendToWebhook({ content: "✅ No call interviews scheduled for today." });
    return;
  }

  for (const [caller, interviews] of Object.entries(callerMap)) {
    const payloads = buildEmbedPayload(caller, interviews, today);

    // 1. القناة العامة
    for (const p of payloads) {
      await sendToWebhook(p);
      await sleep(300);
    }

    // 2. DM لو عنده Discord ID
    const discordId = callerIds[caller];
    if (discordId && BOT_TOKEN) {
      const dmChannelId = await openDMChannel(discordId);
      if (dmChannelId) {
        for (const p of payloads) {
          await sendToChannel(dmChannelId, p);
          await sleep(300);
        }
        console.log(`✅ DM sent to ${caller}`);
      } else {
        console.warn(`⚠️ Could not open DM for ${caller} (ID: ${discordId})`);
      }
    } else {
      console.warn(`⚠️ No Discord ID for ${caller} — DM skipped`);
    }

    await sleep(500);
  }

  console.log("✅ All reminders sent for: " + Object.keys(callerMap).join(", "));
}

main().catch((err) => {
  console.error("❌ Error:", err);
  process.exit(1);
});
