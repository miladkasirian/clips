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
import base64, json, os, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
OUT  = os.path.join(HERE, "output")

DEFAULTS = {
    "transcribe":  "whisper-1",      # the ONLY model that returns timestamps
    "writer":      "gpt-4o",         # Persian/English -> natural American English
    "speaker":     "gpt-4o-mini-tts",
    "voice":       "onyx",
    "max_tempo":   1.20,             # 1.0 = never speed up. Past ~1.3 it is audible
    "min_tempo":   0.90,             # slowing a short line down, gently
    "longest_line": 10.0,            # fragments are joined into sentences up to this long
    "join_gap":     0.8,             # ...as long as the pause between them is under this
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
                       stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
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


def silences(path, floor="-32dB", least=0.45):
    """Where it goes quiet, so a chunk boundary never lands mid-sentence."""
    p = subprocess.run([tool("ffmpeg"), "-v", "info", "-i", path, "-af",
                        "silencedetect=noise=%s:d=%s" % (floor, least), "-f", "null", "-"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                       text=True, encoding="utf-8", errors="replace")
    marks = []
    for m in re.finditer(r"silence_start:\s*([\d.]+)", p.stderr or ""):
        marks.append(float(m.group(1)))
    return marks


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
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError("could not decode %s:\n%s" % (path, p.stderr.decode("utf-8", "replace")[-400:]))
    return p.stdout


# ----------------------------------------------------------------- the work
def transcribe(chunks, cfg, k):
    """Segments with real timestamps, on the clock of the whole lecture."""
    segs = []
    for i, (path, offset) in enumerate(chunks, 1):
        size = os.path.getsize(path) / 1e6
        log("     piece %d of %d  (%.1f MB)" % (i, len(chunks), size))
        body, ctype = multipart(
            {"model": cfg["transcribe"], "response_format": "verbose_json",
             "timestamp_granularities": ["segment"]},
            os.path.basename(path), open(path, "rb").read())
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


def budget(segs, i, cps=WORDS_PER_SECOND):
    """How many words this line has room for, from the gap to the next one."""
    nxt = segs[i + 1]["start"] if i + 1 < len(segs) else segs[i]["end"] + 3.0
    return max(3, int((nxt - segs[i]["start"]) * cps))


TRANSLATE = (
    "You are turning a university lecturer's own recording into the English he would have "
    "spoken himself. The input may be Persian or English, and it is speech, so it rambles, "
    "repeats and restarts.\n"
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
            rules = TRANSLATE
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


def local_voice(cfg):
    """Loaded once - it takes about fifteen seconds and would otherwise be paid
    for on every single line."""
    if _local[0] is None:
        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        try:
            import torch
            from TTS.api import TTS
        except ImportError:
            die("Your own voice needs the local model. Run Setup-voice.bat once.")
        where = "cuda" if torch.cuda.is_available() else "cpu"
        log("       loading your voice (%s)%s"
            % (where, "" if where == "cuda" else " - the processor, so this is slow"))
        _local[0] = TTS(cfg.get("clone_model", "tts_models/multilingual/multi-dataset/xtts_v2")).to(where)
    return _local[0]


def speak_local(text, cfg, dest):
    ref = reference(cfg)
    if not ref:
        die("There is no recording in voice\\ to copy. Add one in the app first.")
    wav = dest + ".wav"
    local_voice(cfg).tts_to_file(text=text, speaker_wav=ref, language="en", file_path=wav)
    run([tool("ffmpeg"), "-y", "-v", "error", "-i", wav, "-c:a", "libmp3lame", "-b:a", "128k", dest])
    try: os.remove(wav)
    except Exception: pass


def speak(text, cfg, k, dest):
    if is_clone(cfg):
        padded = dest + ".padded.mp3"
        speak_local(text, cfg, padded)
        try:
            trim_silence(padded, dest); os.remove(padded)
        except Exception:
            os.replace(padded, dest)
        return
    return speak_openai(text, cfg, k, dest)


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

    report, cursor = [], 0.0
    with open(raw_path, "r+b") as f:
        for i, s in enumerate(segs):
            if not s["en"]:
                continue
            mp3 = os.path.join(folder, "say%04d.mp3" % i)
            if not os.path.exists(mp3):
                speak(s["en"], cfg, k, mp3)
            pcm = decode_pcm(mp3, rate)
            want = len(pcm) / 2.0 / rate

            # where it may start, and how much room there is before the next line
            start = max(s["start"], cursor)
            nxt = segs[i + 1]["start"] if i + 1 < len(segs) else total
            room = max(0.25, nxt - start)

            tempo = 1.0
            if want > room:
                tempo = min(want / room, float(cfg["max_tempo"]))
            elif want < room * 0.55 and want > 0.6:
                # far too short for its slot: slow it very slightly rather than
                # leaving a hole, but never below the floor
                tempo = max(float(cfg["min_tempo"]), want / (room * 0.8))
            if abs(tempo - 1.0) > 0.01:
                pcm = decode_pcm(mp3, rate, tempo)
                want = len(pcm) / 2.0 / rate

            # Two different things can be wrong, and blaming them the same way
            # turned one bad line into twenty-three. `late` is how far behind the
            # earlier lines have pushed this one; `own` is whether the line is
            # simply too long for the moment it belongs to. Only the second is
            # something to go and fix.
            late = start - s["start"]
            own = max(0.25, nxt - s["start"])
            over = want - room
            if want > own * float(cfg["max_tempo"]) + 0.05:
                report.append((i, s["start"], "too long for its %.1fs: needs %.1fs of speech"
                               % (own, want), True))
            elif over > 0.05:
                report.append((i, s["start"], "pushed %.1fs late by the lines before it" % late, False))
            elif tempo > 1.02:
                report.append((i, s["start"], "sped up to %.0f%% to fit" % (tempo * 100), False))

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

    log("  1/6  taking the sound out (the video itself is never uploaded)")
    audio = os.path.join(folder, "voice.mp3")
    if not os.path.exists(audio):
        extract_audio(video, audio)
    log("       %.1f MB of audio\n" % (os.path.getsize(audio) / 1e6))

    log("  2/6  writing down what you said")
    segs_path = os.path.join(folder, "heard.json")
    if os.path.exists(segs_path):
        segs = json.load(open(segs_path, encoding="utf-8"))
        log("       (using what was already transcribed)")
    else:
        pts = cut_points(audio, total, cfg["chunk_minutes"])
        segs = transcribe(slice_audio(audio, pts, folder), cfg, k)
        raw_count = len(segs)
        segs = merge(segs, float(cfg.get("longest_line", 10.0)), float(cfg.get("join_gap", 0.8)))
        log("     %d fragments joined into %d sentences" % (raw_count, len(segs)))
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
        json.dump(segs, open(en_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("       %s\n" % (segs[0].get("en", "")[:70]))

    # ---- your turn, before anything is spoken ----------------------------
    # The voice is the expensive step and the one that cannot be un-said. A
    # name the translator got wrong is free to fix here and costs a whole run
    # to fix afterwards, so this is where it stops and waits.
    if ask is not None:
        segs = ask(segs)
        if segs is None:
            log("  stopped before anything was spoken.")
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
