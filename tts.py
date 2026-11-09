"""Scout voiceovers: ElevenLabs text-to-speech with word timings.

How it works:
  1. Claude commits a request file to vo/requests/<name>.json and pushes.
  2. This runs in GitHub Actions (.github/workflows/voiceover.yml), calls ElevenLabs,
     and commits the results back to vo/out/:
        <name>.mp3          the voiceover
        <name>.words.json   start/end time of every word (for synced captions)
        voices.json         the voices this account can use (when a request asks for it)
     Errors are written to vo/out/<name>.error.txt so they're visible without the Actions page.

Request file format (vo/requests/<name>.json):
  {"text": "...", "voice": "Charlie" or a voice_id, "model": "eleven_multilingual_v2",
   "stability": 0.45, "similarity": 0.8, "style": 0.2, "speed": 1.0}
  or {"list_voices": true}
A request is skipped if its output already exists, unless it has "version" bumped
(the output records the version it was made from).

Needs the GitHub secret ELEVENLABS_API_KEY. Python standard library only.
"""

import base64
import glob
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.elevenlabs.io/v1"
REQ_DIR, OUT_DIR = "vo/requests", "vo/out"
DEFAULT_MODEL = "eleven_multilingual_v2"


def call(method, path, body=None):
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing ELEVENLABS_API_KEY. Add it under repo Settings > Secrets and variables > Actions.")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"xi-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ElevenLabs {method} {path} failed: HTTP {e.code} {e.read().decode(errors='replace')[:800]}") from None


def list_voices():
    res = call("GET", "/voices")
    voices = [{"name": v.get("name"), "voice_id": v.get("voice_id"), "category": v.get("category"),
               "labels": v.get("labels", {}), "description": v.get("description")}
              for v in res.get("voices", [])]
    return sorted(voices, key=lambda v: (v["name"] or "").lower())


def resolve_voice(voice):
    if not voice:
        raise RuntimeError("Request has no 'voice'.")
    voices = list_voices()
    for v in voices:
        if voice in (v["voice_id"], v["name"]) or (v["name"] or "").lower().startswith(voice.lower()):
            return v["voice_id"]
    if len(voice) >= 20:  # looks like an ID from the voice library not yet in the account list
        return voice
    raise RuntimeError(f"Voice '{voice}' not found. Available: " + ", ".join(v["name"] for v in voices))


def words_from_alignment(al):
    chars, starts, ends = al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]
    words, cur, s, e = [], "", None, None
    for c, cs, ce in zip(chars, starts, ends):
        if c.isspace():
            if cur:
                words.append({"word": cur, "start": round(s, 3), "end": round(e, 3)})
            cur, s = "", None
            continue
        if s is None:
            s = cs
        cur += c
        e = ce
    if cur:
        words.append({"word": cur, "start": round(s, 3), "end": round(e, 3)})
    return words


def make(name, req):
    voice_id = resolve_voice(req.get("voice"))
    settings = {"stability": req.get("stability", 0.45), "similarity_boost": req.get("similarity", 0.8),
                "style": req.get("style", 0.2), "use_speaker_boost": True}
    if "speed" in req:
        settings["speed"] = req["speed"]
    res = call("POST", f"/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_128",
               {"text": req["text"], "model_id": req.get("model", DEFAULT_MODEL), "voice_settings": settings})
    with open(os.path.join(OUT_DIR, f"{name}.mp3"), "wb") as f:
        f.write(base64.b64decode(res["audio_base64"]))
    al = res.get("alignment") or res.get("normalized_alignment")
    out = {"version": req.get("version", 1), "voice_id": voice_id, "model": req.get("model", DEFAULT_MODEL),
           "text": req["text"], "words": words_from_alignment(al)}
    with open(os.path.join(OUT_DIR, f"{name}.words.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"{name}: {len(out['words'])} words, {out['words'][-1]['end']:.1f}s")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    failures = 0
    for path in sorted(glob.glob(os.path.join(REQ_DIR, "*.json"))):
        name = os.path.splitext(os.path.basename(path))[0]
        err_path = os.path.join(OUT_DIR, f"{name}.error.txt")
        try:
            req = json.load(open(path))
            if req.get("list_voices"):
                with open(os.path.join(OUT_DIR, "voices.json"), "w") as f:
                    json.dump(list_voices(), f, indent=1)
                print("voices.json written")
            else:
                done = os.path.join(OUT_DIR, f"{name}.words.json")
                if os.path.exists(done) and json.load(open(done)).get("version", 1) == req.get("version", 1):
                    continue
                make(name, req)
            if os.path.exists(err_path):
                os.remove(err_path)
        except Exception as e:
            failures += 1
            print(f"{name} FAILED: {e}", file=sys.stderr)
            with open(err_path, "w") as f:
                f.write(str(e)[:3000] + "\n")
    if failures:
        print(f"{failures} request(s) failed; see vo/out/*.error.txt", file=sys.stderr)


if __name__ == "__main__":
    main()
