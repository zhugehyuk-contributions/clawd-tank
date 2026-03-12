#!/usr/bin/env python3
"""
Generate PNG frames for all Clawd animations.

Uses the same pixel coordinates as the HTML designers for consistency.
Output PNGs use #1a1a2e background which png2rgb565.py treats as transparent.

Usage:
    python tools/sprite-designer/generate_sprite_pngs.py
"""

import os
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Error: Pillow is required. Install with: pip install Pillow")
    sys.exit(1)

W, H = 64, 64
BG = (0x1A, 0x1A, 0x2E)
BODY_COLOR = (0xFF, 0x6B, 0x2B)
BODY_DARK = (0x99, 0x3D, 0x1A)  # Sleeping variant
EYE_COLOR = (0x00, 0x00, 0x00)
EYE_CLOSED = (0x55, 0x55, 0x55)  # Sleeping closed eyes
ALERT_COLOR = (0xFF, 0xDD, 0x57)
SPARKLE_COLOR = (0xFF, 0xDD, 0x57)
Z_COLOR = (0x77, 0x77, 0xBB)     # Muted blue for sleeping "z"
Z_FADE = (0x55, 0x55, 0x88)      # Faded "z"
BLE_COLOR = (0x44, 0x66, 0xAA)   # Bluetooth icon color

# Clawd base dimensions (matches overlay in index.html)
BODY = {"x": 18, "y": 23, "w": 28, "h": 18}
EYES_LEFT = {"x": 25, "y": 28}
EYES_RIGHT = {"x": 37, "y": 28}
EYE_SIZE = 2
LEG_POSITIONS = [21, 26, 36, 41]
LEG_Y = 41
LEG_W, LEG_H = 2, 5
CLAW_LEFT = {"x": 14, "y": 27}
CLAW_RIGHT = {"x": 46, "y": 27}
CLAW_W, CLAW_H = 4, 4


def new_frame():
    """Create a new 64x64 image with background color."""
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def draw_rect(draw, x, y, w, h, color):
    """Draw a filled rectangle (x, y, width, height)."""
    draw.rectangle([x, y, x + w - 1, y + h - 1], fill=color)


def draw_clawd(draw, dx=0, dy=0, eye_dx=0, eye_dy=0, leg_h=LEG_H):
    """Draw the base Clawd sprite with optional offsets."""
    # Body
    draw_rect(draw, BODY["x"] + dx, BODY["y"] + dy, BODY["w"], BODY["h"], BODY_COLOR)

    # Left claw
    draw_rect(draw, CLAW_LEFT["x"] + dx, CLAW_LEFT["y"] + dy, CLAW_W, CLAW_H, BODY_COLOR)

    # Right claw
    draw_rect(draw, CLAW_RIGHT["x"] + dx, CLAW_RIGHT["y"] + dy, CLAW_W, CLAW_H, BODY_COLOR)

    # Legs
    for lx in LEG_POSITIONS:
        draw_rect(draw, lx + dx, LEG_Y + dy, LEG_W, leg_h, BODY_COLOR)

    # Eyes
    draw_rect(
        draw,
        EYES_LEFT["x"] + dx + eye_dx,
        EYES_LEFT["y"] + dy + eye_dy,
        EYE_SIZE,
        EYE_SIZE,
        EYE_COLOR,
    )
    draw_rect(
        draw,
        EYES_RIGHT["x"] + dx + eye_dx,
        EYES_RIGHT["y"] + dy + eye_dy,
        EYE_SIZE,
        EYE_SIZE,
        EYE_COLOR,
    )


def draw_exclamation(draw, dx=0):
    """Draw '!' alert mark above Clawd's head."""
    ex, ey = 32, 16
    # Stick (2x2)
    draw_rect(draw, ex, ey, 2, 2, ALERT_COLOR)
    # Dot (2x1, with 1px gap)
    draw_rect(draw, ex, ey + 3, 2, 1, ALERT_COLOR)


