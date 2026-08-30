# -*- coding: utf-8 -*-
"""The whole pipeline on a made-up lecture, with nothing sent anywhere.

The three steps that cost money are replaced: the transcriber returns known
lines at known times, the writer returns known English, and the voice writes a
real mp3 of a known length. Everything else - ffmpeg, the chunking, the fitting,
the muxing, the subtitles - is the real code.

What it is actually checking is the thing that is hard to see by watching once:
that every line ends up at the moment of video it belongs to, that a line too
long for its slot is sped up rather than allowed to trample the next one, and
that the picture came through untouched.
"""
import io, json, os, subprocess, sys, shutil, wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replacer as R

REAL_CONFIG = R.config          # main() stubs it out; the window needs the real one
REAL_YT = R.yt_transcript      # and so does the check that the upload is deleted
REAL_FIT, REAL_RATE = R.fit_english, R.voice_rate      # likewise, for the same reason
REAL_SPEAK = R.speak           # and again. This trap has now been fallen into four times

ok = lambda b: "PASS" if b else "**FAIL**"
fails = []


def check(n, what, good, extra=""):
    print("%-3s %-58s %s %s" % (str(n) + ".", what, ok(good), extra))
    if not good:
        fails.append(n)


# a lecture: 40 seconds, four things said, with real gaps between them
SAID = [
    (2.0,  6.0,  "سلام به همه، امروز درباره ارزش فعلی حرف می‌زنیم",
                 "Hi everyone. Today we are talking about present value."),
    (10.0, 14.0, "اول باید نرخ تنزیل را پیدا کنیم",
                 "First we have to find the discount rate."),
    (20.0, 23.0, "بعد جریان نقدی را تقسیم می‌کنیم",
                 "Then we divide the cash flow."),
    # deliberately far more English than will fit, with another line right behind
    # it so it cannot simply borrow the rest of the lecture
    (30.0, 33.0, "و در نهایت جواب را می‌گیریم",
                 "And finally we arrive at the answer, which is the number we have been "
                 "working towards this whole time and the one that matters most of all."),
    (34.5, 37.0, "هفته بعد می‌بینمتان",
                 "See you next week."),
]
TOTAL = 40.0


