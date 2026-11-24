#!/usr/bin/env python3
"""Спинограф по произвольной форме: колесо катится вдоль кривой, перо рисует узор, результат в MP4.

Примеры:
  python3 spirograph.py --shape line --out line.mp4
  python3 spirograph.py --shape square --side outside --ring-teeth 96 --wheel-teeth 40 --out square.mp4
  python3 spirograph.py --points my_shape.csv --closed --side inside --out custom.mp4

Нужны numpy, Pillow и ffmpeg в PATH.
"""
import argparse
import colorsys
import csv
import json
import math
import subprocess
import sys
from fractions import Fraction

import numpy as np
from PIL import Image, ImageDraw


# ---------- формы (в условных единицах, примерно в квадрате [-1, 1]) ----------

def shape_points(name, n=1200):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    if name == "line":
        return np.array([[-1.0, 0.0], [1.0, 0.0]]), False
    if name == "circle":
        return np.c_[np.cos(t), np.sin(t)], True
    if name == "ellipse":
        return np.c_[1.0 * np.cos(t), 0.6 * np.sin(t)], True
    if name == "square":
        return np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], float), True
    if name == "triangle":
        a = np.pi / 2 + np.arange(3) * 2 * np.pi / 3
        return np.c_[np.cos(a), np.sin(a)], True
    if name == "blob":  # мягкий «трилистник» без острых вогнутых углов
        r = 1 + 0.15 * np.cos(3 * t)
        return np.c_[r * np.cos(t), r * np.sin(t)], True
    if name == "wave":  # открытая синусоида
        x = np.linspace(-1, 1, 400)
        return np.c_[x, 0.2 * np.sin(np.pi * x)], False
    raise ValueError(f"неизвестная форма: {name}")


def load_points(path):
    """CSV/TXT со столбцами x,y или JSON [[x,y], ...]. Ось y направлена вверх."""
    if path.endswith(".json"):
        pts = np.array(json.load(open(path)), float)
    else:
        rows = []
        for row in csv.reader(open(path), delimiter=None if False else ","):
            parts = [p for cell in row for p in cell.split()]
            try:
                rows.append([float(parts[0]), float(parts[1])])
            except (ValueError, IndexError):
                continue
        pts = np.array(rows, float)
    # нормируем в [-1, 1]
    c = (pts.max(0) + pts.min(0)) / 2
    s = (pts.max(0) - pts.min(0)).max() / 2
    return (pts - c) / s


# ---------- геометрия качения ----------

def polyline_length(v, closed):
    seg = np.diff(np.vstack([v, v[:1]]) if closed else v, axis=0)
    return np.linalg.norm(seg, axis=1).sum()


def roll(vertices, closed, side, r, pen, phase, laps, step):
    """Возвращает траектории центра колеса, контакта, угол колеса и пера.

    Колесо катится без проскальзывания. Если s — длина пройденного по форме пути,
    θ — угол касательной, σ = +1 (колесо слева от направления обхода) или −1 (справа),
    то центр C = P + σ·r·N, угол поворота колеса α = θ − σ·s/r.
    На выпуклых для колеса углах колесо поворачивается вокруг вершины (s не растёт).
    Открытая линия обходится «туда и обратно»: колесо огибает концы и едет по другой стороне.
    """
    v = np.asarray(vertices, float)
    if not closed:
        v = np.vstack([v, v[-2:0:-1]])  # туда и обратно как замкнутый контур
        sigma = 1.0
    else:
        area = 0.5 * np.sum(v[:, 0] * np.roll(v[:, 1], -1) - np.roll(v[:, 0], -1) * v[:, 1])
        ccw = area > 0
        inside_is_left = ccw
        sigma = 1.0 if (side == "inside") == inside_is_left else -1.0

    nv = len(v)
    seg_dir = np.roll(v, -1, axis=0) - v
    seg_len = np.linalg.norm(seg_dir, axis=1)
    keep = seg_len > 1e-12
    v, seg_dir, seg_len = v[keep], seg_dir[keep], seg_len[keep]
    nv = len(v)
    seg_ang = np.arctan2(seg_dir[:, 1], seg_dir[:, 0])

    P, TH, S = [], [], []
    s_acc = 0.0
    th = seg_ang[0]
    for lap in range(laps):
        for i in range(nv):
            # отрезок i: от v[i] до v[i+1]
            n = max(1, int(math.ceil(seg_len[i] / step)))
            f = np.arange(n) / n
            P.append(v[i] + f[:, None] * seg_dir[i])
            TH.append(np.full(n, th))
            S.append(s_acc + f * seg_len[i])
            s_acc += seg_len[i]
            # поворот в вершине i+1
            nxt = seg_ang[(i + 1) % nv]
            d = (nxt - seg_ang[i] + np.pi) % (2 * np.pi) - np.pi
            if abs(abs(d) - np.pi) < 1e-9:  # разворот на конце линии — огибаем снаружи
                d = -sigma * np.pi
            if sigma * d < 0:  # выпуклый для колеса угол: поворот вокруг вершины
                m = max(1, int(math.ceil(abs(d) * r / step)))
                g = np.arange(1, m + 1) / m
                P.append(np.repeat(v[(i + 1) % nv][None], m, axis=0))
                TH.append(th + g * d)
                S.append(np.full(m, s_acc))
            th += d
    P = np.vstack(P + [v[:1]])
    TH = np.concatenate(TH + [[th]])
    S = np.concatenate(S + [[s_acc]])

    N = np.c_[-np.sin(TH), np.cos(TH)]
    C = P + sigma * r * N
    alpha = TH - sigma * S / r + phase
    pen_xy = C + pen * r * np.c_[np.cos(alpha), np.sin(alpha)]
    return C, P, alpha, pen_xy, sigma


