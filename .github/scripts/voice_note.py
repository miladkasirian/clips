# -*- coding: utf-8 -*-
"""Runs inside GitHub Actions, where the OpenAI key lives.

For every recording waiting in voice-in/:
  1. transcribe it (any language - it is detected)
  2. rewrite it as short, natural American English with a couple of emoji
  3. put the result in the shared database, so every phone sees it at once
  4. if the recording asked for it, make the spoken version as audio/<id>.mp3
  5. remove the recording

Nothing here is clever. It is deliberately linear so that a failure on one clip
cannot take the others down with it, and so that a half-finished run leaves the
recording in place to be tried again rather than silently losing it.
"""
import base64, json, os, re, sys, urllib.request, urllib.error

ROOT   = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INBOX  = os.path.join(ROOT, "voice-in")
AUDIO  = os.path.join(ROOT, "audio")
CONFIG = os.path.join(ROOT, "tools", "sync-config.js")
KEY    = os.environ.get("OPENAI_API_KEY", "").strip()

TRANSCRIBE = "gpt-4o-transcribe"
WRITER     = "gpt-4o-mini"
SPEAKER    = "gpt-4o-mini-tts"
VOICE      = "onyx"
SECONDS    = 20


def config():
    """The database address and the model names live beside the page, so they can
    be changed without touching this script."""
    out = {"db": "", "room": "default", "transcribe": TRANSCRIBE, "writer": WRITER,
           "speaker": SPEAKER, "voice": VOICE, "seconds": SECONDS}
    try:
        txt = open(CONFIG, encoding="utf-8").read()
    except Exception:
        return out
    for key, pat in [("db", r'db:\s*"([^"]*)"'), ("room", r'room:\s*"([^"]*)"'),
                     ("transcribe", r'transcribe:\s*"([^"]*)"'), ("writer", r'writer:\s*"([^"]*)"'),
                     ("speaker", r'speaker:\s*"([^"]*)"'), ("voice", r'voice:\s*"([^"]*)"')]:
        m = re.search(pat, txt)
        if m: out[key] = m.group(1)
    m = re.search(r'seconds:\s*(\d+)', txt)
    if m: out["seconds"] = int(m.group(1))
    return out


def post(url, data, headers, timeout=180):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError("HTTP %s from %s: %s" % (e.code, url.split("/v1/")[-1], body))


def multipart(fields, filename, filedata, field="file"):
    b = "----breaktime%d" % os.getpid()
    out = b""
    for k, v in fields.items():
        out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (b, k, v)).encode()
    out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n" % (b, field, filename)).encode()
    out += filedata + ("\r\n--%s--\r\n" % b).encode()
    return out, "multipart/form-data; boundary=" + b


def transcribe(path, model):
    data = open(path, "rb").read()
    body, ctype = multipart({"model": model}, os.path.basename(path), data)
    raw = post("https://api.openai.com/v1/audio/transcriptions", body,
               {"Authorization": "Bearer " + KEY, "Content-Type": ctype})
    return (json.loads(raw).get("text") or "").strip()


def polish(said, cfg):
    words = round(cfg["seconds"] * 2.6)
    body = json.dumps({
        "model": cfg["writer"], "temperature": 0.7,
        "messages": [
            {"role": "system", "content":
                "You write the one-line note a lecturer plays after a short comedy clip during a "
                "class break. The input is dictated, may be English or Persian, and may ramble.\n"
                "Rewrite it as natural, idiomatic American English - the way a person actually "
                "talks, not written prose. Fix all grammar. Keep the speaker's meaning and their "
                "sense of humour.\n"
                "HARD LIMIT: about %d words, so it takes roughly %d seconds to say. If the "
                "dictation was long, keep only the point worth hearing.\n"
                "Add one or two emoji where they genuinely land. Do not decorate every sentence.\n"
                "It is read out loud to a room of university students, so keep it clean.\n"
                "Reply with the note itself and nothing else - no quotes, no preamble."
                % (words, cfg["seconds"])},
            {"role": "user", "content": said}]}).encode()
    raw = post("https://api.openai.com/v1/chat/completions", body,
               {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    txt = json.loads(raw)["choices"][0]["message"]["content"].strip()
    # a bar would break the "url | note" line format the list file uses
    return re.sub(r"\s+", " ", txt).strip('"“”').replace("|", "/")


def speak(text, cfg, dest):
    body = json.dumps({
        "model": cfg["speaker"], "voice": cfg["voice"], "input": text,
        "response_format": "mp3",
        "instructions": "American man, warm and conversational, with comic timing. Speak it the "
                        "way a friend would say it, not the way a newsreader would. Let the funny "
                        "parts land - a smile in the voice, a slight laugh where it fits. "
                        "Never sound like an announcer."}).encode()
    raw = post("https://api.openai.com/v1/audio/speech", body,
               {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, "wb").write(raw)


def firebase(cfg, child, vid, value):
    if not cfg["db"]:
        print("   (no database address configured - the note stays in the repository only)")
        return
    url = "%s/breaktime/%s/%s.json" % (cfg["db"].rstrip("/"), cfg["room"], child)
    body = json.dumps({vid: value}).encode()
    req = urllib.request.Request(url, data=body, method="PATCH",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: r.read()
    except Exception as e:
        print("   could not reach the database: %s" % e)


def main():
    if not KEY:
        print("No OPENAI_API_KEY. Add a repository secret named CLIPS.", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(INBOX):
        print("Nothing waiting."); return
    cfg = config()
    # only audio - the folder also holds a README, and handing that to the
    # transcriber would burn a call and produce nonsense
    AUDIO_EXT = (".webm", ".mp4", ".m4a", ".mp3", ".ogg", ".wav", ".flac", ".mpga", ".mpeg")
    jobs = sorted(f for f in os.listdir(INBOX)
                  if not f.startswith(".") and f.lower().endswith(AUDIO_EXT))
    if not jobs:
        print("Nothing waiting."); return
    print("%d recording(s) waiting. Models: %s / %s / %s"
          % (len(jobs), cfg["transcribe"], cfg["writer"], cfg["speaker"]))

    for name in jobs:
        path = os.path.join(INBOX, name)
        stem = os.path.splitext(name)[0]
        # "<id>.webm" makes text only; "<id>.voice.webm" also makes the spoken file
        want_audio = stem.endswith(".voice")
        vid = stem[:-6] if want_audio else stem
        print("\n== %s (audio: %s)" % (vid, want_audio))
        try:
            said = transcribe(path, cfg["transcribe"])
            if not said:
                raise RuntimeError("nothing was heard in the recording")
            print("   heard: %s" % said[:110])
            note = polish(said, cfg)
            print("   note : %s" % note[:110])
            firebase(cfg, "notes", vid, note)
            if want_audio:
                speak(note, cfg, os.path.join(AUDIO, vid + ".mp3"))
                firebase(cfg, "voices", vid, True)
                print("   spoken version written to audio/%s.mp3" % vid)
            os.remove(path)
            print("   done")
        except Exception as e:
            # the recording is deliberately left where it is, so a rerun retries it
            print("   FAILED: %s" % e, file=sys.stderr)

if __name__ == "__main__":
    main()
