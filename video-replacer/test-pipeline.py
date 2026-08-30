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


def main():
    work = os.path.join(HERE, "_test")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    video = os.path.join(work, "lecture.mp4")
    build_input(video)
    print("   made a %.0f-second test lecture\n" % TOTAL)

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

    R.WORK = os.path.join(work, "work")
    R.OUT = os.path.join(work, "out")
    print("\n--- the report it wrote ---")
    print(rep.strip()[:700])
    shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


main()