def draw_sparkles(draw, dy=0):
    """Draw sparkle crosses at body corners."""
    bx = BODY["x"]
    by = BODY["y"] + dy
    bx2 = bx + BODY["w"]
    by2 = by + BODY["h"]

    # Each sparkle is a small cross pattern
    sparkle_points = [
        # Top-left
        [(bx - 3, by - 1), (bx - 2, by - 2), (bx - 2, by), (bx - 1, by - 1)],
        # Top-right
        [(bx2 + 1, by - 1), (bx2 + 2, by - 2), (bx2 + 2, by), (bx2 + 3, by - 1)],
        # Bottom-left
        [(bx - 3, by2 + 1), (bx - 2, by2), (bx - 2, by2 + 2), (bx - 1, by2 + 1)],
        # Bottom-right
        [(bx2 + 1, by2 + 1), (bx2 + 2, by2), (bx2 + 2, by2 + 2), (bx2 + 3, by2 + 1)],
    ]

    for points in sparkle_points:
        for px, py in points:
            if 0 <= px < W and 0 <= py < H:
                draw.point((px, py), fill=SPARKLE_COLOR)


def generate_alert_frames():
    """Generate 6 frames for the alert animation."""
    frames = []

    # Frame 0: Neutral pose
    img, draw = new_frame()
    draw_clawd(draw)
    frames.append(img)

    # Frame 1: Eyes shift right 1px
    img, draw = new_frame()
    draw_clawd(draw, eye_dx=1)
    frames.append(img)

    # Frame 2: Body leans right 1px, eyes shifted
    img, draw = new_frame()
    draw_clawd(draw, dx=1, eye_dx=1)
    frames.append(img)

    # Frame 3: "!" appears above head
    img, draw = new_frame()
    draw_clawd(draw, dx=1, eye_dx=1)
    draw_exclamation(draw, dx=1)
    frames.append(img)

    # Frame 4: Hold alert pose
    img, draw = new_frame()
    draw_clawd(draw, dx=1, eye_dx=1)
    draw_exclamation(draw, dx=1)
    frames.append(img)

    # Frame 5: "!" fades, body still leaning
    img, draw = new_frame()
    draw_clawd(draw, dx=1, eye_dx=1)
    frames.append(img)

    return frames


def generate_happy_frames():
    """Generate 6 frames for the happy animation."""
    frames = []

    # Frame 0: Neutral pose
    img, draw = new_frame()
    draw_clawd(draw)
    frames.append(img)

    # Frame 1: Crouch (legs shorten by 2px)
    img, draw = new_frame()
    draw_clawd(draw, leg_h=3)
    frames.append(img)

    # Frame 2: Jump up 4px, legs extend
    img, draw = new_frame()
    draw_clawd(draw, dy=-4)
    frames.append(img)

    # Frame 3: Peak with sparkles
    img, draw = new_frame()
    draw_clawd(draw, dy=-4)
    draw_sparkles(draw, dy=-4)
    frames.append(img)

    # Frame 4: Coming down (body at +2px from normal = -2 offset)
    img, draw = new_frame()
    draw_clawd(draw, dy=-2)
    frames.append(img)

    # Frame 5: Landing (back to neutral)
    img, draw = new_frame()
    draw_clawd(draw)
    frames.append(img)

    return frames


def draw_sleeping_clawd(draw, dy=0):
    """Draw sleeping Clawd: wider/shorter body, dark color, closed eyes."""
    # Sleeping body: 30w x 14h, lower on canvas
    draw_rect(draw, 17, 27 + dy, 30, 14, BODY_DARK)
    # Leg stubs (barely visible)
    for lx in [20, 25, 35, 40]:
        draw_rect(draw, lx, 41 + dy, 2, 2, BODY_DARK)
    # Closed eyes: horizontal lines (2x1), dark gray
    draw_rect(draw, 24, 31 + dy, 2, 1, EYE_CLOSED)
    draw_rect(draw, 36, 31 + dy, 2, 1, EYE_CLOSED)


def draw_z(draw, x, y, color):
    """Draw a small 'z' character in 3x3 pixels."""
    # Top row
    draw_rect(draw, x, y, 3, 1, color)
    # Diagonal
    draw.point((x + 1, y + 1), fill=color)
    # Bottom row
    draw_rect(draw, x, y + 2, 3, 1, color)


def draw_question_mark(draw):
    """Draw '?' mark above Clawd's head (3x5 area)."""
    qx, qy = 31, 15
    # Top curve
    draw_rect(draw, qx, qy, 2, 1, ALERT_COLOR)
    draw.point((qx + 2, qy), fill=ALERT_COLOR)
    # Right side
    draw.point((qx + 2, qy + 1), fill=ALERT_COLOR)
    # Middle
    draw.point((qx + 1, qy + 2), fill=ALERT_COLOR)
    # Dot (after gap)
    draw.point((qx + 1, qy + 4), fill=ALERT_COLOR)


