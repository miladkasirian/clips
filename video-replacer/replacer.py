# -*- coding: utf-8 -*-
"""Course Video Replacer - your lecture, in an American voice, still in sync.

    your.mp4  ->  your.en.mp4  +  your.fa.srt  +  your.en.srt  +  your.report.txt

WHAT DOES THE WORK
Everything that touches the video is ffmpeg, not a model. A 500MB file is never
uploaded anywhere and never re-encoded: only the audio leaves this machine, as a
32kbps mono mp3 - about 14MB for an hour - and the finished video is muxed with
`-c:v copy`, which is a stream copy and takes seconds regardless of size.

WHY NOT YOUTUBE
Uploading the video to get YouTube's captions would cost 1600 quota units per
upload (six a day out of 10,000), needs OAuth rather than the API key, only
returns captions for a video you own, and is widely reported to refuse the
automatic ones. It would also mean waiting on a machine you do not control and
then remembering to delete a private lecture from the internet. Extracting the
audio here is faster, deterministic, cheaper, gives real word timestamps, and
leaves nothing anywhere to clean up.

THE ONE HARD PROBLEM
English is never the same length as the Persian it came from. This keeps the
picture untouched and the sound in step with it, in that order:
  1. say it at a natural speed;
  2. if it will not fit, speed it up - but never past the cap in config.json
     (atempo changes speed without changing pitch, so the voice does not chirp);
  3. if it still will not fit, use the silence that follows it;
  4. if it STILL will not fit, let it run over and say so in the report, so you
     can shorten that sentence yourself rather than find out in class.
"""
import array, base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile, time
import urllib.error, urllib.parse, urllib.request
if os.name == "nt":
    # a frozen app has no console; every helper must run without flashing one up
    _NOWINDOW = {"creationflags": 0x08000000}
else:
    _NOWINDOW = {}

# Frozen into an exe, "where I am" is the exe's folder, not a temp directory
# PyInstaller unpacked itself into. Everything the user owns - the key, the
# glossary, the voices, the output - lives beside the exe.
if getattr(sys, "frozen", False):
    HERE = os.path.dirname(os.path.abspath(sys.executable))
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
OUT  = os.path.join(HERE, "output")

# whisper knows about a hundred languages and works out which one it is hearing on
# its own, which is right nearly always. Naming it only matters when a lecture is
# genuinely bilingual and the guess wanders. These are the ones worth a list; any
# other ISO code can be typed straight into the box.
LANGUAGES = [
    ("Work it out from the audio", ""),
    ("Persian \u0641\u0627\u0631\u0633\u06cc", "fa"),
    ("English", "en"),
    ("Hindi \u0939\u093f\u0928\u094d\u0926\u0940", "hi"),
    ("Arabic \u0627\u0644\u0639\u0631\u0628\u064a\u0629", "ar"),
    ("Urdu \u0627\u0631\u062f\u0648", "ur"),
    ("Turkish", "tr"),
    ("French", "fr"),
    ("German", "de"),
    ("Spanish", "es"),
    ("Russian", "ru"),
    ("Chinese", "zh"),
]


def language_label(code):
    """The code stored in config, as something a person reads."""
    code = str(code or "").strip().lower()
    for name, c in LANGUAGES:
        if c == code:
            return name
    return code          # an ISO code typed by hand is shown as typed


def language_code(label):
    """What the person picked or typed, as the code whisper wants."""
    label = str(label or "").strip()
    for name, c in LANGUAGES:
        if name == label:
            return c
    return label.lower()


DEFAULTS = {
    "transcribe":  "whisper-1",      # the ONLY model that returns timestamps
    "writer":      "gpt-4o",         # Persian/English -> natural American English
    "speaker":     "gpt-4o-mini-tts",
    "voice":       "onyx",
    "max_tempo":   1.20,             # 1.0 = never speed up. Past ~1.3 it is audible
    "min_tempo":   0.90,
    "max_drift":   0.75,             # a line is never later than this behind its own moment
    "catch_up_tempo": 1.45,          # how hard it may hurry while it is behind
    "squeeze_tempo": 1.60,           # ...and rather than cut a line short at all
    "writer_prompt": "",             # your own instructions for the English; blank = mine
    "voice_rates":  {},              # words a second, measured once per voice
    "voice_retries": None,           # extra attempts at a bad take; None = 2 cloned, 1 bought
    "shortest_take": 0.60,           # ...and what counts as bad: it dropped words
    "longest_take":  1.65,           # ...or it rambled
    "longest_line": 10.0,            # fragments are joined into sentences up to this long
    "join_gap":     0.8,             # ...as long as the pause between them is under this
    "language":     "",              # "fa", "en"... blank lets it work the language out
    "transcript_from": "here",       # "here" = OpenAI; "youtube" = your own upload
    "youtube_longest": 14.0,         # YouTube's cues are rejoined and cut at real pauses
    "youtube_wait_minutes": 20,      # how long to wait for YouTube to write the captions
    "youtube_delete":  True,         # take the upload down again once we have the words
    "out_dir":         "",           # where results go; blank means output\\ beside the app
    "use_gpu":         True,         # the graphics card, when installing the local voice
    "last_video":      "",           # so the app opens on the file you were working on
    "proofread":    True,            # repair the transcript's spelling before translating
    "review":       True,            # stop and show the English before speaking it
    "chunk_minutes": 12,             # transcription is sent in pieces this long
    "batch":       40,               # segments per translation request
    "sample_rate": 24000,            # what the speech endpoint returns
    "keep_work":   False,
}


# ----------------------------------------------------------------- plumbing
# The Windows console is cp1252 by default, and the first line this printed of a
# Persian transcript killed the run outright. Nothing here is worth losing an
# hour's work over: say it in UTF-8, and replace anything the console cannot draw.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(msg):
    try:
        print(msg, flush=True)
    except Exception:
        print(str(msg).encode("ascii", "replace").decode("ascii"), flush=True)


def die(msg):
    log("\n  STOPPED: %s\n" % msg)
    sys.exit(1)


def config():
    cfg = dict(DEFAULTS)
    path = os.path.join(HERE, "config.json")
    if os.path.exists(path):
        try:
            cfg.update(json.load(open(path, encoding="utf-8-sig")))
        except Exception as e:
            log("  (config.json could not be read: %s - using the defaults)" % e)
    return cfg


def key():
    """The key stays on this machine. key.txt is in .gitignore, and the folder in
    the repository is the code only."""
    k = os.environ.get("OPENAI_API_KEY", "").strip()
    if k:
        return k
    path = os.path.join(HERE, "key.txt")
    if os.path.exists(path):
        k = open(path, encoding="utf-8-sig").read().strip()
    if not k:
        die("No OpenAI key. Put it in key.txt beside this script, on one line.\n"
            "  That file never goes into the repository.")
    return k


def tool(name):
    """ffmpeg, wherever it ended up.

    PATH first, then the portable copy Setup.bat unpacks beside this, then the
    folder winget installs into - because winget adds itself to PATH for shells
    started AFTERWARDS, and the one you are in was started before. Looking there
    is the difference between "run Setup.bat" and "it says ffmpeg is missing and
    I just installed it".
    """
    found = shutil.which(name)
    if found:
        return found
    local = os.path.join(HERE, "ffmpeg", "bin", name + ".exe")
    if os.path.exists(local):
        return local
    packages = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
    if os.path.isdir(packages):
        for root, dirs, files in os.walk(packages):
            if name + ".exe" in files and os.path.basename(root).lower() == "bin":
                return os.path.join(root, name + ".exe")
    die("%s is not installed. Run Setup.bat once - it fetches it." % name)


def run(args, capture=True):
    p = subprocess.run(args, stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                       **_NOWINDOW)
    if p.returncode != 0:
        raise RuntimeError("%s failed:\n%s" % (os.path.basename(args[0]),
                                               (p.stderr or "")[-800:]))
    return p.stdout or ""


# ----------------------------------------------------------------- the API
def post(url, data, headers, timeout=600):
    import urllib.request, urllib.error
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError("HTTP %s from %s\n%s" % (e.code, url.split("/v1/")[-1], body))


def multipart(fields, filename, filedata, field="file"):
    b = "----coursereplacer%d" % os.getpid()
    out = b""
    for k, v in fields.items():
        if isinstance(v, (list, tuple)):
            for one in v:
                out += ('--%s\r\nContent-Disposition: form-data; name="%s[]"\r\n\r\n%s\r\n'
                        % (b, k, one)).encode()
        else:
            out += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                    % (b, k, v)).encode()
    out += ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n' % (b, field, filename)).encode()
    out += filedata + ("\r\n--%s--\r\n" % b).encode()
    return out, "multipart/form-data; boundary=" + b


