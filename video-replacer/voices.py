# -*- coding: utf-8 -*-
"""Two jobs in one run, so only one set of calls is paid for.

1. MEASURE. The report said three-word lines were overrunning two-second slots,
   which cannot be about English being longer than Persian. This times the same
   short line as it comes back, and again with the silence trimmed off each end,
   and prints both. If the difference is large, the padding was the bug.

2. LISTEN. A ten-second sample of every voice the model offers, into samples\,
   so the voice is chosen by ear rather than by me picking one.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replacer as R

OUT = os.path.join(HERE, "samples")
MODEL = "gpt-4o-mini-tts"

# every voice worth trying; the ones the model refuses are simply skipped
VOICES = ["onyx", "ash", "echo", "ballad", "verse", "sage", "alloy",
          "fable", "coral", "nova", "shimmer"]

SAMPLE = ("Alright, in this video I want to show you how to use this website. "
          "You will see the list of chapters, the resources for each week, and "
          "where to hand your work in.")

SHORT = "And that's it."


def secs(path):
    return float(subprocess.run(
        [R.tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", path],
        stdout=subprocess.PIPE, text=True).stdout.strip())


def trim(src, dest, floor="-45dB"):
    """Cut the dead air off both ends. Trimming the tail means reversing the
    audio, trimming its new head, and reversing it back - ffmpeg has no
    'trim the end' filter, and this is the standard way round it."""
    R.run([R.tool("ffmpeg"), "-y", "-v", "error", "-i", src, "-af",
           "silenceremove=start_periods=1:start_silence=0:start_threshold=%s:detection=peak,"
           "areverse,"
           "silenceremove=start_periods=1:start_silence=0:start_threshold=%s:detection=peak,"
           "areverse" % (floor, floor), dest])


def say(text, voice, dest):
    body = json.dumps({"model": MODEL, "voice": voice, "input": text,
                       "response_format": "mp3",
                       "instructions": "An American man teaching a university class: warm, "
                                       "clear and unhurried, explaining rather than announcing."}).encode()
    raw = R.post("https://api.openai.com/v1/audio/speech", body,
                 {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    open(dest, "wb").write(raw)


KEY = R.key()
os.makedirs(OUT, exist_ok=True)

print("\n  1. WHERE THE TIME GOES  -  %r, three words\n" % SHORT)
raw = os.path.join(OUT, "_probe.mp3")
cut = os.path.join(OUT, "_probe.trimmed.mp3")
say(SHORT, "onyx", raw)
trim(raw, cut)
a, b = secs(raw), secs(cut)
print("     as it arrives      : %.2f s" % a)
print("     with the ends cut  : %.2f s" % b)
print("     dead air           : %.2f s  (%.0f%% of the file)" % (a - b, (a - b) / a * 100))
print("\n     Three words take about 1.2 seconds to say. Anything much above that")
print("     is silence the voice adds, and it is what pushed short lines over.\n")

print("  2. THE VOICES  -  ten seconds each, in samples\\\n")
ok = []
for v in VOICES:
    dest = os.path.join(OUT, "%s.mp3" % v)
    try:
        say(SAMPLE, v, dest)
        t = secs(dest)
        trim(dest, dest + ".t.mp3")
        os.replace(dest + ".t.mp3", dest)
        print("     %-9s %.1f s   %s.mp3" % (v, t, v))
        ok.append(v)
    except Exception as e:
        msg = str(e).replace("\n", " ")
        print("     %-9s not available (%s)" % (v, msg[:70]))

for f in (raw, cut):
    try: os.remove(f)
    except Exception: pass

print("\n     %d voices in: %s" % (len(ok), OUT))
print("     Play them, then put the one you want in config.json as \"voice\".\n")
