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
    "chunk_minutes": 12,             # transcription is sent in pieces this long
    "batch":       40,               # segments per translation request
    "sample_rate": 24000,            # what the speech endpoint returns
    "keep_work":   False,
}


# ----------------------------------------------------------------- plumbing
def log(msg):
    print(msg, flush=True)


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


TRANSLATE = (
    "You are turning a university lecturer's own recording into the English he would have "
    "spoken himself. The input may be Persian or English, and it is speech, so it rambles, "
    "repeats and restarts.\n"
    "Rewrite each numbered line as natural, idiomatic American English - the way a lecturer "
    "actually talks to a room, not written prose. Fix every grammatical error. Keep his "
    "meaning, his emphasis and his examples exactly; keep every number, name and technical "
    "term.\n"
    "LENGTH MATTERS: each line is spoken over the same moment of video it came from, so keep "
    "it close to the same spoken length. Shorter is safer than longer. Cut the false starts, "
    "the 'um's and the repetitions - that is where the room comes from.\n"
    "Do not merge lines, do not split them, do not add or drop any. Reply with a JSON object "
    "whose keys are exactly the line numbers you were given and whose values are the English. "
    "Nothing else."
)


def translate(segs, cfg, k):
    out = [None] * len(segs)
    size = max(5, int(cfg["batch"]))
    for a in range(0, len(segs), size):
        part = segs[a:a + size]
        lines = "\n".join("%d. %s" % (a + i + 1, s["said"]) for i, s in enumerate(part))
        want = [str(a + i + 1) for i in range(len(part))]
        got = None
        for attempt in (1, 2):
            body = json.dumps({
                "model": cfg["writer"], "temperature": 0.4,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": TRANSLATE},
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


def speak(text, cfg, k, dest):
    body = json.dumps({
        "model": cfg["speaker"], "voice": cfg["voice"], "input": text,
        "response_format": "mp3",
        "instructions": "An American man teaching a university class: warm, clear and "
                        "unhurried, explaining rather than announcing. Natural emphasis on "
                        "the words that carry the point. Never sound like a newsreader."}).encode()
    raw = post("https://api.openai.com/v1/audio/speech", body,
               {"Authorization": "Bearer " + k, "Content-Type": "application/json"})
    open(dest, "wb").write(raw)


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

            over = want - room
            if over > 0.05:
                report.append((i, start, "runs %.1fs past its slot even at %.0f%% speed"
                               % (over, tempo * 100)))
            elif tempo > 1.02:
                report.append((i, start, "sped up to %.0f%% to fit" % (tempo * 100)))

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


def main():
    if len(sys.argv) < 2:
        die("Drag an .mp4 onto Replace.bat, or run:  python replacer.py \"your video.mp4\"")
    video = os.path.abspath(sys.argv[1])
    if not os.path.exists(video):
        die("There is no file at %s" % video)

    cfg, k = config(), key()
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
        tight = [r for r in report if "past its slot" in r[2]]
        f.write("Lines that would not fit even sped up: %d\n" % len(tight))
        f.write("Lines that had to be sped up at all:   %d\n\n" % (len(report) - len(tight)))
        if tight:
            f.write("Shorten these and run it again if they matter:\n")
            for i, at, why in tight:
                f.write("  %s  line %d  %s\n     %s\n" % (clock(at), i + 1, why, segs[i]["en"][:110]))
            f.write("\n")
        for i, at, why in report:
            if "past its slot" not in why:
                f.write("  %s  line %d  %s\n" % (clock(at), i + 1, why))

    if not cfg.get("keep_work"):
        shutil.rmtree(folder, ignore_errors=True)

    tight = len([r for r in report if "past its slot" in r[2]])
    log("\n  Done in %.0f minutes.\n" % ((time.time() - began) / 60))
    log("   %s" % out_mp4)
    log("   %s" % fa)
    log("   %s" % en)
    log("   %s%s" % (rep, "   <- %d lines did not fit, have a look" % tight if tight else ""))
    log("")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        die("stopped by you")
    except Exception as e:
        die(str(e))
