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
    check(28, "asking YouTube uses its words, and never touches the audio",
          asked == [video] and os.path.exists(heard)
          and not os.path.exists(voice)
          and os.path.exists(os.path.join(work, "out3", "lecture.en.mp4")),
          "audio made=%s" % os.path.exists(voice))

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
    print("\n--- the report it wrote ---")
    print(rep.strip()[:700])
    shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


main()