def draw_ble_icon(draw):
    """Draw 16x16 Bluetooth rune symbol."""
    c = BLE_COLOR
    # Vertical center line (col 8, rows 3-12)
    for y in range(3, 13):
        draw.point((8, y), fill=c)
    # Top-right arrow
    draw.point((9, 4), fill=c)
    draw.point((10, 5), fill=c)
    draw.point((9, 6), fill=c)
    # Bottom-right arrow
    draw.point((9, 9), fill=c)
    draw.point((10, 10), fill=c)
    draw.point((9, 11), fill=c)
    # Cross lines (left)
    draw.point((5, 9), fill=c)
    draw.point((6, 8), fill=c)
    draw.point((7, 7), fill=c)
    draw.point((5, 6), fill=c)
    draw.point((6, 7), fill=c)
    # Peaks
    draw.point((9, 3), fill=c)
    draw.point((9, 12), fill=c)


def generate_sleeping_frames():
    """Generate 6 frames for the sleeping animation."""
    frames = []

    # Frame 0: Curled up, eyes closed
    img, draw = new_frame()
    draw_sleeping_clawd(draw)
    frames.append(img)

    # Frame 1: Same pose, closed eyes
    img, draw = new_frame()
    draw_sleeping_clawd(draw)
    frames.append(img)

    # Frame 2: Breathe out (body +1px)
    img, draw = new_frame()
    draw_sleeping_clawd(draw, dy=1)
    frames.append(img)

    # Frame 3: Breathe in + "z" appears
    img, draw = new_frame()
    draw_sleeping_clawd(draw, dy=-1)
    draw_z(draw, 44, 23, Z_COLOR)
    frames.append(img)

    # Frame 4: "z" floats up, fading
    img, draw = new_frame()
    draw_sleeping_clawd(draw)
    draw_z(draw, 45, 21, Z_FADE)
    frames.append(img)

    # Frame 5: New small "z" starts near body
    img, draw = new_frame()
    draw_sleeping_clawd(draw)
    draw_z(draw, 44, 24, Z_COLOR)
    frames.append(img)

    return frames


def generate_disconnected_frames():
    """Generate 6 frames for the disconnected animation."""
    frames = []

    # Frame 0: Eyes looking up-right
    img, draw = new_frame()
    draw_clawd(draw, eye_dx=1, eye_dy=-1)
    frames.append(img)

    # Frame 1: Head tilts right 1px
    img, draw = new_frame()
    draw_clawd(draw, dx=1, eye_dx=1, eye_dy=-1)
    frames.append(img)

    # Frame 2: Eyes shift left
    img, draw = new_frame()
    draw_clawd(draw, eye_dx=-1)
    frames.append(img)

    # Frame 3: Eyes shift back right
    img, draw = new_frame()
    draw_clawd(draw, eye_dx=1, eye_dy=-1)
    frames.append(img)

    # Frame 4: "?" appears above head
    img, draw = new_frame()
    draw_clawd(draw, eye_dx=1, eye_dy=-1)
    draw_question_mark(draw)
    frames.append(img)

    # Frame 5: "?" fades, back to looking up-right
    img, draw = new_frame()
    draw_clawd(draw, eye_dx=1, eye_dy=-1)
    frames.append(img)

    return frames


def generate_ble_icon():
    """Generate 16x16 BLE icon."""
    img = Image.new("RGB", (16, 16), BG)
    draw = ImageDraw.Draw(img)
    draw_ble_icon(draw)
    return [img]


def save_frames(frames, output_dir):
    """Save frames as numbered PNG files."""
    os.makedirs(output_dir, exist_ok=True)
    for i, img in enumerate(frames):
        path = os.path.join(output_dir, f"frame_{i:02d}.png")
        img.save(path, "PNG")
        print(f"  Saved: {path}")


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    animations = [
        ("alert", generate_alert_frames),
        ("happy", generate_happy_frames),
        ("sleeping", generate_sleeping_frames),
        ("disconnected", generate_disconnected_frames),
        ("ble-icon", generate_ble_icon),
    ]

    for name, gen_fn in animations:
        print(f"Generating {name} frames...")
        frames = gen_fn()
        out_dir = os.path.join(script_dir, "exports", name)
        save_frames(frames, out_dir)
        print(f"  {len(frames)} frame(s) saved to {out_dir}\n")

    print("Done! Run png2rgb565.py to convert to C headers.")


if __name__ == "__main__":
    main()
