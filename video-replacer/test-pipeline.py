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
import json, os, subprocess, sys, shutil, wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replacer as R

ok = lambda b: "PASS" if b else "**FAIL**"
fails = []


def check(n, what, good, extra=""):
    print("%d. %-58s %s %s" % (n, what, ok(good), extra))
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
    R.config = lambda: dict(R.DEFAULTS, keep_work=True)

    sys.argv = ["replacer.py", video]
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
    check(14, "a line that will not fit even at the cap is reported, not hidden",
          "line 4" in rep and "past its slot" in rep)
    check(15, "it was capped rather than made unlistenable",
          "120%" in rep or "1.2" in rep, [l for l in rep.splitlines() if "line 4" in l])

    print("\n--- the report it wrote ---")
    print(rep.strip()[:700])
    shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


main()
