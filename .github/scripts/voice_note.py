# -*- coding: utf-8 -*-
"""Runs inside GitHub Actions, where the OpenAI key lives.

For every job waiting in voice-in/:
  0. gather what is known about the clip - title, and with a YouTube key its
     description, tags and most-liked comments (the comments usually quote the
     joke, which is what stops the writing from being guesswork)
  1. transcribe the recording, if there is one (any language - it is detected)
  2. rewrite it as short, natural American English with a couple of emoji
  3. put the result in the shared database, so every phone sees it at once
  4. if the recording asked for it, make the spoken version as audio/<id>.mp3
  5. remove the recording

Nothing here is clever. It is deliberately linear so that a failure on one clip
cannot take the others down with it, and so that a half-finished run leaves the
recording in place to be tried again rather than silently losing it.
"""
import base64, json, os, re, sys, urllib.parse, urllib.request, urllib.error

ROOT   = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INBOX  = os.path.join(ROOT, "voice-in")
AUDIO  = os.path.join(ROOT, "audio")
CONFIG = os.path.join(ROOT, "tools", "sync-config.js")
LINKS  = os.path.join(ROOT, "links.txt")
KEY    = os.environ.get("OPENAI_API_KEY", "").strip()
YTKEY  = os.environ.get("YOUTUBE_API_KEY", "").strip()   # optional: adds comments

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


def title(vid):
    """What the clip is actually about, in YouTube's own words.

    WHY: dictation is full of things only a person watching can resolve - "what
    is this dog called?", "the fat one", "her". Without the title the rewrite has
    nothing to attach those to and answers with a shrug. oEmbed gives the title
    with no key, no account and one request, and a failure here is not worth
    stopping for - the note is simply written without the extra context.
    """
    url = ("https://www.youtube.com/oembed?format=json&url="
           + urllib.parse.quote("https://www.youtube.com/watch?v=" + vid, safe=""))
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return (json.loads(r.read()).get("title") or "").strip()
    except Exception as e:
        print("   (no title for %s: %s)" % (vid, e))
        return ""


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "break-time/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def evidence(vid):
    """Everything that can be known about a clip without watching it.

    The title always comes back - oEmbed needs no key at all. Description, tags
    and comments need a YouTube Data API key; without one the note is written
    from the title alone, which is thinner but never an error.

    Captions are deliberately not attempted. YouTube now answers the timedtext
    endpoint with an empty body for every format, from a browser and from a
    server alike - measured, not assumed.
    """
    ev = {"title": "", "channel": "", "desc": "", "tags": [], "comments": []}
    try:
        o = get("https://www.youtube.com/oembed?format=json&url="
                + urllib.parse.quote("https://www.youtube.com/watch?v=" + vid, safe=""))
        ev["title"] = (o.get("title") or "").strip()
        ev["channel"] = (o.get("author_name") or "").strip()
    except Exception as e:
        print("   (no title for %s: %s)" % (vid, e))
    if not YTKEY:
        return ev
    try:
        d = get("https://www.googleapis.com/youtube/v3/videos?part=snippet&id=%s&key=%s"
                % (vid, YTKEY))
        items = d.get("items") or []
        if items:
            sn = items[0]["snippet"]
            ev["title"] = sn.get("title") or ev["title"]
            ev["channel"] = sn.get("channelTitle") or ev["channel"]
            ev["desc"] = (sn.get("description") or "").strip()
            ev["tags"] = sn.get("tags") or []
    except Exception as e:
        print("   (no video details: %s)" % e)
    try:
        d = get("https://www.googleapis.com/youtube/v3/commentThreads"
                "?part=snippet&order=relevance&maxResults=25&textFormat=plainText"
                "&videoId=%s&key=%s" % (vid, YTKEY))
        for it in (d.get("items") or []):
            c = it["snippet"]["topLevelComment"]["snippet"]
            txt = re.sub(r"\s+", " ", (c.get("textDisplay") or "")).strip()
            if 4 <= len(txt) <= 220:
                ev["comments"].append((c.get("likeCount") or 0, txt))
        ev["comments"].sort(reverse=True)
        ev["comments"] = [t for _, t in ev["comments"][:15]]
    except Exception as e:
        print("   (no comments: %s)" % e)
    return ev


def brief(ev):
    """The evidence, as plain lines a model can read. Empty when there is none."""
    out = []
    if ev["title"]:   out.append("Clip title: " + ev["title"])
    if ev["channel"]: out.append("Channel: " + ev["channel"])
    if ev["desc"]:
        d = re.sub(r"https?://\S+", "", ev["desc"])
        d = re.sub(r"\s+", " ", d).strip()[:400]
        if d: out.append("Description: " + d)
    if ev["tags"]:    out.append("Tags: " + ", ".join(ev["tags"][:12]))
    if ev["comments"]:
        out.append("What people said underneath it, most liked first:")
        out += ["- " + c for c in ev["comments"]]
    return "\n".join(out)


COMMON = (
    "You write the one-line note a lecturer plays to the room after a short comedy clip "
    "during a class break.\n"
    "Natural, idiomatic American English - the way a person actually talks, not written "
    "prose.\n"
    "HARD LIMIT: about %d words, so it takes roughly %d seconds to say.\n"
    "Add one or two emoji where they genuinely land. Do not decorate every sentence.\n"
    "It is read out loud to a room of university students, so keep it clean.\n"
    "Never mention the title, the comments, or that you were shown anything. Never describe "
    "the clip as a clip.\n"
    "Reply with the note itself and nothing else - no quotes, no preamble.")

