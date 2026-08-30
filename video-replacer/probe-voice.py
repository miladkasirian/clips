# -*- coding: utf-8 -*-
"""Is a voice of your own actually open to this account, and what would it cost?

OpenAI does now have custom voices - the speech endpoint takes {"id": "voice_..."}
and there are endpoints for voice consents - but the documentation says they are
"limited to eligible customers" and does not say who. Asking the API is the only
honest way to find out, and every call here is a read: nothing is created, no
voice is made, nothing is spent.
"""
import json, os, sys, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replacer as R

KEY = R.key()


def get(path):
    req = urllib.request.Request("https://api.openai.com/v1/" + path,
                                 headers={"Authorization": "Bearer " + KEY})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:
        return 0, str(e)[:200]


print("\n  Asking what this account can reach. Nothing is created.\n")
for path in ["audio/voices", "audio/voice_consents", "voices", "voice_consents"]:
    code, body = get(path)
    verdict = {200: "AVAILABLE", 401: "key refused", 403: "not enabled for this account",
               404: "no such endpoint on this account"}.get(code, "HTTP %s" % code)
    print("  %-22s %-32s %s" % (path, verdict, body.replace("\n", " ")[:110]))

print("""
  200 on a voices endpoint means a voice of your own is possible.
  403 or 404 means it is gated, and the preset voices are what there is.
""")
