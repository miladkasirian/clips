# -*- coding: utf-8 -*-
"""The consent-screen logo. Drawn at 4x and shrunk, so the curves stay clean.

It has to say what the app does at 120 pixels: a frame of film with a new voice
coming out of it. A play triangle for the video, three bars beside it for the
speech that replaces the sound, and the sprocket holes so it reads as film
rather than as a generic media button."""
from PIL import Image, ImageDraw

S = 480                      # drawn big, saved small
R = S * 22 // 100            # corner radius
TEAL, BLUE = (49, 224, 192), (77, 141, 255)
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

# the gradient body, painted line by line then cut to a rounded square
grad = Image.new("RGBA", (S, S))
g = ImageDraw.Draw(grad)
for y in range(S):
    for_x = y / (S - 1.0)
    g.line([(0, y), (S, y)], fill=(
        int(TEAL[0] + (BLUE[0] - TEAL[0]) * for_x),
        int(TEAL[1] + (BLUE[1] - TEAL[1]) * for_x),
        int(TEAL[2] + (BLUE[2] - TEAL[2]) * for_x), 255))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=R, fill=255)
img.paste(grad, (0, 0), mask)

d = ImageDraw.Draw(img)
dark = (7, 11, 20, 255)

# sprocket holes down both edges - what makes it read as film
hole_w, hole_h = S * 7 // 100, S * 9 // 100
for i in range(4):
    y = S * 15 // 100 + i * (S * 23 // 100)
    for x in (S * 6 // 100, S - S * 6 // 100 - hole_w):
        d.rounded_rectangle([x, y, x + hole_w, y + hole_h],
                            radius=hole_w // 3, fill=(255, 255, 255, 86))

# the play triangle
cx, cy = S * 38 // 100, S // 2
h = S * 27 // 100
d.polygon([(cx - h * 45 // 100, cy - h), (cx - h * 45 // 100, cy + h),
           (cx + h * 80 // 100, cy)], fill=dark)

# the new voice coming out of it: uneven bars, so it reads as a waveform and
# not as the "skip to next track" button that a triangle beside two even bars is
bx = S * 62 // 100
bw = S * 45 // 1000
gap = int(bw * 1.75)
for i, tall in enumerate((0.20, 0.42, 0.62, 0.34)):
    x = bx + i * gap
    half = int(S * tall / 2)
    d.rounded_rectangle([x, cy - half, x + bw, cy + half],
                        radius=bw // 2, fill=dark)

img.resize((120, 120), Image.LANCZOS).save("icon.png")
# and the same picture as a Windows icon, for the exe itself
img.resize((256, 256), Image.LANCZOS).save(
    "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon.png 120x120, icon.ico written")
