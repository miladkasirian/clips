# -*- coding: utf-8 -*-
"""Your own voice, speaking English - a sample, before committing to anything.

The reference is thirty seconds of you from your own lecture. XTTS-v2 takes that
and speaks new English in the same voice. It runs here on your machine, so it
costs nothing to run and nothing leaves.

Deliberately a sample and not part of the app yet. It is slow on the processor,
it is licensed for non-commercial use, and whether it actually sounds like you is
something to hear rather than to be told. The next step - installing the CUDA
build of torch so the graphics card does the work - is a 2.5GB download, and
that is not worth doing until you have listened to this.
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("COQUI_TOS_AGREED", "1")     # the model's licence prompt
import replacer as R

REF = os.path.join(HERE, "voice", "reference.wav")
OUT = os.path.join(HERE, "samples")

# the same words the eleven preset voices said, so it is a fair comparison
SAMPLE = ("Alright, in this video I want to show you how to use this website. "
          "You will see the list of chapters, the resources for each week, and "
          "where to hand your work in.")

if not os.path.exists(REF):
    R.die("There is no reference recording at voice\\reference.wav")

import torch
from TTS.api import TTS

gpu = torch.cuda.is_available()
print("\n  reference : %s (%.0f seconds)" % (os.path.basename(REF), R.duration(REF)))
print("  running on: %s" % ("the graphics card" if gpu else
                            "the processor - slow, but it proves the point"))
print("  the model is about 1.8GB and downloads once\n")

began = time.time()
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cuda" if gpu else "cpu")
print("  model ready in %.0f seconds, speaking...\n" % (time.time() - began))

os.makedirs(OUT, exist_ok=True)
wav = os.path.join(OUT, "_your-cloned-voice.wav")
mp3 = os.path.join(OUT, "_your-cloned-voice.mp3")
began = time.time()
tts.tts_to_file(text=SAMPLE, speaker_wav=REF, language="en", file_path=wav)
took = time.time() - began

R.run([R.tool("ffmpeg"), "-y", "-v", "error", "-i", wav, "-c:a", "libmp3lame", "-b:a", "96k", mp3])
os.remove(wav)
spoken = R.duration(mp3)

print("  %.1f seconds of speech, made in %.0f seconds  (%.1fx real time)" % (spoken, took, took / spoken))
print("\n  Compare these three in samples\\ :")
print("     _your-real-voice.mp3    you, in Persian, from your own lecture")
print("     _your-cloned-voice.mp3  the same voice, speaking English")
print("     onyx.mp3                what the app uses now\n")
