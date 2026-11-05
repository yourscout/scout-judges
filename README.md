# Scout judges: ChatGPT + Gemini, automatic

Every Monday this sends the Content Engine's judge pack (posted by Claude on the Notion **Judge Desk** at 12:41pm) to ChatGPT and Gemini, and writes both replies back onto the Judge Desk. Tuesday's Claude step then picks the Top 3 using all three judges. No copy-pasting.

**Runs:** Mondays 04:00 UTC (2:30pm Adelaide in summer, 1:30pm in winter), plus a manual "Run workflow" button.
**Cost:** GitHub Actions about 1 minute a week (well inside the free allowance). Gemini free tier. OpenAI a few cents a week.
**Code:** one file, `judge.py`, Python standard library only. Nothing to install.

## Setup (about 20 minutes, once)

### 1. Make the repo
Create a **private** repo (e.g. `scout-judges`) and push these files exactly as they are, including `.github/workflows/judges.yml`.

### 2. Notion integration
1. Go to <https://www.notion.so/profile/integrations>, then **New integration**. Name it "Scout judges", make it Internal, and select the workspace that has Scout HQ.
2. Capabilities: **Read content**, **Update content**, **Insert content**. No user info needed.
3. Copy the **Internal Integration Secret**.
4. In Notion, open **Scout HQ → Judge Desk**, then ••• → **Connections** → add **Scout judges**. Only the Judge Desk needs it.

### 3. API keys
- **OpenAI:** <https://platform.openai.com/api-keys>, then create a key. Add US$5–10 credit and set a monthly limit under Billing → Limits.
- **Gemini:** <https://aistudio.google.com/apikey>, then create a key. Free tier is fine.

Save all three secrets in **Bitwarden** too. Never put them in Notion.

### 4. GitHub settings
Repo → **Settings → Secrets and variables → Actions**.

**Secrets** (encrypted):

| Name | Value |
| --- | --- |
| `NOTION_TOKEN` | Notion integration secret |
| `OPENAI_API_KEY` | OpenAI key |
| `GEMINI_API_KEY` | Gemini key |

**Variables** (Variables tab):

| Name | Value |
| --- | --- |
| `OPENAI_MODEL` | the model to judge with. Pick a current, cheap, capable chat model from OpenAI's models page |
| `GEMINI_MODEL` | a current Gemini model ID from Google AI Studio's model list (e.g. a "flash" model) |
| `JUDGE_DESK_ID` | optional. Defaults to `40e0ae8b62bf8108bbe8d43cfbfc032f` |

### 5. Test it
After a Monday run has put a pack on the Judge Desk (or one is there now), go to **Actions → Scout judges → Run workflow**. Within a minute, both replies should appear under their headings on the Judge Desk. The log prints how many scores each judge wrote.

## If something goes wrong
- **"No judge pack on the Judge Desk yet":** Claude's Monday step hasn't run or failed. Check the "Scout Engine: Monday ideas" scheduled task.
- **"Could not find a heading containing…":** someone renamed a heading on the Judge Desk. The script looks for headings containing "judge pack", "ChatGPT" and "Gemini".
- **HTTP 401/403:** wrong key, or the Notion integration isn't connected to the Judge Desk page.
- **HTTP 404 from OpenAI/Gemini:** the model name in the variables is wrong or retired. Update `OPENAI_MODEL` / `GEMINI_MODEL`.
- **One judge fails:** the other still runs, and Tuesday's step works with whatever scores exist. GitHub emails the repo owner when a run fails.