WRITE_SAID = (COMMON + "\n\n"
    "The input is dictated, may be English or Persian, and may ramble. Rewrite it, fix all "
    "grammar, and keep the speaker's meaning and their sense of humour. If the dictation was "
    "long, keep only the point worth hearing.\n"
    "You may also be shown what is known about the clip. Use it to resolve what the speaker "
    "means - names, characters, the situation - and answer plainly. If they ask something the "
    "evidence settles, just give the answer.")

WRITE_AUTO = (COMMON + "\n\n"
    "Nobody dictated anything this time. Write the note yourself, from the evidence below.\n"
    "THE TITLE IS THE FACT. It says what actually happens in the clip, and the note must be "
    "about that. Build it around the title.\n"
    "The comments tell you what people found funny about it - the line worth repeating, the "
    "detail everyone noticed. Use them for the angle, never for the subject. A comment that "
    "does not fit the title is about something else entirely: ignore it. Never build the note "
    "on a tangent from a comment, and never name another film or show unless the title itself "
    "does.\n"
    "Do NOT invent a detail the evidence does not support. If the evidence is thin, say "
    "something true and general about the humour rather than guessing at what happened.\n"
    "Write it as the lecturer's own aside to the class, not as a summary.")


def ask(said, clip, auto):
    if auto:
        return ((clip or "There is nothing known about this clip.")
                + (("\n\nThe lecturer added: " + said) if said else ""))
    return ((clip + "\n\n") if clip else "") + "What was said: " + said


def polish(said, cfg, clip="", auto=False):
    words = round(cfg["seconds"] * 2.6)
    body = json.dumps({
        "model": cfg["writer"], "temperature": 0.7,
        "messages": [
            {"role": "system", "content": (WRITE_AUTO if auto else WRITE_SAID) % (words, cfg["seconds"])},
            {"role": "user", "content": ask(said, clip, auto)}]}).encode()
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


def relabel(vid, note):
    """Put the note on the clip's line in links.txt, if the clip is live there.

    WHY: the main page reads its note from links.txt and plays audio/<id>.mp3.
    Those are two files, so they can disagree - and they did: a note written by
    hand next to a recording made from different words meant the button read out
    something the text never said. Writing both from this one string is the only
    way they cannot drift apart.
    """
    try:
        raw = open(LINKS, encoding="utf-8-sig").read()
    except Exception:
        return
    lines, hit = raw.split("\n"), False
    for i, line in enumerate(lines):
        bare = line.strip()
        # a parked line starts with # - leave it parked, and leave its note alone
        if not bare or bare.startswith("#") or bare.startswith("//"):
            continue
        url = bare.split("|")[0].strip()
        if vid not in url:
            continue
        lines[i] = url + " | " + note
        hit = True
    if not hit:
        print("   %s is not live in links.txt - the note stays in the database only" % vid)
        return
    open(LINKS, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    print("   links.txt updated, so the page shows the same words it speaks")


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
    # A .txt is treated as something already said in writing: it skips the
    # transcriber and goes straight to the rewrite and the voice. Useful when you
    # would rather type than talk, and the only way to make a note and its
    # recording match without dictating it.
    jobs = sorted(f for f in os.listdir(INBOX)
                  if not f.startswith(".") and f.lower().endswith(AUDIO_EXT + (".txt",)))
    if not jobs:
        print("Nothing waiting."); return
    print("%d recording(s) waiting. Models: %s / %s / %s"
          % (len(jobs), cfg["transcribe"], cfg["writer"], cfg["speaker"]))

    for name in jobs:
        path = os.path.join(INBOX, name)
        stem = os.path.splitext(name)[0]
        # The name carries the instructions. A video id never contains a dot, so
        # everything after the first one is a flag:
        #   <id>.webm            text only, from the recording
        #   <id>.voice.webm      and the spoken version
        #   <id>.auto.voice.txt  no recording - write it from the clip itself
        bits = stem.split(".")
        vid, flags = bits[0], set(bits[1:])
        want_audio = "voice" in flags
        auto = "auto" in flags
        print("\n== %s (audio: %s, written for you: %s)" % (vid, want_audio, auto))
        try:
            if name.lower().endswith(".txt"):
                # in auto mode this is an optional steer, not the note
                said = open(path, encoding="utf-8").read().strip()
                if not said and not auto:
                    raise RuntimeError("the text file was empty")
                if said: print("   read : %s" % said[:110])
            else:
                said = transcribe(path, cfg["transcribe"])
                if not said:
                    raise RuntimeError("nothing was heard in the recording")
                print("   heard: %s" % said[:110])
            ev = evidence(vid)
            seen = brief(ev)
            print("   about: %s%s" % (ev["title"][:70],
                                      " (+%d comments)" % len(ev["comments"]) if ev["comments"] else ""))
            if auto and not seen:
                raise RuntimeError("nothing is known about this clip, so there is nothing to write from")
            note = polish(said, cfg, seen, auto)
            print("   note : %s" % note[:110])
            firebase(cfg, "notes", vid, note)
            relabel(vid, note)
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
