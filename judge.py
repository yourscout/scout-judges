"""Scout Content Engine: automatic ChatGPT + Gemini judges.

Runs every Monday after Claude's idea round. It:
  1. reads this week's judge pack from the Notion "Judge Desk" page,
  2. sends it to ChatGPT (OpenAI API) and Gemini (Google AI API),
  3. writes each reply under its heading on the Judge Desk,
so the Tuesday Claude step can pick the Top 3 with all three judges' scores.

Needs these environment variables (GitHub Actions secrets / variables):
  NOTION_TOKEN     secret   Notion internal integration token (shared with the Judge Desk page)
  OPENAI_API_KEY   secret   OpenAI API key
  GEMINI_API_KEY   secret   Google AI Studio API key
  OPENAI_MODEL     variable OpenAI model name to use as the judge
  GEMINI_MODEL     variable Gemini model name to use as the judge
  JUDGE_DESK_ID    variable (optional) Notion page ID of the Judge Desk
Only the Python standard library is used, so there is nothing to install.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

NOTION_VERSION = "2022-06-28"
DEFAULT_JUDGE_DESK_ID = "40e0ae8b62bf8108bbe8d43cfbfc032f"
PLACEHOLDER = "The Monday run puts the pack here"

SYSTEM_PROMPT = (
    "You are a tough, sceptical short-form social media strategist judging content ideas "
    "for an Australian startup. Follow the scoring instructions exactly and reply only in "
    "the requested line format, with no introduction or summary."
)


# ---------------------------------------------------------------- HTTP helpers

def http(method, url, headers=None, body=None, retries=3):
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"{method} {url.split('?')[0]} failed: HTTP {e.code} {detail}") from None
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"{method} {url.split('?')[0]} failed: {e.reason}") from None


def env(name, required=True, default=None):
    value = os.environ.get(name, "").strip() or default
    if required and not value:
        sys.exit(f"Missing required setting: {name}")
    return value


# ---------------------------------------------------------------- Notion

def notion_headers():
    return {
        "Authorization": f"Bearer {env('NOTION_TOKEN')}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def get_children(block_id):
    blocks, cursor = [], None
    while True:
        url = f"https://api.notion.com/v1/blocks/{block_id}/children?page_size=100"
        if cursor:
            url += f"&start_cursor={cursor}"
        res = http("GET", url, notion_headers())
        blocks.extend(res.get("results", []))
        if not res.get("has_more"):
            return blocks
        cursor = res["next_cursor"]


def plain_text(block):
    content = block.get(block["type"], {})
    return "".join(rt.get("plain_text", "") for rt in content.get("rich_text", []))


def is_heading(block):
    return block["type"] in ("heading_1", "heading_2", "heading_3")


def section(blocks, heading_contains):
    """Return (heading_block, [blocks under it until the next heading])."""
    for i, b in enumerate(blocks):
        if is_heading(b) and heading_contains.lower() in plain_text(b).lower():
            body = []
            for nb in blocks[i + 1:]:
                if is_heading(nb):
                    break
                body.append(nb)
            return b, body
    raise RuntimeError(f"Could not find a heading containing '{heading_contains}' on the Judge Desk.")


def read_pack(blocks):
    _, body = section(blocks, "judge pack")
    text = "\n".join(plain_text(b) for b in body if b["type"] in ("code", "paragraph", "quote", "callout"))
    text = text.strip()
    if not text or PLACEHOLDER.lower() in text.lower() or "IDEA-" not in text:
        return None
    return text


def chunks(text, size=1900):
    out, current = [], ""
    for line in text.splitlines():
        while len(line) > size:
            out.append(line[:size])
            line = line[size:]
        if len(current) + len(line) + 1 > size:
            out.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        out.append(current)
    return out


def write_reply(blocks, heading_contains, reply):
    heading, old = section(blocks, heading_contains)
    for b in old:  # clear last week's reply
        http("DELETE", f"https://api.notion.com/v1/blocks/{b['id']}", notion_headers())
    new_blocks = [
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": [{"type": "text", "text": {"content": c.rstrip()}}]}}
        for c in chunks(reply)
    ][:100]
    page_id = heading["parent"]["page_id"]
    http("PATCH", f"https://api.notion.com/v1/blocks/{page_id}/children", notion_headers(),
         {"children": new_blocks, "after": heading["id"]})


# ---------------------------------------------------------------- Judges

def ask_chatgpt(pack):
    res = http(
        "POST", "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {env('OPENAI_API_KEY')}", "Content-Type": "application/json"},
        {"model": env("OPENAI_MODEL"),
         "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": pack}]},
    )
    return res["choices"][0]["message"]["content"].strip()


def ask_gemini(pack):
    model = env("GEMINI_MODEL")
    res = http(
        "POST", f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        {"x-goog-api-key": env("GEMINI_API_KEY"), "Content-Type": "application/json"},
        {"systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
         "contents": [{"role": "user", "parts": [{"text": pack}]}]},
    )
    parts = res["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts).strip()


def count_scores(reply):
    return sum(1 for line in reply.splitlines() if "IDEA-" in line.upper() and ":" in line)


# ---------------------------------------------------------------- Main

def main():
    desk_id = env("JUDGE_DESK_ID", required=False, default=DEFAULT_JUDGE_DESK_ID)
    blocks = get_children(desk_id)
    pack = read_pack(blocks)
    if not pack:
        print("No judge pack on the Judge Desk yet (has Claude's Monday step run?). Nothing to do.")
        return

    judges = [("ChatGPT", ask_chatgpt), ("Gemini", ask_gemini)]
    failures = 0
    for name, ask in judges:
        try:
            reply = ask(pack)
            n = count_scores(reply)
            if n == 0:
                raise RuntimeError(f"{name} replied but no 'IDEA-n: score' lines were found:\n{reply[:500]}")
            write_reply(get_children(desk_id), name, reply)
            print(f"{name}: wrote {n} scores to the Judge Desk.")
        except Exception as e:  # keep going so one judge failing doesn't block the other
            failures += 1
            print(f"{name} FAILED: {e}", file=sys.stderr)
            try:  # make the failure visible on the Judge Desk too
                write_reply(get_children(desk_id), name, f"⚠️ {name} judge failed: {str(e)[:1500]}")
            except Exception as e2:
                print(f"Could not write the error to Notion: {e2}", file=sys.stderr)

    if failures:
        sys.exit(f"{failures} judge(s) failed. See the Judge Desk or the log above.")


if __name__ == "__main__":
    main()