# ----------------------------------------------------------------- ffmpeg
def duration(path):
    out = run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nk=1:nw=1", path])
    return float(out.strip())


def extract_audio(video, dest):
    """Mono, 16kHz, 32kbps. Speech needs nothing more, and an hour lands at about
    14MB - comfortably inside what the transcriber accepts."""
    run([tool("ffmpeg"), "-y", "-v", "error", "-i", video, "-vn", "-ac", "1",
         "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k", dest])


def silences(path, floor="-32dB", least=0.45, with_length=False):
    """Where it goes quiet, and for how long.

    The length matters: a hesitation in the middle of a sentence and the pause at
    the end of one look identical until you measure them."""
    p = subprocess.run([tool("ffmpeg"), "-v", "info", "-i", path, "-af",
                        "silencedetect=noise=%s:d=%s" % (floor, least), "-f", "null", "-"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                       text=True, encoding="utf-8", errors="replace", **_NOWINDOW)
    marks, at = [], None
    for m in re.finditer(r"silence_(start|duration):\s*([\d.]+)", p.stderr or ""):
        if m.group(1) == "start":
            at = float(m.group(2))
        elif at is not None:
            marks.append((at, float(m.group(2))))
            at = None
    return marks if with_length else [t for t, _ in marks]


def cut_points(path, total, minutes):
    """Chunk boundaries: the quiet moment nearest each target time."""
    span = minutes * 60.0
    if total <= span:
        return []
    quiet, points, target = silences(path), [], span
    while target < total - 30:
        near = min(quiet, key=lambda s: abs(s - target)) if quiet else target
        # only trust a silence that is actually near the target
        points.append(near if abs(near - target) < span * 0.35 else target)
        target = points[-1] + span
    return points


def slice_audio(path, points, folder):
    """[(file, offset_seconds)] - the offset is what puts the timestamps back on
    the clock of the whole lecture."""
    if not points:
        return [(path, 0.0)]
    edges = [0.0] + points + [None]
    out = []
    for i in range(len(edges) - 1):
        dest = os.path.join(folder, "chunk%02d.mp3" % i)
        args = [tool("ffmpeg"), "-y", "-v", "error", "-ss", "%.3f" % edges[i], "-i", path]
        if edges[i + 1] is not None:
            args += ["-t", "%.3f" % (edges[i + 1] - edges[i])]
        args += ["-c", "copy", dest]
        run(args)
        out.append((dest, edges[i]))
    return out


def decode_pcm(path, rate, tempo=1.0):
    """One segment of speech as raw 16-bit mono samples, optionally sped up.
    atempo keeps the pitch, so a faster line still sounds like the same person."""
    args = [tool("ffmpeg"), "-y", "-v", "error", "-i", path]
    if abs(tempo - 1.0) > 0.005:
        # atempo only accepts 0.5-2.0 per stage; chain if ever asked for more
        stages, t = [], tempo
        while t > 2.0:
            stages.append("atempo=2.0"); t /= 2.0
        while t < 0.5:
            stages.append("atempo=0.5"); t *= 2.0
        stages.append("atempo=%.4f" % t)
        args += ["-filter:a", ",".join(stages)]
    args += ["-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(rate), "-"]
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_NOWINDOW)
    if p.returncode != 0:
        raise RuntimeError("could not decode %s:\n%s" % (path, p.stderr.decode("utf-8", "replace")[-400:]))
    return p.stdout


# ----------------------------------------------------------------- the work
def hint(cfg):
    """What to expect. Measured on a real lecture: this is the single change that
    improved the Persian most - "tabdil" came back as تبلیل without it and تبدیل
    with it. Both sides of the glossary go in, because half the errors are English
    words spoken inside a Persian sentence and written back phonetically: "config"
    as کانفک, "Add Voice" as اد ویس."""
    terms = []
    for a, b in glossary():
        terms += [a, b]
    if not terms:
        return ""
    return "A university lecture. Words used: " + ", ".join(dict.fromkeys(terms))


def transcribe(chunks, cfg, k):
    """Segments with real timestamps, on the clock of the whole lecture."""
    segs = []
    tip, lang = hint(cfg), str(cfg.get("language", "")).strip()
    for i, (path, offset) in enumerate(chunks, 1):
        size = os.path.getsize(path) / 1e6
        log("     piece %d of %d  (%.1f MB)" % (i, len(chunks), size))
        fields = {"model": cfg["transcribe"], "response_format": "verbose_json",
                  "timestamp_granularities": ["segment"]}
        if lang: fields["language"] = lang
        if tip:  fields["prompt"] = tip
        body, ctype = multipart(fields, os.path.basename(path), open(path, "rb").read())
        raw = post("https://api.openai.com/v1/audio/transcriptions", body,
                   {"Authorization": "Bearer " + k, "Content-Type": ctype})
        got = json.loads(raw)
        for s in got.get("segments") or []:
            text = (s.get("text") or "").strip()
            if not text:
                continue
            segs.append({"start": float(s["start"]) + offset,
                         "end": float(s["end"]) + offset, "said": text})
        if i == 1:
            log("     heard: %s" % (segs[0]["said"][:70] if segs else "(nothing)"))
    segs.sort(key=lambda s: s["start"])
    return segs


WORDS_PER_SECOND = 2.6      # measured: what the voice actually speaks at


def merge(segs, longest=10.0, gap=0.8):
    """Join the fragments into sentences.

    WHY THIS IS THE WHOLE FIX. A 100-second lecture came back as 36 pieces, some
    of them two seconds long. Two seconds holds about five spoken words, and
    "When I select Spin here, the videos start playing" is nine - so that line
    could not fit however it was written, while "And there," next door sat in
    two seconds with nothing to do. Neither piece can borrow from the other
    while they are separate lines. Merged, the pair has plenty of room.

    Nothing is lost: the merged line keeps the start of the first fragment and
    the end of the last, so it still sits on the same stretch of video.
    """
    out = []
    for s in segs:
        if out and (s["start"] - out[-1]["end"] <= gap
                    and s["end"] - out[-1]["start"] <= longest):
            out[-1]["end"] = s["end"]
            out[-1]["said"] = (out[-1]["said"].rstrip() + " " + s["said"].lstrip()).strip()
        else:
            out.append(dict(s))
    return out


def glossary():
    """Words the writer would otherwise get wrong.

    A name you invented has no translation. Said in Persian, "MLAD" comes out of
    the transcriber as ملاد and the writer turns it into "Milad" - a different
    thing entirely, in every line, for ever. One line in glossary.txt fixes it
    once instead of by hand every time:

        ملاد = MLAD
        اسپین = Spin
    """
    path = os.path.join(HERE, "glossary.txt")
    if not os.path.exists(path):
        return []
    pairs = []
    for line in open(path, encoding="utf-8-sig"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            a, b = line.split("=", 1)
            if a.strip() and b.strip():
                pairs.append((a.strip(), b.strip()))
    return pairs


def pronounce():
    """say.txt: how a written word must be SPOKEN.

    Separate from glossary.txt on purpose. The glossary decides what is written -
    it belongs in the subtitles and in the report. This decides only what reaches
    the voice: "ChatGPT" is right on the screen and wrong in the mouth, and
    "Chat G P T" is the reverse. Applied to a copy of the line, at the last
    moment, so nothing you read is ever changed."""
    path = os.path.join(HERE, "say.txt")
    pairs = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8-sig"):
            line = line.split("#")[0].strip()
            if "=" in line:
                a, b = line.split("=", 1)
                if a.strip():
                    pairs.append((a.strip(), b.strip()))
    return pairs


def as_spoken(text, pairs=None):
    """The line as the voice should receive it."""
    for a, b in (pairs if pairs is not None else pronounce()):
        text = re.sub(r"(?<!\w)%s(?!\w)" % re.escape(a), b, text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def budget(segs, i, cps=WORDS_PER_SECOND):
    """How many words this line has room for, from the gap to the next one."""
    nxt = segs[i + 1]["start"] if i + 1 < len(segs) else segs[i]["end"] + 3.0
    return max(3, int((nxt - segs[i]["start"]) * cps))


PROOF = (
    "You are correcting the automatic transcript of a university lecture. The speaker mixes his "
    "own language with English technical words, and the transcriber mishears things a reader "
    "would fix instantly from context: letters that sound the same, words split or run together, "
    "and English terms written back phonetically.\n"
    "Fix the spelling and the word boundaries so it reads correctly. Write English technical "
    "words in Latin letters where that is plainly what was said.\n"
    "Do NOT translate. Do NOT summarise. Do NOT add, remove or reorder anything, and do not "
    "invent a word to fill a gap - where a passage is genuinely unclear, leave it exactly as it "
    "is. You are proofreading, not rewriting.\n"
    "Reply with a JSON object whose keys are the line numbers you were given and whose values "
    "are the corrected text. Nothing else."
)


def proofread(segs, cfg, k):
    """The transcriber's mistakes are spelling by the time they reach here, and
    spelling can be fixed by something that reads the language - without ever
    hearing the audio again. It is told firmly not to invent: a wrong word is
    better than a confident wrong sentence, because the wrong word is obvious."""
    size = max(5, int(cfg.get("batch", 40)))
    terms = glossary()
    rules = PROOF
    if terms:
        rules += "\n\nThese are fixed: " + ", ".join("%s -> %s" % (a, b) for a, b in terms)
    fixed = 0
    for a in range(0, len(segs), size):
        part = segs[a:a + size]
        lines = "\n".join("%d. %s" % (a + i + 1, s["said"]) for i, s in enumerate(part))
        try:
            body = json.dumps({"model": cfg["writer"], "temperature": 0.1,
                               "response_format": {"type": "json_object"},
                               "messages": [{"role": "system", "content": rules},
                                            {"role": "user", "content": lines}]}).encode()
            got = json.loads(json.loads(post(
                "https://api.openai.com/v1/chat/completions", body,
                {"Authorization": "Bearer " + k,
                 "Content-Type": "application/json"}))["choices"][0]["message"]["content"])
        except Exception as e:
            log("     (could not tidy lines %d-%d: %s)" % (a + 1, a + len(part), str(e)[:60]))
            continue
        for i in range(len(part)):
            new = got.get(str(a + i + 1))
            if new and str(new).strip() and str(new).strip() != part[i]["said"].strip():
                part[i]["said"] = re.sub(r"\s+", " ", str(new)).strip()
                fixed += 1
    return segs, fixed


TRANSLATE = (
    "You are turning a university lecturer's own recording into the English he would have "
    "spoken himself. He may have lectured in any language - do not assume which one - and it "
    "is speech, so it rambles, repeats and restarts.\n"
    "If he was already speaking English, this is a rewrite and not a translation: keep his own "
    "words wherever they work, and only fix what a listener would stumble over.\n"
    "Rewrite each numbered line as natural, idiomatic American English - the way a lecturer "
    "actually talks to a room, not written prose. Fix every grammatical error. Keep his "
    "meaning, his emphasis and his examples exactly; keep every number, name and technical "
    "term.\n"
    "LENGTH IS A HARD CONSTRAINT, not a preference. Each line is spoken out loud over the "
    "same moment of video it came from, and the number in [brackets] after the line number is "
    "the MOST words that will fit in that moment. Go over it and the voice has to be sped up "
    "or run into the next line.\n"
    "Say the same thing in fewer words. Drop the false starts, the 'um's, the repetitions and "
    "the throat-clearing - that is where the room comes from, and it is why the English is "
    "better than the dictation, not worse. If it will not fit, cut a clause, not a fact.\n"
    "Do not merge lines, do not split them, do not add or drop any. Reply with a JSON object "
    "whose keys are exactly the line numbers you were given and whose values are the English. "
    "Nothing else."
)


def writer_rules(cfg):
    """The instructions the English is written from. Yours if you have edited
    them, mine if you have not - and Reset in Settings puts mine back."""
    own = str(cfg.get("writer_prompt") or "").strip()
    return own or TRANSLATE


def translate(segs, cfg, k):
    out = [None] * len(segs)
    terms = glossary()
    if terms:
        log("     holding %d term%s fixed from glossary.txt" % (len(terms), "" if len(terms) == 1 else "s"))
    size = max(5, int(cfg["batch"]))
    for a in range(0, len(segs), size):
        part = segs[a:a + size]
        lines = "\n".join("%d. [max %d words] %s" % (a + i + 1, budget(segs, a + i), s["said"])
                          for i, s in enumerate(part))
        want = [str(a + i + 1) for i in range(len(part))]
        got = None
        for attempt in (1, 2):
            rules = writer_rules(cfg)
            if terms:
                rules += ("\n\nThese are fixed. Wherever they are said, use exactly the right-hand "
                          "side and nothing else - they are names and terms with no translation:\n"
                          + "\n".join("  %s  ->  %s" % (a, b) for a, b in terms))
            body = json.dumps({
                "model": cfg["writer"], "temperature": 0.4,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": rules},
                             {"role": "user", "content": lines}]}).encode()
            raw = post("https://api.openai.com/v1/chat/completions", body,
                       {"Authorization": "Bearer " + k, "Content-Type": "application/json"})
            try:
                got = json.loads(json.loads(raw)["choices"][0]["message"]["content"])
            except Exception:
                got = None
            if got and all(str(w) in got for w in want):
                break
            log("     (line %d-%d came back incomplete - asking again)" % (a + 1, a + len(part)))
            got = None
        for i in range(len(part)):
            n = str(a + i + 1)
            # a line that would not come back keeps the original rather than a hole
            out[a + i] = (got or {}).get(n) or part[i]["said"]
        log("     %d of %d lines" % (min(a + size, len(segs)), len(segs)))
    for s, en in zip(segs, out):
        s["en"] = re.sub(r"\s+", " ", str(en)).strip()
    return segs


CALIBRATE = ("Alright, in this video I want to show you how this works, step by step, "
             "so you can follow along and try it yourself afterwards.")


def remember(cfg, key, value):
    """Keep a measured fact in config.json without disturbing anything else."""
    path = os.path.join(HERE, "config.json")
    try:
        have = json.load(open(path, encoding="utf-8-sig")) if os.path.exists(path) else {}
    except Exception:
        have = {}
    have[key] = value
    try:
        json.dump(have, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    except Exception:
        pass
    cfg[key] = value


def voice_rate(cfg, k, say=None):
    """How fast THIS voice actually speaks, in words a second.

    It matters which voice: a cloned voice and a ready-made one do not talk at
    the same speed, and every decision about whether a line fits is made from
    this number. Measured once per voice by saying one fixed sentence, then kept
    in config.json - so it costs a fraction of a cent the first time each voice
    is used and nothing ever again."""
    say = say or log
    who = str(cfg.get("voice", "onyx"))
    rates = dict(cfg.get("voice_rates") or {})
    if who in rates and 1.0 < float(rates[who]) < 6.0:
        return float(rates[who])
    tmp = os.path.join(tempfile.gettempdir(), "rate-%s.mp3" % re.sub(r"\W+", "_", who))
    try:
        say_once(CALIBRATE, cfg, k, tmp)      # the check needs the rate this makes
        secs = duration(tmp)
        rate = len(CALIBRATE.split()) / secs if secs > 0.5 else WORDS_PER_SECOND
    except Exception as e:
        say("     (could not time the voice: %s - assuming %.1f words a second)"
            % (str(e)[:60], WORDS_PER_SECOND))
        return WORDS_PER_SECOND
    finally:
        try: os.remove(tmp)
        except Exception: pass
    rate = round(min(4.5, max(1.5, rate)), 3)
    rates[who] = rate
    remember(cfg, "voice_rates", rates)
    say("     %s speaks at %.1f words a second" % (who, rate))
    return rate


SHORTEN = (
    "You are trimming lines of a lecture's English so each one fits the moment of video it is "
    "spoken over. You are given numbered lines, each with the MOST words it may have.\n"
    "Rewrite each one to fit, keeping the meaning, the numbers, the names and the technical "
    "terms exactly. Drop hedges, repetitions, filler and anything the picture already shows. "
    "It must still sound like a lecturer talking to a room, not a telegram.\n"
    "Never drop a fact to make room - cut a clause, not a fact.\n"
    "Reply with a JSON object whose keys are the line numbers you were given and whose values "
    "are the shortened English. Nothing else."
)


def room_for(segs, i, cfg, total=None):
    """The seconds this line really has: its own moment, plus the lateness the
    next line is allowed to absorb."""
    nxt = segs[i + 1]["start"] if i + 1 < len(segs) else (
        total if total else segs[i]["end"] + 3.0)
    return max(0.4, (nxt + float(cfg.get("max_drift", 0.75))) - segs[i]["start"])


def fit_english(segs, cfg, k, rate, total=None, say=None, rounds=2):
    """Make every line short enough to be spoken in the time it has, BEFORE any
    of it is spoken and before you are asked to approve it.

    The old order asked you to approve English that had not been measured, and
    then cut a sentence short during the run because it did not fit. Cutting is
    still there as a last resort, but it should never be reached: a line that is
    too long is rewritten shorter first, against the speed of the voice you
    actually chose."""
    say = say or log
    # the limit here is the SQUEEZE, not the ordinary speed limit: a line is only
    # rewritten when even speaking it as fast as the voice is ever allowed to go
    # would not fit. Speaking faster keeps the meaning; rewriting risks it.
    ceiling = max(float(cfg["max_tempo"]), float(cfg.get("catch_up_tempo", 1.45)),
                  float(cfg.get("squeeze_tempo", 1.60)))
    size = max(5, int(cfg.get("batch", 40)))

    def too_long(i):
        """Words over the limit for line i, or 0 if it fits."""
        allowed = int(room_for(segs, i, cfg, total) * rate * ceiling)
        segs[i]["fit"] = allowed          # what the panel shows you, per line
        return max(0, len(segs[i]["en"].split()) - allowed), allowed

    trimmed = 0
    for _ in range(max(1, rounds)):
        over = [i for i in range(len(segs)) if segs[i].get("en") and too_long(i)[0] > 0]
        if not over:
            break
        for a in range(0, len(over), size):
            part = over[a:a + size]
            lines = "\n".join("%d. [at most %d words] %s"
                              % (i + 1, too_long(i)[1], segs[i]["en"]) for i in part)
            try:
                body = json.dumps({"model": cfg["writer"], "temperature": 0.2,
                                   "response_format": {"type": "json_object"},
                                   "messages": [{"role": "system", "content": SHORTEN},
                                                {"role": "user", "content": lines}]}).encode()
                got = json.loads(json.loads(post(
                    "https://api.openai.com/v1/chat/completions", body,
                    {"Authorization": "Bearer " + k,
                     "Content-Type": "application/json"}))["choices"][0]["message"]["content"])
            except Exception as e:
                say("     (could not shorten those lines: %s)" % str(e)[:70])
                continue
            for i in part:
                new = got.get(str(i + 1))
                new = re.sub(r"\s+", " ", str(new or "")).strip()
                # only ever accept a rewrite that is actually shorter
                if new and len(new.split()) < len(segs[i]["en"].split()):
                    segs[i]["was"] = segs[i].get("was") or segs[i]["en"]
                    segs[i]["en"] = new
                    trimmed += 1

    left = [i for i in range(len(segs)) if segs[i].get("en") and too_long(i)[0] > 0]
    if trimmed:
        say("     %d line%s too long even at %d%% speed - shortened, and marked for you"
            % (trimmed, "" if trimmed == 1 else "s", round(ceiling * 100)))
    if left:
        say("     %d line%s still longer than %s can say in the time - they would be cut short"
            % (len(left), " is" if len(left) == 1 else "s are", cfg.get("voice", "the voice")))
    return segs, trimmed, left


def trim_silence(src, dest, floor="-45dB"):
    """Half of a three-word clip came back as silence - measured. Over a lecture
    that is half a minute of dead air pushing every later line out of step.
    ffmpeg has no filter for the END of a file, so the tail is trimmed by
    reversing, trimming the new head, and reversing back."""
    one = ("silenceremove=start_periods=1:start_silence=0:start_threshold=%s:detection=peak"
           % floor)
    run([tool("ffmpeg"), "-y", "-v", "error", "-i", src, "-af",
         one + ",areverse," + one + ",areverse", dest])


REVIEW_HEAD = """\
# ---------------------------------------------------------------------------
#  READ AND FIX THIS BEFORE THE VOICE IS MADE
#
#  Under each line is what you said, and under that the English that will be
#  spoken over that exact moment of the video. Change the EN: lines - only the
#  EN: lines - and save the file.
#
#  Then run  Approve.bat  (or drag the same video onto Replace.bat again).
#
#  Nothing has been spoken yet, so fixing a word here costs nothing. A name the
#  translator got wrong is worth putting in glossary.txt as well, so it is right
#  the next time too.
#
#  (max N words) is what will fit in that moment. Going over it is allowed - the
#  line is then sped up, and if it still will not fit it runs over and the
#  report says so.
# ---------------------------------------------------------------------------

"""


def write_review(segs, path):
    # utf-8-sig: the BOM is what makes every Windows editor open the Persian as
    # Persian instead of as mojibake. read_review reads utf-8-sig, so it round-trips.
    with open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(REVIEW_HEAD)
        for i, s in enumerate(segs):
            f.write("[%03d]  %s - %s   (max %d words)\n"
                    % (i + 1, clock(s["start"])[3:-4], clock(s["end"])[3:-4], budget(segs, i)))
            f.write("  FA: %s\n" % s["said"].strip())
            f.write("  EN: %s\n\n" % (s.get("en") or "").strip())


def read_review(segs, path):
    """Take the English back off the sheet. A line that is not there, or has been
    emptied, keeps what it had - deleting a line by accident should not silently
    delete that piece of the lecture."""
    if not os.path.exists(path):
        return segs, 0
    got, n, changed = {}, None, 0
    for line in open(path, encoding="utf-8-sig"):
        line = line.rstrip("\n")
        m = re.match(r"\s*\[(\d+)\]", line)
        if m:
            n = int(m.group(1)) - 1
            continue
        m = re.match(r"\s*EN:\s?(.*)$", line)
        if m and n is not None and 0 <= n < len(segs):
            got[n] = re.sub(r"\s+", " ", m.group(1)).strip()
            n = None
    for i, s in enumerate(segs):
        new = got.get(i)
        if new and new != (s.get("en") or "").strip():
            s["en"] = new
            changed += 1
    return segs, changed


VOICEDIR = os.path.join(HERE, "voice")
MINE = "mine:"       # a voice value of "mine:milad" means voice\milad.wav
_local = [None]


def cloned_voices():
    """Every recording in the voice folder is a voice you can pick."""
    if not os.path.isdir(VOICEDIR):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(VOICEDIR)
                  if f.lower().endswith(".wav") and not f.startswith("_"))


def is_clone(cfg):
    return str(cfg.get("voice", "")).lower().startswith(MINE)


def reference(cfg):
    """The recording the clone copies.

    Use a recording of the speaker in ENGLISH if there is one. The model copies
    timbre from whatever it is given, and giving it the language it has to speak
    gives it far more to work with - the difference between the two is audible.
    """
    want = str(cfg.get("voice", ""))[len(MINE):].strip()
    path = os.path.join(VOICEDIR, want + ".wav")
    if os.path.exists(path):
        return path
    left = cloned_voices()
    return os.path.join(VOICEDIR, left[0] + ".wav") if left else None


def add_voice(source, name):
    """Turn any recording - a video, an m4a, anything ffmpeg reads - into a voice
    that can be picked. Mono, trimmed of its silence, and capped: past about
    forty seconds the model gains nothing and only gets slower."""
    os.makedirs(VOICEDIR, exist_ok=True)
    safe = re.sub(r"[^\w -]+", "", name).strip() or "voice"
    dest = os.path.join(VOICEDIR, safe + ".wav")
    cut = ("silenceremove=start_periods=1:start_silence=0:start_threshold=-45dB:detection=peak")
    run([tool("ffmpeg"), "-y", "-v", "error", "-i", source, "-vn", "-ac", "1", "-ar", "22050",
         "-af", cut, "-t", "40", "-c:a", "pcm_s16le", dest])
    return safe, dest


def venv_python():
    """The model needs several gigabytes of PyTorch, which has no business inside
    an exe. It is installed beside the app instead, and driven from there."""
    for parts in (("Scripts", "python.exe"), ("bin", "python")):
        p = os.path.join(HERE, ".venv", *parts)
        if os.path.exists(p):
            return p
    return None


WORKER = r'''
import sys, os
os.environ.setdefault("COQUI_TOS_AGREED", "1")
import torch
from TTS.api import TTS

ref = sys.argv[1]
MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"

# The graphics card if it is really there. "Really" means three things, and only
# the first is about having one: the card, a CUDA build of torch (the plain
# `pip install torch` on Windows is CPU-only, which is how this was silently on
# the processor), and enough memory to hold the model.
why = ""
if not torch.cuda.is_available():
    why = ("no CUDA build of torch" if torch.version.cuda is None
           else "no card torch can reach")
    where = "cpu"
else:
    where = "cuda"

def load(dev):
    t = TTS(MODEL).to(dev)
    return t

try:
    tts = load(where)
except Exception as e:
    if where == "cuda":
        why = "the card ran out of memory" if "memory" in str(e).lower() else str(e)[:70]
        where = "cpu"
        tts = load(where)
    else:
        raise

sys.stdout.write("READY %s %s\n" % (where, why)); sys.stdout.flush()

for line in sys.stdin:                      # "<destination wav>\t<text>"
    line = line.rstrip("\n")
    if not line: continue
    dest, text = line.split("\t", 1)
    try:
        tts.tts_to_file(text=text, speaker_wav=ref, language="en", file_path=dest)
        sys.stdout.write("OK\n")
    except Exception as e:
        # a card that fills up part way through must not lose the whole lecture
        if where == "cuda" and "memory" in str(e).lower():
            try:
                torch.cuda.empty_cache()
                tts = load("cpu"); where = "cpu"
                tts.tts_to_file(text=text, speaker_wav=ref, language="en", file_path=dest)
                sys.stdout.write("OK moved to the processor - the card ran out of memory\n")
                sys.stdout.flush(); continue
            except Exception as e2:
                e = e2
        sys.stdout.write("ERR %s\n" % str(e).replace("\n", " ")[:200])
    sys.stdout.flush()
'''


def local_voice(cfg):
    """Started once and kept. Loading the model takes about fifteen seconds, and
    a process per line would pay that on every sentence of the lecture."""
    if _local[0] is None:
        py = venv_python()
        if not py:
            die("A voice of your own needs the local model installed. "
                "Open the app, go to Voice, and press Install.")
        ref = reference(cfg)
        if not ref:
            die("There is no recording to copy. Add a voice in the app first.")
        script = os.path.join(HERE, "voice_worker.py")
        open(script, "w", encoding="utf-8").write(WORKER)
        log("       starting your voice - about fifteen seconds")
        p = subprocess.Popen([py, script, ref], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                             bufsize=1, **_NOWINDOW)
        first = p.stdout.readline().strip()
        if not first.startswith("READY"):
            raise RuntimeError("the local voice would not start: %s" % (first or "no answer"))
        bits = first.split(None, 2)
        where = bits[1] if len(bits) > 1 else "cpu"
        why = bits[2] if len(bits) > 2 else ""
        if where == "cuda":
            log("       your voice is ready, on the graphics card")
        else:
            log("       your voice is ready, on the processor%s"
                % (" (%s)" % why if why else "") + " - this part is slow")
        _local[0] = p
    return _local[0]


def speak_local(text, cfg, dest):
    p = local_voice(cfg)
    wav = dest + ".wav"
    p.stdin.write("%s\t%s\n" % (wav, re.sub(r"\s+", " ", text).strip()))
    p.stdin.flush()
    answer = p.stdout.readline().strip()
    if answer.startswith("OK ") and len(answer) > 3:
        log("       %s" % answer[3:])
    if not answer.startswith("OK"):
        raise RuntimeError("your voice could not say that line: %s" % answer[:180])
    run([tool("ffmpeg"), "-y", "-v", "error", "-i", wav, "-c:a", "libmp3lame", "-b:a", "128k", dest])
    try: os.remove(wav)
    except Exception: pass


def stop_local():
    if _local[0] is not None:
        try:
            _local[0].stdin.close(); _local[0].terminate()
        except Exception:
            pass
        _local[0] = None


def say_once(text, cfg, k, dest):
    """One attempt. Whichever voice says it, the silence around it is trimmed:
    both of them pad what they produce, and untrimmed padding is a line that is
    longer than its words - which is a line that runs into the next one for no
    reason. This used to be done only for the cloned voice, which made the
    ready-made voices quietly worse at keeping time."""
    padded = dest + ".padded.mp3"
    text = as_spoken(text)
    if is_clone(cfg):
        speak_local(text, cfg, padded)
    else:
        speak_openai(text, cfg, k, padded)
    try:
        trim_silence(padded, dest)
        os.remove(padded)
    except Exception:
        os.replace(padded, dest)


def speak(text, cfg, k, dest):
    """Say it, and check that what came back is the length those words should
    take. If it is not, say it again.

    A cloned voice does not fail loudly. It rambles: a fourteen-word sentence
    came back as ten seconds of audio - five of speech and five of noise that
    sounds like wind - and everything downstream treated that as a very slow
    line and squeezed it. Nothing in the pipeline could tell, because a long
    file is not an error.

    The words themselves are the check. The voice's speed was measured before
    the run, so how long a line SHOULD take is known to within a fraction, and
    a take that is nearly twice too long has rambled while one that is far too
    short has dropped something. Both are worth another attempt, and for the
    cloned voice another attempt is free."""
    words = len(text.split())
    if words < 2:
        return say_once(text, cfg, k, dest)
    rates = cfg.get("voice_rates") or {}
    try:
        rate = float(rates.get(str(cfg.get("voice", "")), 0)) or WORDS_PER_SECOND
    except Exception:
        rate = WORDS_PER_SECOND
    want = words / rate
    asked = cfg.get("voice_retries")
    tries = 1 + int(asked if asked not in (None, "") else (2 if is_clone(cfg) else 1))
    low = float(cfg.get("shortest_take", 0.60))
    high = float(cfg.get("longest_take", 1.65))

    keep, kept_off = None, None
    for attempt in range(1, tries + 1):
        say_once(text, cfg, k, dest)
        off = duration(dest) / want if want > 0 else 1.0
        if low <= off <= high:
            if attempt > 1:
                log("       (line said again, attempt %d, and it came back right)" % attempt)
            if keep and os.path.exists(keep):
                os.remove(keep)
            return
        if kept_off is None or abs(off - 1.0) < abs(kept_off - 1.0):
            keep = dest + ".best.mp3"
            shutil.copyfile(dest, keep)
            kept_off = off
        if attempt < tries:
            log("       line %s than its words - saying it again"
                % ("nearly %.1f times longer" % off if off > high else "far shorter"))
    # nothing came back right: use whichever attempt was closest
    if keep and os.path.exists(keep):
        os.replace(keep, dest)
    log("       (kept the closest of %d attempts, %.0f%% of the expected length)"
        % (tries, (kept_off or 1.0) * 100))


def speak_openai(text, cfg, k, dest):
    body = json.dumps({
        "model": cfg["speaker"], "voice": cfg["voice"], "input": text,
        "response_format": "mp3",
        "instructions": "An American man teaching a university class: warm, clear and "
                        "unhurried, explaining rather than announcing. Natural emphasis on "
                        "the words that carry the point. Never sound like a newsreader."}).encode()
    raw = post("https://api.openai.com/v1/audio/speech", body,
               {"Authorization": "Bearer " + k, "Content-Type": "application/json"})
    padded = dest + ".padded.mp3"
    open(padded, "wb").write(raw)
    try:
        trim_silence(padded, dest)
        os.remove(padded)
    except Exception:
        os.replace(padded, dest)      # trimming is an improvement, never a gate


# ----------------------------------------------------------------- fitting
def fade_tail(pcm, rate, ms=45):
    """Cutting raw samples mid-word leaves a click. This takes the last few
    milliseconds down to nothing so a truncated line simply stops."""
    n = min(int(rate * ms / 1000.0), len(pcm) // 2)
    if n <= 0:
        return pcm
    a = array.array("h")
    a.frombytes(pcm[len(pcm) - n * 2:])
    for j in range(n):
        a[j] = int(a[j] * (1.0 - (j + 1) / float(n)))
    return pcm[:len(pcm) - n * 2] + a.tobytes()


def build_track(segs, cfg, folder, total, k):
    """Lay every spoken line onto one silent track at the moment it belongs to.

    Written straight into a raw PCM file by byte offset rather than mixed with a
    filter graph: with several hundred lines an amix of that many inputs is slow
    and imprecise, and this is exact by construction.
    """
    rate = int(cfg["sample_rate"])
    raw_path = os.path.join(folder, "track.raw")
    frames = int(total * rate) + rate            # a second of headroom at the end
    with open(raw_path, "wb") as f:
        f.truncate(frames * 2)                   # silence, as zeros

    # How far behind its own moment a line may ever be. Lateness used to be
    # allowed to accumulate: one sentence whose English did not fit put the next
    # fifteen lines up to 6.6 seconds behind the picture, and it took 45 seconds
    # of video to recover. Measured, not guessed. Now a line is never more than
    # this late, and the cost of an over-long sentence is paid by that sentence
    # alone instead of by everything after it.
    drift_cap = float(cfg.get("max_drift", 0.75))
    catch_up = max(float(cfg["max_tempo"]), float(cfg.get("catch_up_tempo", 1.45)))
    squeeze = max(catch_up, float(cfg.get("squeeze_tempo", 1.60)))

    report, cursor = [], 0.0
    with open(raw_path, "r+b") as f:
        for i, s in enumerate(segs):
            if not s["en"]:
                continue
            mp3 = os.path.join(folder, "say%04d.mp3" % i)
            if not os.path.exists(mp3):
                speak(s["en"], cfg, k, mp3)
            pcm = decode_pcm(mp3, rate)
            natural = len(pcm) / 2.0 / rate

            # where it may start: after the line before it, but never further
            # behind its own moment than the cap allows
            start = min(max(s["start"], cursor), s["start"] + drift_cap)
            late = start - s["start"]
            nxt = segs[i + 1]["start"] if i + 1 < len(segs) else total
            room = max(0.25, nxt - start)
            allowed = (nxt + drift_cap) - start     # past this the next line suffers

            # ONE decision about speed, in order of preference. Speaking faster
            # keeps every word; cutting does not - so speed is tried first, and
            # harder, before anything is ever thrown away.
            tempo = 1.0
            if natural > room:
                # while behind, it may hurry harder than usual: that is what pays
                # the lateness back instead of passing it on
                tempo = min(natural / room, catch_up if late > 0.05
                            else float(cfg["max_tempo"]))
            elif late <= 0.05 and natural < room * 0.55 and natural > 0.6:
                # far too short for its slot: slow it very slightly rather than
                # leaving a hole, but never below the floor. Not while behind -
                # stretching a line when you are late is how you stay late.
                tempo = max(float(cfg["min_tempo"]), natural / (room * 0.8))
            if natural / tempo > allowed + 0.02 and i + 1 < len(segs):
                # it would otherwise have to be cut. Hurry as much as the squeeze
                # limit permits first - a fast whole sentence beats half a slow one
                tempo = min(squeeze, natural / allowed)

            if abs(tempo - 1.0) > 0.01:
                pcm = decode_pcm(mp3, rate, tempo)
            want = len(pcm) / 2.0 / rate

            # and only if even that is not enough does anything get thrown away.
            # Cut with a short fade rather than a click, and say so.
            cut = False
            if want > allowed + 0.02 and i + 1 < len(segs):
                pcm = fade_tail(pcm[:int(allowed * rate) * 2], rate)
                want = len(pcm) / 2.0 / rate
                cut = True

            # Two different things can be wrong, and blaming them the same way
            # turned one bad line into twenty-three. `late` is how far behind the
            # earlier lines have pushed this one; `own` is whether the line is
            # simply too long for the moment it belongs to. Only the second is
            # something to go and fix.
            own = max(0.25, nxt - s["start"])
            if cut:
                report.append((i, s["start"], "too long for its %.1fs and cut short to keep "
                               "the rest in step" % own, True))
            elif want > own + 0.05 and tempo >= squeeze - 0.01:
                report.append((i, s["start"], "at %.0f%% and still longer than its %.1fs"
                               % (tempo * 100, own), True))
            elif late > 0.05:
                # only worth saying when it is actually late. It used to report
                # "pushed 0.0s late", which is not a fact about anything.
                report.append((i, s["start"], "pushed %.1fs late by the lines before it" % late,
                               False))
            elif tempo > 1.02:
                report.append((i, s["start"], "sped up to %.0f%% to fit" % (tempo * 100), False))
            elif tempo < 0.98:
                report.append((i, s["start"], "slowed to %.0f%% to fill its moment"
                               % (tempo * 100), False))

            at = int(start * rate) * 2
            if at + len(pcm) > frames * 2:
                pcm = pcm[:max(0, frames * 2 - at)]
            f.seek(at)
            f.write(pcm)
            cursor = start + len(pcm) / 2.0 / rate
            if (i + 1) % 10 == 0 or i + 1 == len(segs):
                log("     %d of %d lines spoken" % (i + 1, len(segs)))

    track = os.path.join(folder, "track.m4a")
    run([tool("ffmpeg"), "-y", "-v", "error", "-f", "s16le", "-ar", str(rate), "-ac", "1",
         "-i", raw_path, "-c:a", "aac", "-b:a", "128k", track])
    return track, report


# ----------------------------------------------------------------- output
def clock(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def srt(segs, field, path):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        n = 0
        for s in segs:
            text = (s.get(field) or "").strip()
            if not text:
                continue
            n += 1
            f.write("%d\n%s --> %s\n%s\n\n" % (n, clock(s["start"]), clock(s["end"]), text))
    return n


def mux(video, track, dest):
    """The picture is copied, not re-encoded. This is why a 500MB file takes
    seconds here and why nothing about the video quality changes."""
    run([tool("ffmpeg"), "-y", "-v", "error", "-i", video, "-i", track,
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
         "-shortest", "-movflags", "+faststart", dest])


def clear_work(keep=False):
    """Everything in work\\ is a piece of somebody's lecture. It exists only
    while a run is going; when the app closes it should not still be there."""
    if keep or not os.path.isdir(WORK):
        return 0
    gone = 0
    for name in os.listdir(WORK):
        path = os.path.join(WORK, name)
        try:
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
            gone += 1
        except Exception:
            pass
    return gone


# ------------------------------------------------------- the YouTube transcript
# YouTube's own machine writes better Persian than anything reachable through an
# API, which is the whole reason this exists. What it will NOT do is transcribe a
# file you hand it: the transcript belongs to a video on your channel, so the
# video has to be on your channel first, and you have to put it there yourself.
#
# Not the app. A video uploaded through an API project Google has not audited is
# locked private by YouTube and that cannot be appealed - so the app never
# uploads anything. You upload it unlisted, paste the link, and it fetches the
# words. Nothing is uploaded from here and nothing is deleted from your channel.
YT_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
YT_API = "https://www.googleapis.com/youtube/v3"
YT_SECRET = os.path.join(HERE, "client_secret.json")
YT_TOKEN = os.path.join(HERE, "youtube_token.json")


def yt_client():
    """The desktop client you downloaded from the Google console, or None."""
    if not os.path.exists(YT_SECRET):
        return None
    try:
        d = json.load(open(YT_SECRET, encoding="utf-8-sig"))
        return d.get("installed") or d.get("web")
    except Exception:
        return None


def yt_ready():
    """(has the client file, is signed in) - what the Settings tab shows."""
    return bool(yt_client()), os.path.exists(YT_TOKEN)


def yt_video_id(text):
    """Whatever was pasted, as the eleven characters that name the video."""
    text = (text or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    m = re.search(r"(?:v=|/shorts/|youtu\.be/|/embed/|/live/)([A-Za-z0-9_-]{11})", text)
    return m.group(1) if m else None


def _yt_form(url, fields):
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode("utf-8", "replace")[:300])


def yt_sign_in(say=None):
    """Once, in a browser. Google sends the answer back to a one-shot server on
    this machine, so there is nothing to copy or paste by hand."""
    import http.server, threading, webbrowser
    app = yt_client()
    if not app:
        raise RuntimeError("client_secret.json is missing. Settings -> YouTube -> "
                           "Choose the file you downloaded from Google.")
    say = say or log
    caught = {}

    class Catch(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            caught.update(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            page = ("<body style='font:16px system-ui;padding:60px;color:#111'>"
                    "<h2>Done.</h2><p>Close this tab and go back to the app.</p>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Catch)
    redirect = "http://localhost:%d/" % server.server_port
    verifier = base64.urlsafe_b64encode(os.urandom(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = app["auth_uri"] + "?" + urllib.parse.urlencode({
        "client_id": app["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": YT_SCOPE, "access_type": "offline", "prompt": "consent",
        "code_challenge": challenge, "code_challenge_method": "S256"})

    say("  A browser is opening. Sign in with the account that owns the channel.")
    threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    server.timeout = 300
    server.handle_request()
    server.server_close()
    if "code" not in caught:
        raise RuntimeError("Sign-in did not finish: %s"
                           % (caught.get("error") or "the window was closed"))

    tok = _yt_form(app["token_uri"], {
        "code": caught["code"], "client_id": app["client_id"],
        "client_secret": app["client_secret"], "redirect_uri": redirect,
        "grant_type": "authorization_code", "code_verifier": verifier})
    json.dump(tok, open(YT_TOKEN, "w"), indent=2)
    say("  Signed in to YouTube.")
    return tok["access_token"]


def yt_access():
    """A usable token, or None if it has to be signed in again. A refresh token
    only dies on you while the app is left on Testing in the Google console -
    publish it and it keeps working."""
    app = yt_client()
    if not app or not os.path.exists(YT_TOKEN):
        return None
    try:
        saved = json.load(open(YT_TOKEN, encoding="utf-8"))
        fresh = _yt_form(app["token_uri"], {
            "refresh_token": saved["refresh_token"], "client_id": app["client_id"],
            "client_secret": app["client_secret"], "grant_type": "refresh_token"})
        saved.update(fresh)
        json.dump(saved, open(YT_TOKEN, "w"), indent=2)
        return saved["access_token"]
    except Exception:
        return None


def yt_get(url, tok):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _why(body):
    try:
        return json.loads(body)["error"]["message"]
    except Exception:
        return body.decode("utf-8", "replace")[:200]


def parse_srt(text):
    """SRT back into the same shape everything else here speaks: start, end and
    the words. YouTube writes one cue per breath, which is exactly what merge()
    expects to be handed."""
    def secs(t):
        h, m, rest = t.split(":")
        s, ms = rest.replace(".", ",").split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    out = []
    for block in re.split(r"\r?\n\r?\n+", text.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        if lines[0].strip().isdigit():
            lines = lines[1:]
        m = re.match(r"\s*([\d:,.]+)\s*-->\s*([\d:,.]+)", lines[0] if lines else "")
        if not m:
            continue
        said = re.sub(r"<[^>]+>", "", " ".join(lines[1:])).strip()
        said = re.sub(r"\s+", " ", said)
        if said:
            out.append({"start": secs(m.group(1)), "end": secs(m.group(2)), "said": said})
    out.sort(key=lambda s: s["start"])
    # YouTube writes ROLLING captions: every cue's display window overlaps the
    # next by several seconds so the text stays on screen. The words in each cue
    # are new, but the end time is when it stops being SHOWN, not when he stopped
    # speaking. Left as they are, every gap between lines is negative and nothing
    # downstream that reasons about pauses can work.
    for i in range(len(out) - 1):
        out[i]["end"] = min(out[i]["end"], out[i + 1]["start"])
    return out


def word_times(cues):
    """Every word with a time, by spreading each cue's words evenly across the
    span it covers. Cue-level timing is all YouTube gives; within a cue this is
    an interpolation, and it is out by at most a word - which is a great deal
    closer than the alternative of pretending the cue boundaries mean anything."""
    out = []
    for c in cues:
        ws = c["said"].split()
        if not ws:
            continue
        span = max(0.05, c["end"] - c["start"])
        for n, w in enumerate(ws):
            out.append((c["start"] + span * n / float(len(ws)), w))
    return out


def resplit(cues, marks, longest=14.0, least=0.45, near=None):
    """Cut the words into lines where he actually stopped talking.

    MEASURED, and it is the whole reason this function exists in this shape: of
    36 caption boundaries in a real lecture, **35 were more than a third of a
    second from any real pause**. YouTube cuts its cues by how much text fits on
    screen. They are not sentence ends, they are not pauses, and choosing among
    them - however cleverly - cannot produce a break in the right place. Two
    versions of this function tried and both failed, which is what "name, and it
    creates it for me" and "for you, and you can adjust" were: the tail of one
    sentence and the head of the next, each spoken as its own utterance.

    So the cue boundaries are thrown away. The words are laid on a timeline and
    cut at the pauses in his own recording; a line then begins and ends where he
    began and ended, and a line that stops mid-thought stops where he did.

    `marks` may be plain times or (time, length) pairs; with lengths, only a
    pause of at least `least` counts, because a hesitation is not a full stop.
    """
    words = word_times(cues)
    if not words:
        return []
    pauses = sorted(m if isinstance(m, (int, float)) else m[0]
                    for m in marks
                    if isinstance(m, (int, float)) or m[1] >= least)
    times = [t for t, _ in words]

    cut = set()
    for p in pauses:
        # the first word that starts after the pause begins
        lo, hi = 0, len(times)
        while lo < hi:
            mid = (lo + hi) // 2
            if times[mid] < p:
                lo = mid + 1
            else:
                hi = mid
        if 0 < lo < len(words):
            cut.add(lo)

    last = cues[-1]["end"] if cues else 0.0
    lines, held, began = [], [], 0
    for n, (t, w) in enumerate(words):
        if held and n in cut and t - times[began] >= 0.8:
            lines.append((times[began], t, " ".join(held)))
            held, began = [], n
        elif held and t - times[began] > longest:
            lines.append((times[began], t, " ".join(held)))
            held, began = [], n
        held.append(w)
    if held:
        lines.append((times[began], last, " ".join(held)))
    return [{"start": a, "end": b, "said": txt} for a, b, txt in lines]


def yt_upload(path, tok, say=None, chunk=8 << 20):
    """Put the lecture on your own channel, unlisted, so YouTube will transcribe
    it. Resumable and chunked, because a lecture can be half a gigabyte and a
    single POST that dies at 90% is a wasted half hour.

    Nothing about this is permanent: the caller deletes the video again the
    moment it has the words."""
    say = say or log
    total = os.path.getsize(path)
    meta = json.dumps({
        "snippet": {"title": os.path.splitext(os.path.basename(path))[0][:100],
                    "description": "Uploaded by Course Video Replacer to read back its own "
                                   "captions. Deleted automatically once they are read.",
                    "categoryId": "27"},                      # Education
        "status": {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False}
    }).encode()

    req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos"
        "?uploadType=resumable&part=snippet,status",
        data=meta, method="POST",
        headers={"Authorization": "Bearer " + tok,
                 "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Length": str(total),
                 "X-Upload-Content-Type": "video/*"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            where = r.headers.get("Location")
    except urllib.error.HTTPError as e:
        raise RuntimeError("YouTube would not start the upload (%d): %s"
                           % (e.code, _why(e.read())))
    if not where:
        raise RuntimeError("YouTube did not say where to send the video.")

    say("       uploading %.0f MB, unlisted" % (total / 1e6))
    sent, began, said = 0, time.time(), -1
    with open(path, "rb") as fh:
        while sent < total:
            piece = fh.read(chunk)
            if not piece:
                break
            end = sent + len(piece) - 1
            put = urllib.request.Request(where, data=piece, method="PUT", headers={
                "Content-Length": str(len(piece)),
                "Content-Range": "bytes %d-%d/%d" % (sent, end, total)})
            try:
                with urllib.request.urlopen(put, timeout=600) as r:
                    done = json.loads(r.read() or b"{}")
                    if done.get("id"):
                        say("       uploaded in %.0f seconds" % (time.time() - began))
                        return done["id"]
            except urllib.error.HTTPError as e:
                if e.code != 308:              # 308 = keep going, this is normal
                    raise RuntimeError("The upload failed at %.0f%% (%d): %s"
                                       % (100.0 * sent / total, e.code, _why(e.read())))
            sent = end + 1
            pct = int(100.0 * sent / total)
            if pct // 10 > said // 10:         # a line every tenth, not every chunk
                said = pct
                say("         %d%%" % pct)
    raise RuntimeError("The upload finished but YouTube never returned a video id.")


def yt_delete_video(vid, tok, say=None):
    """It was only ever there to be transcribed."""
    say = say or log
    req = urllib.request.Request("%s/videos?id=%s" % (YT_API, vid), method="DELETE",
                                 headers={"Authorization": "Bearer " + tok})
    try:
        urllib.request.urlopen(req, timeout=60).read()
        say("       deleted it from your channel")
        return True
    except Exception as e:
        say("       COULD NOT DELETE the upload (%s). It is unlisted on your channel as "
            "video %s - remove it yourself." % (str(e)[:120], vid))
        return False


def yt_tracks(vid, tok):
    status, body = yt_get("%s/captions?part=snippet&videoId=%s" % (YT_API, vid), tok)
    if status != 200:
        raise RuntimeError("YouTube would not list the captions (%d): %s" % (status, _why(body)))
    return json.loads(body).get("items") or []


def yt_wait(vid, tok, minutes, say=None):
    """YouTube writes the captions when it gets round to it. Usually a couple of
    minutes; sometimes not. Waiting is the only thing to be done, so it waits out
    loud rather than looking hung."""
    say = say or log
    deadline = time.time() + minutes * 60
    while True:
        tracks = yt_tracks(vid, tok)
        if tracks:
            return tracks
        if time.time() > deadline:
            raise RuntimeError("YouTube had not written any captions after %d minutes."
                               % minutes)
        say("       waiting for YouTube to write the captions...")
        time.sleep(20)


def yt_fetch(tracks, tok, say=None):
    """The best track we are allowed to have, as lines with timings."""
    say = say or log
    tracks = sorted(tracks, key=lambda t: 0 if t["snippet"].get("trackKind") != "ASR" else 1)
    last = "no tracks"
    for t in tracks:
        sn = t["snippet"]
        # Report what YouTube said, not what it probably meant. "ASR" is its own
        # automatic transcript; "standard" is a published caption track, which
        # on your own upload is usually still YouTube's work rather than yours.
        made = "track kind %s" % (sn.get("trackKind") or "?")
        status, body = yt_get("%s/captions/%s?tfmt=srt" % (YT_API, t["id"]), tok)
        if status == 200 and body.strip():
            segs = parse_srt(body.decode("utf-8", "replace"))
            if segs:
                say("       %s, %s: %d lines" % (sn.get("language") or "?", made, len(segs)))
                return segs
            last = "the track came back empty"
        else:
            last = _why(body)
            say("       %s (%s) refused: %s" % (sn.get("language") or "?", made, last))
    raise RuntimeError("YouTube would not hand over any of its caption tracks. %s" % last)


def yt_transcript(video, cfg=None, say=None):
    """Upload, wait, read the words, delete. You do nothing and nothing is left
    behind - if the deletion itself fails, that is said out loud with the video
    id, because a lecture quietly left on a channel is the one outcome that must
    never happen silently."""
    cfg = cfg or {}
    say = say or log
    tok = yt_access()
    if not tok:
        raise RuntimeError("Not signed in to YouTube. Settings -> Your YouTube sign-in -> Sign in.")
    vid = yt_upload(video, tok, say)
    try:
        tracks = yt_wait(vid, tok, int(cfg.get("youtube_wait_minutes", 20)), say)
        return yt_fetch(tracks, tok, say)
    finally:
        if cfg.get("youtube_delete", True):
            yt_delete_video(vid, tok, say)


def convert(video, cfg=None, say=None, ask=None, out_dir=None):
    """The whole pipeline, once.

    `say` is where the progress lines go - the console, or a window.
    `ask` is your look at the English before anything is spoken. It is handed the
    lines and gives back the ones to speak, or None to stop. The console version
    writes a file and waits for Approve; the window version opens a panel. The
    pipeline does not know or care which.
    """
    global log, OUT
    if say: log = say
    if out_dir: OUT = out_dir
    cfg = cfg or config()
    k = key()
    name = os.path.splitext(os.path.basename(video))[0]
    folder = os.path.join(WORK, re.sub(r"[^\w.-]+", "_", name))
    os.makedirs(folder, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    began = time.time()

    log("\n  %s" % os.path.basename(video))
    total = duration(video)
    log("  %.0f minutes, %.0f MB\n" % (total / 60, os.path.getsize(video) / 1e6))

    audio = os.path.join(folder, "voice.mp3")
    segs_path = os.path.join(folder, "heard.json")
    from_youtube = str(cfg.get("transcript_from", "here")).strip().lower() == "youtube"

    def sound():
        """The audio, made only if something here actually has to listen to it.
        When YouTube supplies the words, nothing needs to."""
        log("  1/6  taking the sound out (the video itself is never uploaded)")
        if not os.path.exists(audio):
            extract_audio(video, audio)
        log("       %.1f MB of audio\n" % (os.path.getsize(audio) / 1e6))

    if not from_youtube and not os.path.exists(segs_path):
        sound()

    log("  2/6  writing down what you said")
    if os.path.exists(segs_path):
        segs = json.load(open(segs_path, encoding="utf-8"))
        log("       (using what was already transcribed)")
    else:
        segs, rolling = [], False
        if from_youtube:
            # Its Persian is better than anything reachable through an API, so it
            # is worth asking. If it says no, that is a fact to state out loud
            # and carry on from, not a reason to stop the run.
            log("       putting it on your channel so YouTube can transcribe it")
            try:
                segs = yt_transcript(video, cfg, log)
                rolling = bool(segs)
            except Exception as e:
                log("       YouTube could not: %s" % e)
                log("       so it is being transcribed here instead.")
        if not segs:
            sound()
            pts = cut_points(audio, total, cfg["chunk_minutes"])
            segs = transcribe(slice_audio(audio, pts, folder), cfg, k)
        raw_count = len(segs)
        if rolling:
            # Captions are cut to fit a screen, not to end a sentence. The
            # recording knows where he stopped talking; the captions do not.
            sound()
            marks = silences(audio, "-30dB", 0.35)
            segs = resplit(segs, marks, float(cfg.get("youtube_longest", 14.0)))
            log("       (the caption boundaries are thrown away - see the guide)")
            log("     %d captions rejoined into %d lines, cut at %d real pauses"
                % (raw_count, len(segs), len(marks)))
        else:
            segs = merge(segs, float(cfg.get("longest_line", 10.0)),
                         float(cfg.get("join_gap", 0.8)))
            log("     %d fragments joined into %d sentences" % (raw_count, len(segs)))
        if cfg.get("proofread", True):
            segs, fixed = proofread(segs, cfg, k)
            log("     %d line%s tidied up" % (fixed, "" if fixed == 1 else "s"))
        json.dump(segs, open(segs_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not segs:
        die("Nothing was heard in that recording.")
    log("       %d lines\n" % len(segs))

    log("  3/6  turning it into English")
    en_path = os.path.join(folder, "english.json")
    if os.path.exists(en_path):
        segs = json.load(open(en_path, encoding="utf-8"))
        log("       (using the English already written)")
    else:
        segs = translate(segs, cfg, k)
        # Measured against the voice you actually chose, and shortened where it
        # will not fit - before you are asked to approve it, and before a word
        # of it is spoken. Approving English that has not been measured is how a
        # sentence ends up cut short halfway through the run.
        segs, _, _ = fit_english(segs, cfg, k, voice_rate(cfg, k, log), total, log)
        json.dump(segs, open(en_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("       %s\n" % (segs[0].get("en", "")[:70]))

    # ---- your turn, before anything is spoken ----------------------------
    # The voice is the expensive step and the one that cannot be un-said. A
    # name the translator got wrong is free to fix here and costs a whole run
    # to fix afterwards, so this is where it stops and waits.
    if ask is not None:
        segs = ask(segs)
        if segs is None:
            # Walking away at the review panel is a decision, not a pause. What
            # is left behind is a half-done transcript of a private lecture, so
            # unless you asked to keep it, it goes.
            if not cfg.get("keep_work"):
                shutil.rmtree(folder, ignore_errors=True)
            log("  stopped before anything was spoken. Nothing was left behind.")
            return None
        json.dump(segs, open(en_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    review = os.path.join(OUT, name + ".review.txt")
    if ask is None and cfg.get("review", True):
        # A sheet on disk is your answer, whether you came back through
        # Approve.bat or just ran it again. Only when there is no sheet at all
        # does it write one and wait - and --go is how you say "do not bother".
        if os.path.exists(review):
            segs, changed = read_review(segs, review)
            json.dump(segs, open(en_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            log("  approved%s\n" % (" with %d line%s of your own" % (changed, "" if changed == 1 else "s")
                                     if changed else " unchanged"))
        elif "--go" not in sys.argv:
            write_review(segs, review)
            log("  READ IT FIRST")
            log("       %s" % review)
            log("")
            log("       Every line you said, with the English that will be spoken over it.")
            log("       Fix any EN: line, save, then run Approve.bat.")
            log("       Nothing has been spoken yet, so nothing has been spent on the voice.\n")
            try:
                os.startfile(review)          # opens it in Notepad, on Windows
            except Exception:
                pass
            return None

    log("  4/6  speaking it, and fitting it to your picture")
    track, report = build_track(segs, cfg, folder, total, k)
    log("")

    log("  5/6  putting it back on the video (the picture is copied, not re-encoded)")
    out_mp4 = os.path.join(OUT, name + ".en.mp4")
    mux(video, track, out_mp4)

    log("  6/6  writing the subtitles")
    fa = os.path.join(OUT, name + ".original.srt")
    en = os.path.join(OUT, name + ".english.srt")
    srt(segs, "said", fa)
    srt(segs, "en", en)

    rep = os.path.join(OUT, name + ".report.txt")
    with open(rep, "w", encoding="utf-8", newline="\n") as f:
        f.write("%s\n%d lines, %.0f minutes\n\n" % (os.path.basename(video), len(segs), total / 60))
        tight = [r for r in report if r[3]]
        f.write("Lines whose English is too long for their moment: %d\n" % len(tight))
        f.write("Lines merely pushed along, or sped up a little:    %d\n\n"
                % (len(report) - len(tight)))
        if tight:
            f.write("Shorten these and run it again if they matter:\n")
            for i, at, why, _ in tight:
                f.write("  %s  line %d  %s\n     %s\n" % (clock(at), i + 1, why, segs[i]["en"][:110]))
            f.write("\n")
        for i, at, why, bad in report:
            if not bad:
                f.write("  %s  line %d  %s\n" % (clock(at), i + 1, why))

    if not cfg.get("keep_work"):
        shutil.rmtree(folder, ignore_errors=True)
    try:
        os.remove(review)                 # it has been used; the srt files replace it
    except Exception:
        pass

    tight = len([r for r in report if r[3]])
    log("\n  Done in %.0f minutes.\n" % ((time.time() - began) / 60))
    log("   %s" % out_mp4)
    log("   %s" % fa)
    log("   %s" % en)
    log("   %s%s" % (rep, "   <- %d lines did not fit, have a look" % tight if tight else ""))
    log("")


def main():
    """The console way in: a video on the command line, and the review sheet as a
    file you edit in Notepad. The window app calls run() directly instead."""
    if len(sys.argv) < 2:
        die("Drag an .mp4 onto Replace.bat, or run:  python replacer.py \"your video.mp4\"")
    video = os.path.abspath(sys.argv[1])
    if not os.path.exists(video):
        die("There is no file at %s" % video)
    convert(video)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        die("stopped by you")
    except Exception as e:
        die(str(e))