def check_curvature(vertices, closed, sigma, r):
    """Предупреждение, если в гладкой вогнутой части кривизна слишком велика для колеса."""
    v = np.asarray(vertices, float)
    if len(v) < 5:
        return
    a, b, c = (np.roll(v, 1, 0), v, np.roll(v, -1, 0)) if closed else (v[:-2], v[1:-1], v[2:])
    ab, bc = b - a, c - b
    cross = ab[:, 0] * bc[:, 1] - ab[:, 1] * bc[:, 0]
    l = np.linalg.norm(ab, axis=1) * np.linalg.norm(bc, axis=1) * np.linalg.norm(c - a, axis=1)
    k = 2 * cross / np.maximum(l, 1e-12)  # знаковая кривизна (+ = поворот влево)
    bad = (np.abs(k) if not closed else sigma * k) > 1.0 / r * 1.02
    if np.any(bad):
        print("ВНИМАНИЕ: в некоторых местах форма изогнута сильнее радиуса колеса — "
              "колесо там «проваливается». Уменьшите колесо.", file=sys.stderr)


# ---------- рендер ----------

def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def render(args):
    if args.points:
        verts, closed = load_points(args.points), args.closed
    else:
        verts, closed = shape_points(args.shape)
        if args.shape in ("line", "wave"):
            closed = False

    L = polyline_length(verts if closed else np.vstack([verts, verts[-2::-1]]), True if closed else False)
    if not closed:
        L = 2 * polyline_length(verts, False)

    # радиус колеса: по «зубцам» (как в настоящем спирографе) или напрямую
    if args.wheel_radius:
        r = args.wheel_radius
        ratio = Fraction(L / (2 * np.pi * r)).limit_denominator(40)
        laps = args.laps or ratio.denominator
    else:
        R, w = args.ring_teeth, args.wheel_teeth
        r = L * w / (2 * np.pi * R)
        laps = args.laps or w // math.gcd(R, w)
    pen = args.pen
    phase = math.radians(args.phase)

    step = r / 60
    C, P, alpha, pen_xy, sigma = roll(verts, closed, args.side, r, pen, phase, laps, step)
    check_curvature(verts, closed, sigma, r)

    # кадрирование
    pts = np.vstack([verts, C + r, C - r, pen_xy])
    lo, hi = pts.min(0), pts.max(0)
    W = args.size
    SS = 2  # суперсэмплинг для сглаживания
    margin = 0.07
    scale = (1 - 2 * margin) * W / (hi - lo).max()
    ctr = (hi + lo) / 2

    def to_px(xy, k=SS):
        xy = np.atleast_2d(xy)
        x = (xy[:, 0] - ctr[0]) * scale + W / 2
        y = W / 2 - (xy[:, 1] - ctr[1]) * scale
        return np.c_[x, y] * k

    bg = hex2rgb(args.bg)
    WS = W * SS
    canvas = Image.new("RGB", (WS, WS), bg)
    dr = ImageDraw.Draw(canvas)

    # форма — «линейка/кольцо», по которой катится колесо
    sp = to_px(verts)
    track_w = max(2, int(0.006 * WS))
    poly = [tuple(p) for p in sp] + ([tuple(sp[0])] if closed else [])
    dr.line(poly, fill=hex2rgb(args.shape_color), width=track_w, joint="curve")

    # время ∝ пути центра колеса — движение с постоянной скоростью
    u = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))])
    nframes = int(args.duration * args.fps)
    idx_at = np.searchsorted(u, np.linspace(0, u[-1], nframes + 1)[1:], side="right") - 1
    idx_at[-1] = len(u) - 1

    pen_px = to_px(pen_xy)
    line_w = max(1, int(args.line_width * SS))
    total = len(pen_px)

    def color_at(frac):
        if args.palette == "rainbow":
            rr, gg, bb = colorsys.hsv_to_rgb((args.hue0 + frac) % 1.0, 0.75, 1.0)
            return int(rr * 255), int(gg * 255), int(bb * 255)
        return hex2rgb(args.palette)

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{W}", "-r", str(args.fps), "-i", "-",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium", args.out]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    wheel_rgb = hex2rgb(args.wheel_color)
    rp = r * scale * SS
    prev = 0
    for f in range(nframes):
        cur = int(idx_at[f])
        if cur > prev:
            seg = [tuple(p) for p in pen_px[prev:cur + 1]]
            dr.line(seg, fill=color_at(cur / total), width=line_w, joint="curve")
            prev = cur

        frame = canvas.copy()
        # колесо рисуем на маленьком RGBA-слое и накладываем с прозрачностью
        cx, cy = to_px(C[cur])[0]
        pad = int(rp + 6 * SS)
        x0, y0 = int(cx) - pad, int(cy) - pad
        box = (x0, y0, x0 + 2 * pad, y0 + 2 * pad)
        region = frame.crop(box).convert("RGBA")
        ov = Image.new("RGBA", region.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        lx, ly = cx - x0, cy - y0
        od.ellipse([lx - rp, ly - rp, lx + rp, ly + rp], fill=wheel_rgb + (40,),
                   outline=wheel_rgb + (200,), width=max(2, int(0.003 * WS)))
        a = alpha[cur]
        # зубцы по ободу
        nt = args.wheel_teeth if not args.wheel_radius else 48
        for k in range(nt):
            t = a + 2 * np.pi * k / nt
            c_, s_ = math.cos(t), -math.sin(t)
            od.line([(lx + c_ * rp * 0.93, ly + s_ * rp * 0.93), (lx + c_ * rp, ly + s_ * rp)],
                    fill=wheel_rgb + (150,), width=max(1, SS))
        # отверстия на «спице» и перо
        for q in np.linspace(0.2, 0.9, 6):
            hx, hy = lx + math.cos(a) * q * rp, ly - math.sin(a) * q * rp
            hr = 0.03 * rp
            od.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], outline=wheel_rgb + (120,), width=SS)
        px, py = lx + math.cos(a) * pen * rp, ly - math.sin(a) * pen * rp
        od.line([(lx, ly), (px, py)], fill=wheel_rgb + (110,), width=max(1, SS))
        od.ellipse([lx - 0.04 * rp, ly - 0.04 * rp, lx + 0.04 * rp, ly + 0.04 * rp], fill=wheel_rgb + (200,))
        pr = max(4 * SS, 0.05 * rp)
        od.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(255, 255, 255, 255),
                   outline=color_at(cur / total) + (255,), width=2 * SS)
        region = Image.alpha_composite(region, ov).convert("RGB")
        frame.paste(region, box)

        ff.stdin.write(frame.resize((W, W), Image.LANCZOS).tobytes())

    final = canvas.resize((W, W), Image.LANCZOS).tobytes()
    for _ in range(int(args.hold * args.fps)):
        ff.stdin.write(final)
    ff.stdin.close()
    ff.wait()
    canvas.resize((W, W), Image.LANCZOS).save(args.out.rsplit(".", 1)[0] + ".png")
    print(f"готово: {args.out}  (радиус колеса {r:.3f}, перо {pen:.2f}·r, кругов {laps}, кадров {nframes})")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--shape", default="circle",
                   choices=["line", "wave", "circle", "ellipse", "square", "triangle", "blob"])
    p.add_argument("--points", help="свой контур: CSV/TXT (x,y по строкам) или JSON [[x,y],...]")
    p.add_argument("--closed", action="store_true", help="контур из --points замкнут")
    p.add_argument("--side", default="inside", choices=["inside", "outside"],
                   help="колесо внутри или снаружи замкнутой формы (для линии игнорируется)")
    p.add_argument("--ring-teeth", type=int, default=96, help="«зубцов» на всей форме")
    p.add_argument("--wheel-teeth", type=int, default=40, help="зубцов на колесе")
    p.add_argument("--wheel-radius", type=float, help="радиус колеса напрямую (форма ~ в [-1,1])")
    p.add_argument("--pen", type=float, default=0.85, help="расстояние пера от центра, доля радиуса")
    p.add_argument("--phase", type=float, default=0, help="начальный угол пера, градусы")
    p.add_argument("--laps", type=int, help="сколько раз обойти форму (по умолчанию — до замыкания узора)")
    p.add_argument("--duration", type=float, default=20, help="длительность рисования, с")
    p.add_argument("--hold", type=float, default=2.5, help="пауза на готовом узоре в конце, с")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--size", type=int, default=1080)
    p.add_argument("--bg", default="#0e1116")
    p.add_argument("--shape-color", default="#3a4250")
    p.add_argument("--wheel-color", default="#9ec9ff")
    p.add_argument("--palette", default="rainbow", help="'rainbow' или цвет вида #ff8800")
    p.add_argument("--hue0", type=float, default=0.55, help="стартовый оттенок радуги 0..1")
    p.add_argument("--line-width", type=float, default=1.6)
    p.add_argument("--out", default="spirograph.mp4")
    render(p.parse_args())


if __name__ == "__main__":
    main()