def build_input(path):
    subprocess.run([R.tool("ffmpeg"), "-y", "-v", "error",
                    "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=%g" % TOTAL,
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=%g" % TOTAL,
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", path], check=True)


def fake_speak(text, cfg, k, dest):
    """A tone as long as the words would take: about 2.6 words a second."""
    secs = max(0.6, len(text.split()) / 2.6)
    subprocess.run([R.tool("ffmpeg"), "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=%.3f" % secs,
                    "-c:a", "libmp3lame", "-b:a", "64k", dest], check=True)


def energy_windows(path, rate=8000):
    """Where there is sound in the finished file, half-second by half-second."""
    raw = subprocess.run([R.tool("ffmpeg"), "-v", "error", "-i", path, "-f", "s16le",
                          "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(rate), "-"],
                         stdout=subprocess.PIPE, check=True).stdout
    import array
    a = array.array("h"); a.frombytes(raw[:len(raw) // 2 * 2])
    step, out = rate // 2, []
    for i in range(0, len(a) - step, step):
        chunk = a[i:i + step]
        out.append(sum(abs(x) for x in chunk) / float(step))
    return out


def window_checks(work):
    """The window itself, opened for real. A setting that does not come back is
    a setting you have to set again every time, and a colour that goes pale
    under the pointer is a line you cannot read - both were real bugs."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        print("30. (the window checks need tkinter - skipped here)")
        return
    try:
        root = tk.Tk()
    except Exception as e:
        print("30. (no display for the window checks - skipped: %s)" % str(e)[:60])
        return
    root.destroy()

    import importlib.machinery, importlib.util
    spec = importlib.util.spec_from_loader("appmod", importlib.machinery.SourceFileLoader(
        "appmod", os.path.join(HERE, "app.pyw")))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    saved = os.path.join(HERE, "config.json")
    keep = open(saved, encoding="utf-8").read() if os.path.exists(saved) else None
    stub, R.config = R.config, REAL_CONFIG    # the window must read the real file
    try:
        app = m.App(); app.update()
        app.v_out.set(os.path.join(work, "elsewhere"))
        app.v_cuda.set(False)
        app.v_in.set(os.path.join(work, "a lecture.mp4"))
        app.v_source.set("youtube")
        app.v_lang.set("Hindi \u0939\u093f\u0928\u094d\u0926\u0940")
        app.v_proof.set(False)
        app.v_keepwork.set(True)
        app.update()
        yt_hint = app.vid_hint.cget("text")
        app.v_source.set("here"); app.update()
        here_hint = app.vid_hint.cget("text")
        app.v_source.set("youtube"); app.update()
        app.v_ytdel.set(False); app.v_ytwait.set("7")

        wrote = app.settings()
        json.dump(wrote, open(saved, "w", encoding="utf-8"), indent=2)
        app.shut()

        again = m.App(); again.update()
        back = {"out_dir": again.v_out.get(), "use_gpu": again.v_cuda.get(),
                "last_video": again.v_in.get(), "youtube_delete": again.v_ytdel.get(),
                "youtube_wait_minutes": int(again.v_ytwait.get()),
                "transcript_from": again.v_source.get(), "language": again.v_lang.get(),
                "proofread": again.v_proof.get(), "keep_work": again.v_keepwork.get()}
        st = ttk.Style(again)
        pale = []
        for w, want in (("TCheckbutton", "#0d1118"), ("TRadiobutton", "#0d1118"),
                        ("Card.TCheckbutton", "#161d2b"), ("Card.TRadiobutton", "#161d2b")):
            for state in ((), ("active",), ("focus",), ("selected",), ("pressed",),
                          ("active", "selected"), ("focus", "selected")):
                for what in ("background", "focuscolor"):
                    got = str(st.lookup(w, what, state)).lower()
                    if got != want:
                        pale.append("%s %s %s=%s" % (w, ",".join(state) or "normal", what, got))
        again.shut()
    finally:
        R.config = stub
        if keep is None:
            if os.path.exists(saved):
                os.remove(saved)
        else:
            open(saved, "w", encoding="utf-8").write(keep)

    check(30, "every setting the window offers comes back after a restart",
          back == {"out_dir": os.path.join(work, "elsewhere"), "use_gpu": False,
                   "last_video": os.path.join(work, "a lecture.mp4"),
                   "youtube_delete": False, "youtube_wait_minutes": 7,
                   "transcript_from": "youtube",
                   "language": "Hindi \u0939\u093f\u0928\u094d\u0926\u0940",
                   "proofread": False, "keep_work": True}, back)
    check(31, "the video row says who is going to listen to it, and changes with the choice",
          "YouTube" in yt_hint and "deleted" in yt_hint
          and "Whisper" in here_hint and "never uploaded" in here_hint,
          [yt_hint[:50], here_hint[:50]])
    check(32, "no tick or radio goes pale under the pointer", not pale, pale[:3])


def youtube_checks(work):
    """The upload path cannot be tried against the real YouTube without spending
    quota and putting a lecture on somebody's channel, so the requests it builds
    are checked instead: what it sends, in what order, and - the one that
    matters - that the upload comes down again even when nothing else works."""
    import urllib.error, urllib.request

    real = urllib.request.urlopen
    big = os.path.join(work, "big.mp4")
    io.open(big, "wb").write(b"x" * (5 << 20))          # 5 MB, so it takes two chunks
    seen = []

    class Fake(object):
        def __init__(self, body=b"{}", headers=None):
            self.body, self.headers, self.status = body, headers or {}, 200
        def read(self): return self.body
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(req, timeout=None):
        seen.append({"url": req.full_url, "method": req.get_method(),
                     "headers": dict(req.headers),
                     "len": len(req.data) if req.data else 0,
                     "body": req.data if (req.data and len(req.data) < 4000) else None})
        if req.get_method() == "POST":
            return Fake(b"{}", {"Location": "https://upload.example/session"})
        if req.get_method() == "PUT":
            rng = req.headers.get("Content-range", "")
            if rng.split("/")[0].split("-")[-1] == str(len(b"x" * (5 << 20)) - 1):
                return Fake(b'{"id":"VID12345678"}')
            raise urllib.error.HTTPError(req.full_url, 308, "Resume", {}, io.BytesIO(b""))
        return Fake(b"{}")

    urllib.request.urlopen = fake
    try:
        vid = R.yt_upload(big, "tok", say=lambda m: None, chunk=4 << 20)
        posts = [r for r in seen if r["method"] == "POST"]
        puts = [r for r in seen if r["method"] == "PUT"]
        meta = json.loads(posts[0]["body"])
        sent = sum(r["len"] for r in puts)
        ranges = [r["headers"].get("Content-range") for r in puts]
    finally:
        urllib.request.urlopen = real

    check(33, "the upload goes up unlisted, whole, and in order",
          vid == "VID12345678"
          and meta["status"]["privacyStatus"] == "unlisted"
          and posts[0]["headers"].get("X-upload-content-length") == str(5 << 20)
          and sent == (5 << 20) and len(puts) == 2
          and ranges == ["bytes 0-4194303/5242880", "bytes 4194304-5242879/5242880"],
          ranges)

    # --- and it comes down again, even when everything after it fails ---
    deleted = []

    def fake2(req, timeout=None):
        m = req.get_method()
        if m == "POST":
            return Fake(b"{}", {"Location": "https://upload.example/session"})
        if m == "PUT":
            return Fake(b'{"id":"VID12345678"}')
        if m == "DELETE":
            deleted.append(req.full_url)
            return Fake(b"")
        raise urllib.error.HTTPError(req.full_url, 403, "no", {}, io.BytesIO(
            b'{"error":{"message":"the caption track cannot be downloaded"}}'))

    urllib.request.urlopen = fake2
    R.yt_access = lambda: "tok"
    small = os.path.join(work, "small.mp4")
    io.open(small, "wb").write(b"x" * 1000)
    why = ""
    try:
        REAL_YT(small, {"youtube_wait_minutes": 1}, say=lambda m: None)
    except Exception as e:
        why = str(e)
    finally:
        urllib.request.urlopen = real

    check(34, "the upload is deleted even when the captions never arrive",
          len(deleted) == 1 and "VID12345678" in deleted[0] and "captions" in why.lower(),
          [deleted, why[:60]])


def sync_checks(work):
    """The thing he actually heard: his voice and the English drifting apart.

    Measured in the finished audio rather than argued about. Each line is spoken
    at its own loudness, so a tenth of a second of sound can be traced back to
    the line it came from and the answer is where that line really landed. Run
    twice: once with the cap that stops lateness accumulating, once with it
    switched off, which is what the program used to do. A test that only passes
    is not evidence - this one has to show the bug before it shows the fix."""
    rate = 24000
    # each line's text names itself, so the tone made for it can be told apart
    lines = [{"start": i * 4.0, "end": i * 4.0 + 3.0, "said": "x",
              "en": "L%02d " % i + " ".join(["word"] * ((8 if i != 3 else 30) - 1))}
             for i in range(16)]
    # a different pitch per line: loudness survives encoding badly, pitch does not
    tone = [300 + i * 60 for i in range(len(lines))]          # 300 .. 1200 Hz

    def speak_at_its_own_pitch(text, cfg, k, dest):
        n = len(text.split())
        i = int(text.split()[0][1:])
        secs = max(0.6, n / 2.6)
        subprocess.run([R.tool("ffmpeg"), "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=%d:duration=%.3f" % (tone[i], secs),
                        "-c:a", "libmp3lame", "-b:a", "64k", dest], check=True)

    def landed(cfg, name):
        """Where each line's own sound actually starts, by its loudness."""
        folder = os.path.join(work, name)
        shutil.rmtree(folder, ignore_errors=True); os.makedirs(folder)
        was, R.speak = R.speak, speak_at_its_own_pitch
        try:
            track, report = R.build_track([dict(s) for s in lines], cfg, folder, 80.0, "k")
        finally:
            R.speak = was
        raw = subprocess.run([R.tool("ffmpeg"), "-v", "error", "-i", track, "-f", "s16le",
                              "-acodec", "pcm_s16le", "-ac", "1", "-ar", "8000", "-"],
                             stdout=subprocess.PIPE, check=True).stdout
        import array
        a = array.array("h"); a.frombytes(raw[:len(raw) // 2 * 2])
        step = 800                                   # a tenth of a second at 8 kHz
        seen = {}
        for k in range(0, len(a) - step, step):
            piece = a[k:k + step]
            if max(abs(x) for x in piece) < 2000:
                continue
            crossings = sum(1 for j in range(1, step)
                            if (piece[j - 1] < 0) != (piece[j] < 0))
            hz = crossings * 5.0                     # crossings per 0.1s -> Hz
            i = min(range(len(tone)), key=lambda j: abs(tone[j] - hz))
            if abs(tone[i] - hz) < 22:               # confidently that line
                seen.setdefault(i, k / 8000.0)
        late = {i: seen[i] - lines[i]["start"] for i in seen}
        return late, report, len(seen)

    loose, _, found_loose = landed(
        dict(R.DEFAULTS, sample_rate=rate, max_drift=999.0, catch_up_tempo=1.20), "sync_loose")
    capped, report, found = landed(dict(R.DEFAULTS, sample_rate=rate), "sync_capped")

    worst_loose = max(loose.values()) if loose else 0.0
    worst = max(capped.values()) if capped else 0.0

    check(35, "without the cap, one long line drags everything after it out of step",
          found_loose >= 10 and worst_loose > 2.0,
          "worst %.1fs behind, %d lines traced" % (worst_loose, found_loose))
    check(36, "with it, no line is ever more than three quarters of a second late",
          found >= 10 and worst <= 0.85,
          "worst %.2fs behind, %d lines traced" % (worst, found))

    culprits = [r for r in report if len(r) > 3 and r[3]]
    check(37, "and the one over-long line is named as the cause, on its own",
          len(culprits) == 1 and culprits[0][0] == 3,
          [(r[0], r[2][:38]) for r in report][:4])

    # --- speaking faster is always tried before anything is thrown away ---
    # 13 words in a 4s slot needs about 5.0s: too much for 145%, inside 160%
    edge = [{"start": i * 4.0, "end": i * 4.0 + 3.0, "said": "x",
             "en": " ".join(["word"] * (13 if i == 2 else 8))} for i in range(6)]
    folder = os.path.join(work, "squeeze")
    shutil.rmtree(folder, ignore_errors=True); os.makedirs(folder)
    _, rep = R.build_track([dict(x) for x in edge],
                           dict(R.DEFAULTS, sample_rate=rate), folder, 30.0, "k")
    cut_now = [r for r in rep if "cut short" in r[2]]
    hurried = [r for r in rep if "sped up" in r[2]]
    check("38b", "a line that only just will not fit is hurried, never cut",
          not cut_now and hurried, [(r[0], r[2][:34]) for r in rep])

    # --- the same lines, whoever wrote them down, land in the same place ---
    def track_of(name):
        folder = os.path.join(work, name)
        shutil.rmtree(folder, ignore_errors=True); os.makedirs(folder)
        t, _ = R.build_track([dict(s) for s in lines],
                             dict(R.DEFAULTS, sample_rate=rate), folder, 80.0, "k")
        return open(t, "rb").read()

    check(38, "the two ways of getting the words place the audio identically",
          track_of("from_whisper") == track_of("from_youtube"), "byte-for-byte")


def fitting_checks(work):
    """Nothing should ever be cut short, because nothing over-long should reach
    the voice. Checked against a made-up voice with a known speaking speed, so
    the arithmetic has a right answer rather than an opinion."""
    said = []
    R.log = lambda m: said.append(m)

    lines = [{"start": i * 4.0, "end": i * 4.0 + 3.5, "said": "x",
              "en": " ".join(["word"] * (10 if i != 2 else 40))} for i in range(6)]

    # a writer that obeys the word limit it is given, which is what we are
    # checking the caller asks for correctly
    asked = []

    def fake_post(url, body, headers):
        import json as J
        sent = J.loads(body)
        text = sent["messages"][-1]["content"]
        out = {}
        for row in text.strip().splitlines():
            n, rest = row.split(".", 1)
            cap = int(re.search(r"at most (\d+) words", rest).group(1))
            asked.append((int(n), cap))
            out[n.strip()] = " ".join(["short"] * max(1, cap))
        return J.dumps({"choices": [{"message": {"content": J.dumps(out)}}]})

    import re
    real_post, R.post = R.post, fake_post
    try:
        segs, trimmed, left = REAL_FIT([dict(s) for s in lines],
                                            dict(R.DEFAULTS), "k", 2.5, 30.0)
    finally:
        R.post = real_post

    caps = dict(asked)
    # line 2 has 4.0s of slot plus 0.75s of allowed lateness, at 2.5 words a
    # second and up to the 160% squeeze: about 19 words
    check(39, "a line is only rewritten when even full speed would not save it",
          list(caps) == [3] and 16 <= caps[3] <= 22, asked)
    check(40, "and afterwards nothing is left that would have to be cut",
          trimmed == 1 and not left and len(segs[2]["en"].split()) <= caps[3],
          "%d trimmed, %d still long" % (trimmed, len(left)))
    check("40b", "what it used to say is kept, so you can put your own words back",
          segs[2].get("was") == " ".join(["word"] * 40),
          (segs[2].get("was") or "")[:30])
    check(41, "every line is told how many words it has room for",
          all(isinstance(s.get("fit"), int) and s["fit"] > 0 for s in segs),
          [s.get("fit") for s in segs])

    # --- the voice is timed once and remembered ---
    spoke = []

    def fake_speak(text, cfg, k, dest):
        spoke.append(text)
        subprocess.run([R.tool("ffmpeg"), "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=%.3f" % (len(text.split()) / 3.0),
                        "-c:a", "libmp3lame", "-b:a", "64k", dest], check=True)

    was, R.say_once = R.say_once, fake_speak
    saved = os.path.join(HERE, "config.json")
    keep = open(saved, encoding="utf-8").read() if os.path.exists(saved) else None
    try:
        cfg = dict(R.DEFAULTS, voice="testvoice", voice_rates={})
        first = REAL_RATE(cfg, "k")
        second = REAL_RATE(cfg, "k")
    finally:
        R.say_once = was
        if keep is None:
            if os.path.exists(saved): os.remove(saved)
        else:
            open(saved, "w", encoding="utf-8").write(keep)

    check(42, "the voice is timed once, then remembered rather than timed again",
          len(spoke) == 1 and abs(first - 3.0) < 0.25 and second == first,
          "%.2f words a second, spoken %d time(s)" % (first, len(spoke)))


def caption_checks(work):
    """YouTube's cues are not sentences, and treating them as if they were is
    what makes the finished voice sound like it keeps getting stuck."""
    # exactly the shape YouTube produces: every cue's window overlaps the next
    rolling = ("1\n00:00:01,240 --> 00:00:07,480\none two three\n\n"
               "2\n00:00:04,400 --> 00:00:12,040\nfour five six\n\n"
               "3\n00:00:07,480 --> 00:00:16,960\nseven eight nine\n\n"
               "4\n00:00:14,440 --> 00:00:21,800\nten eleven\n")
    cues = R.parse_srt(rolling)
    ends_before_next = all(cues[i]["end"] <= cues[i + 1]["start"] + 1e-6
                           for i in range(len(cues) - 1))
    check(43, "a rolling caption's end is pulled back to where the next one starts",
          ends_before_next and abs(cues[0]["end"] - 4.4) < 1e-6,
          [(round(c["start"], 2), round(c["end"], 2)) for c in cues])

    # nothing downstream can find a pause while the gaps are all negative
    gaps_now = [cues[i + 1]["start"] - cues[i]["end"] for i in range(len(cues) - 1)]
    check("43b", "so the gaps between lines stop being negative",
          all(g >= -1e-6 for g in gaps_now), [round(g, 2) for g in gaps_now])

    # the pause is at 9.0s, which is INSIDE cue 3 - nowhere near any boundary.
    # That is the whole point: the boundaries are not where the pauses are.
    joined = R.resplit([dict(c) for c in cues], [(9.0, 0.6)], longest=30.0)
    check(44, "the words are cut where he stopped, not where the caption ended",
          len(joined) == 2 and abs(joined[0]["end"] - joined[1]["start"]) < 1e-6
          and abs(joined[1]["start"] - 9.0) < 0.9
          and joined[0]["said"].startswith("one two")
          and joined[1]["said"].endswith("ten eleven"),
          [(round(j["start"], 2), j["said"]) for j in joined])

    check("44b", "and no word is lost or duplicated in the process",
          " ".join(j["said"] for j in joined)
          == " ".join(c["said"] for c in cues),
          " ".join(j["said"] for j in joined))

    every = R.resplit([dict(c) for c in cues], [], longest=6.0)
    # a line can only be cut at a word, so it may run over by at most the gap to
    # the next one - and the last line runs to the end of the recording
    times = [t for t, _ in R.word_times(cues)]
    gap = max(times[i + 1] - times[i] for i in range(len(times) - 1))
    spans = [j["end"] - j["start"] for j in every[:-1]]
    check(45, "with no pauses at all it still cuts at the length allowed",
          all(v <= 6.0 + gap + 0.01 for v in spans) and len(every) >= 3,
          [round(v, 2) for v in spans] + ["limit 6.0 + one %.1fs word gap" % gap])

    check("45b", "a hesitation is not a break",
          len(R.resplit([dict(c) for c in cues], [(9.0, 0.20)], longest=30.0)) == 1,
          "short pauses ignored")


def take_checks(work):
    """A cloned voice does not fail loudly - it rambles, and a long file is not
    an error. The words are the check: how long a line SHOULD take is known."""
    made = []

    def bad_then_good(text, cfg, k, dest, lengths=[9.98, 5.10]):
        secs = lengths[min(len(made), len(lengths) - 1)]
        made.append(secs)
        subprocess.run([R.tool("ffmpeg"), "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=%.3f" % secs,
                        "-c:a", "libmp3lame", "-b:a", "64k", dest], check=True)

    # his real numbers: 14 words at the 2.743 words a second his voice was
    # measured at should be 5.1s. The take that made the wind noise was 9.98s.
    text = " ".join(["word"] * 14)
    cfg = dict(R.DEFAULTS, voice="mine:Milad", voice_rates={"mine:Milad": 2.743})
    dest = os.path.join(work, "take.mp3")
    was, R.say_once = R.say_once, bad_then_good
    said = []
    old_log, R.log = R.log, lambda m: said.append(m)
    try:
        REAL_SPEAK(text, cfg, "k", dest)
        first_len = R.duration(dest)
    finally:
        R.say_once, R.log = was, old_log

    check(46, "a take nearly twice too long for its words is said again",
          len(made) == 2 and abs(first_len - 5.10) < 0.35,
          "attempts %s, kept %.2fs" % ([round(m, 2) for m in made], first_len))
    check("46b", "and it says so rather than doing it silently",
          any("saying it again" in m for m in said), [m.strip()[:44] for m in said])

    # when nothing comes back right, the closest attempt is what is used
    made2 = []

    def always_bad(text, cfg, k, dest, lengths=[12.0, 9.0, 20.0]):
        secs = lengths[min(len(made2), len(lengths) - 1)]
        made2.append(secs)
        subprocess.run([R.tool("ffmpeg"), "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=%.3f" % secs,
                        "-c:a", "libmp3lame", "-b:a", "64k", dest], check=True)

    was, R.say_once = R.say_once, always_bad
    old_log, R.log = R.log, lambda m: None
    try:
        REAL_SPEAK(text, cfg, "k", dest)
        kept = R.duration(dest)
    finally:
        R.say_once, R.log = was, old_log
    check(47, "and when none of them is right, the closest one is kept",
          len(made2) == 3 and abs(kept - 9.0) < 0.35,
          "attempts %s, kept %.2fs" % ([round(m, 2) for m in made2], kept))

    # a good take is never said twice
    made3 = []

    def good(text, cfg, k, dest):
        made3.append(1)
        subprocess.run([R.tool("ffmpeg"), "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=5.10",
                        "-c:a", "libmp3lame", "-b:a", "64k", dest], check=True)

    was, R.say_once = R.say_once, good
    try:
        REAL_SPEAK(text, cfg, "k", dest)
    finally:
        R.say_once = was
    check(48, "a good take is spoken once and never paid for twice", len(made3) == 1,
          "%d attempt(s)" % len(made3))


def wording_checks(work):
    """Two small things he asked for, both worth a check because both are the
    kind that quietly stop working."""
    here = os.path.join(HERE, "say.txt")
    keep = open(here, encoding="utf-8").read() if os.path.exists(here) else None
    try:
        io.open(here, "w", encoding="utf-8").write("ChatGPT = Chat G P T\nOpenAI = Open A I\n")
        spoken = R.as_spoken("Open the ChatGPT page, then OpenAI's, then chatgpt again.")
    finally:
        if keep is None:
            os.remove(here)
        else:
            io.open(here, "w", encoding="utf-8").write(keep)

    check(49, "a word can be written one way and spoken another",
          "Chat G P T" in spoken and "Open A I" in spoken and "ChatGPT" not in spoken,
          spoken)
    check("49b", "and only the spoken copy changes - it is a function, not an edit",
          R.as_spoken("ChatGPT", []) == "ChatGPT", "with no list, nothing happens")

    check(50, "the writer's instructions are mine until you change them",
          R.writer_rules({}) == R.TRANSLATE
          and R.writer_rules({"writer_prompt": "   "}) == R.TRANSLATE
          and R.writer_rules({"writer_prompt": "say it like a pirate"}) == "say it like a pirate")


def main():
    work = os.path.join(HERE, "_test")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    video = os.path.join(work, "lecture.mp4")
    build_input(video)
    print("   made a %.0f-second test lecture\n" % TOTAL)

    real_transcribe = R.transcribe        # kept, so test 24 can ask the real one
    R.speak = fake_speak
    R.transcribe = lambda chunks, cfg, k: [
        {"start": a, "end": b, "said": fa} for a, b, fa, en in SAID]
    R.translate = lambda segs, cfg, k: [
        dict(s, en=SAID[i][3]) for i, s in enumerate(segs)]
    # fitting has its own checks below; here the deliberately over-long line has
    # to survive so the last-resort cut can be seen doing its job
    R.fit_english = lambda segs, *a, **kw: (segs, 0, [])
    R.voice_rate = lambda cfg, k, say=None: 2.6

    def no_network(*a, **kw):
        raise AssertionError("the tests must not talk to anyone")

    R.post = no_network
    R.WORK = os.path.join(work, "work")
    R.OUT = os.path.join(work, "out")
    R.key = lambda: "not-used"
    R.config = lambda: dict(R.DEFAULTS, keep_work=True, proofread=False)

    # --- it stops for you before it speaks anything ---
    sys.argv = ["replacer.py", video]
    R.main()
    sheet = os.path.join(work, "out", "lecture.review.txt")
    check(0, "it stops and asks before spending anything on the voice",
          os.path.exists(sheet) and not os.path.exists(os.path.join(work, "out", "lecture.en.mp4")))
    if os.path.exists(sheet):
        text = open(sheet, encoding="utf-8").read()
        check("0b", "the sheet shows what you said and what will be spoken",
              SAID[0][2] in text and SAID[0][3] in text and "max" in text)
        # change one line by hand, exactly as you would in Notepad
        io.open(sheet, "w", encoding="utf-8-sig", newline="\r\n").write(
            text.replace(SAID[1][3], "I FIXED THIS LINE MYSELF."))

    sys.argv = ["replacer.py", video, "--go"]
    R.main()

    out = os.path.join(work, "out", "lecture.en.mp4")
    check(1, "it produces the video", os.path.exists(out))
    if not os.path.exists(out):
        return

    def probe(what, f):
        return subprocess.run([R.tool("ffprobe"), "-v", "error", "-select_streams", what,
                               "-show_entries", "stream=codec_name", "-of", "default=nk=1:nw=1", f],
                              stdout=subprocess.PIPE, text=True).stdout.strip()

    check(2, "the picture is the same stream, not re-encoded",
          probe("v:0", out) == probe("v:0", video), probe("v:0", out))
    check(3, "it has exactly one audio track", probe("a", out).count("\n") == 0, probe("a", out))
    d_in, d_out = R.duration(video), R.duration(out)
    check(4, "it is the same length as what went in", abs(d_in - d_out) < 0.6,
          "%.1fs -> %.1fs" % (d_in, d_out))

    # --- the point of the whole thing: is each line where it belongs? ---
    e = energy_windows(out)
    loud = max(e) if e else 0
    def speaking(t):
        i = int(t * 2)
        return i < len(e) and e[i] > loud * 0.25

    check(5, "line one starts when it did in the original", speaking(2.6))
    check(6, "the gap after it is still silent", not speaking(8.0))
    check(7, "line two lands at its own moment", speaking(10.6))
    check(8, "the gap before line three is still silent", not speaking(17.0))
    check(9, "line three lands at its own moment", speaking(20.6))
    check(10, "the long line still starts on time", speaking(30.6))

    # --- the subtitles ---
    fa = os.path.join(work, "out", "lecture.original.srt")
    en = os.path.join(work, "out", "lecture.english.srt")
    fa_txt = open(fa, encoding="utf-8").read()
    en_txt = open(en, encoding="utf-8").read()
    check(11, "the original-language subtitles are there and in Persian",
          "ارزش فعلی" in fa_txt and "00:00:02,000 --> 00:00:06,000" in fa_txt)
    check(12, "the English subtitles are there, on the same clock",
          "present value" in en_txt and "00:00:02,000 --> 00:00:06,000" in en_txt)
    check(13, "every line made it into both", fa_txt.count("-->") == len(SAID)
          and en_txt.count("-->") == len(SAID),
          "%d / %d" % (fa_txt.count("-->"), en_txt.count("-->")))

    # --- the report has to name the line that could not fit ---
    rep = open(os.path.join(work, "out", "lecture.report.txt"), encoding="utf-8").read()
    check(14, "the line whose English is too long is named",
          "line 4" in rep and "too long for its" in rep,
          [l.strip() for l in rep.splitlines() if "line 4" in l])
    # the old report blamed every line after a long one as well. A line that is
    # only late is a victim, and saying so is the difference between one thing
    # to fix and twenty-three.
    check(15, "and the lines it merely pushed are counted apart from it",
          "Lines whose English is too long" in rep and "merely pushed" in rep)

    # --- the fixes that came out of the first real lecture ---
    frags = [{"start": 0.0, "end": 2.0, "said": "one"},
             {"start": 2.2, "end": 4.0, "said": "two"},
             {"start": 9.0, "end": 11.0, "said": "far away"}]
    m = R.merge(frags, longest=10.0, gap=0.8)
    check(16, "fragments a breath apart become one sentence",
          len(m) == 2 and m[0]["said"] == "one two" and m[0]["end"] == 4.0,
          [x["said"] for x in m])
    check(17, "a long pause is left as a break", m[1]["said"] == "far away")

    # a two-second moment holds about five spoken words, and the writer is told so
    b = R.budget([{"start": 10.0, "end": 12.0}, {"start": 12.0, "end": 14.0}], 0)
    check(18, "each line is given the word budget its moment allows", b == 5, "%d words" % b)

    # half of a three-word clip came back as silence; over a lecture that is
    # half a minute of dead air pushing everything out of step
    pad = os.path.join(work, "padded.mp3")
    cut = os.path.join(work, "cut.mp3")
    subprocess.run([R.tool("ffmpeg"), "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=1", "-af",
                    "adelay=1000|1000,apad=pad_dur=1", "-c:a", "libmp3lame", pad], check=True)
    R.trim_silence(pad, cut)
    before, after = R.duration(pad), R.duration(cut)
    check(19, "the silence either side of a spoken line is cut off",
          before > 2.8 and after < 1.4, "%.2fs -> %.2fs" % (before, after))

    # --- your correction has to survive into everything downstream ---
    check(20, "the line you fixed is the line that gets spoken",
          "I FIXED THIS LINE MYSELF." in en_txt and SAID[1][3] not in en_txt)

    terms = R.glossary()
    check(21, "the glossary is read", isinstance(terms, list))

    # --- walking away must not leave a lecture lying about ---
    left = os.path.join(work, "work2")
    R.WORK = left
    R.OUT = os.path.join(work, "out2")
    R.config = lambda: dict(R.DEFAULTS, keep_work=False, proofread=False)
    R.convert(video, say=lambda m: None, ask=lambda segs: None)
    inside = os.listdir(left) if os.path.isdir(left) else []
    check(22, "cancelling clears what it had started", not inside, inside)

    # --- and closing the app clears everything, unless you asked to keep it ---
    os.makedirs(os.path.join(left, "something"), exist_ok=True)
    R.clear_work(keep=True)
    kept = os.path.isdir(os.path.join(left, "something"))
    R.clear_work(keep=False)
    now = os.listdir(left) if os.path.isdir(left) else []
    check(23, "closing clears the work folder", kept and not now, "kept-when-asked=%s" % kept)

    # --- the language you pick is the language whisper is told, and no more ---
    sent = []
    real_multipart, real_post = R.multipart, R.post

    def spy(fields, name, data):
        sent.append(dict(fields))
        return b"", "text/plain"

    R.multipart = spy
    R.post = lambda *a, **k: json.dumps({"segments": []})
    try:
        real_transcribe([(video, 0.0)], dict(R.DEFAULTS, language="hi"), "k")
        real_transcribe([(video, 0.0)], dict(R.DEFAULTS, language=""), "k")
    finally:
        R.multipart, R.post = real_multipart, real_post
    check(24, "the language you pick is passed on, and blank is left out",
          sent[0].get("language") == "hi" and "language" not in sent[1],
          [f.get("language", "<omitted>") for f in sent])

    check(25, "any language, not only Persian, and English in is a rewrite",
          "Persian or English" not in R.TRANSLATE and "any language" in R.TRANSLATE
          and "already speaking English" in R.TRANSLATE)

    labels = [n for n, _ in R.LANGUAGES]
    check(26, "every language in the list survives the trip to config and back",
          all(R.language_label(R.language_code(n)) == n for n in labels)
          and R.language_code("ja") == "ja", len(labels))

    # --- YouTube's own transcript, when you ask for it ---
    srt_text = ("1\n00:00:00,500 --> 00:00:04,000\n\u0633\u0644\u0627\u0645 <i>\u062e\u0648\u0628</i>\n"
                "\n2\n00:00:04,000 --> 00:00:09,250\n\u062f\u0648\u0645\n\u062e\u0637\n\n"
                "3\n00:00:09,250 --> 00:00:10,000\n\n")
    cues = R.parse_srt(srt_text)
    check(27, "YouTube's subtitles come back as lines with real timings",
          len(cues) == 2 and abs(cues[0]["start"] - 0.5) < 1e-6
          and abs(cues[1]["end"] - 9.25) < 1e-6
          and "<i>" not in cues[0]["said"] and cues[1]["said"].count(" ") == 1,
          cues)

    asked = []
    R.yt_transcript = lambda vid, cfg=None, say=None: (
        asked.append(vid) or [{"start": a, "end": b, "said": fa} for a, b, fa, en in SAID])
    yt = os.path.join(work, "yt")
    R.WORK = yt
    R.OUT = os.path.join(work, "out3")
    R.config = lambda: dict(R.DEFAULTS, keep_work=True, proofread=False,
                            transcript_from="youtube")
    R.convert(video, say=lambda m: None, ask=lambda segs: segs)
    heard = os.path.join(yt, "lecture", "heard.json")
    voice = os.path.join(yt, "lecture", "voice.mp3")
    check(28, "asking YouTube uses its words, and the audio stays on this computer",
          asked == [video] and os.path.exists(heard)
          and os.path.exists(os.path.join(work, "out3", "lecture.en.mp4")),
          "the sound is still pulled out locally, to find the pauses - see 44")

    # --- and when YouTube says no, the run carries on rather than stopping ---
    def refuse(vid, cfg=None, say=None):
        raise RuntimeError("no captions on that video")

    R.yt_transcript = refuse
    said = []
    fell = os.path.join(work, "fell")
    R.WORK = fell
    R.OUT = os.path.join(work, "out4")
    R.convert(video, say=lambda m: said.append(m), ask=lambda segs: segs)
    check(29, "if YouTube refuses it says why and transcribes here instead",
          os.path.exists(os.path.join(work, "out4", "lecture.en.mp4"))
          and os.path.exists(os.path.join(fell, "lecture", "voice.mp3"))
          and any("no captions on that video" in m for m in said),
          [m.strip() for m in said if "YouTube" in m])

    R.config = lambda: dict(R.DEFAULTS, keep_work=True, proofread=False)
    R.WORK = os.path.join(work, "work")
    R.OUT = os.path.join(work, "out")
    window_checks(work)
    youtube_checks(work)
    sync_checks(work)
    fitting_checks(work)
    caption_checks(work)
    take_checks(work)
    wording_checks(work)
    print("\n--- the report it wrote ---")
    print(rep.strip()[:700])
    shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


main()
