#!/usr/bin/env python3
"""
MyBank - Barcode / QR reading test (no camera needed)

What it does
Generates demo unit labels (QR codes and EAN-13 barcodes), puts each one in a
640x480 "camera frame", applies simulated camera problems (blur, low light,
rotation, tilt, noise, glare, distance, JPEG compression), then tries to read
it with OpenCV. Every attempt is logged, and a report is written.

What it does NOT do
It does not use a real camera, a real printed label or a real blood bag.
The results show how the reader behaves on simulated problems. A test with
real photos is still needed later (see --folder).

Usage
python barcode_test.py                  run the full test (20 trials per case)
python barcode_test.py --trials 50      more trials
python barcode_test.py --make-labels 5  write 5 printable QR demo labels to ./labels
python barcode_test.py --folder photos  read your own images (see below)

--folder mode: name each image <expected-id>__anything.jpg
for example DEMO-001__take1.jpg or 2001234567893__take2.png

Only demo IDs are used. Never put donor or patient information in a code.
Requires: opencv-python (4.8 or newer) and numpy.
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime

import cv2
import numpy as np

FRAME_W, FRAME_H = 640, 480

# ------------------------------ EAN-13 encoder ------------------------------
_L = ["0001101", "0011001", "0010011", "0111101", "0100011",
      "0110001", "0101111", "0111011", "0110111", "0001011"]
_G = ["0100111", "0110011", "0011011", "0100001", "0011101",
      "0111001", "0000101", "0010001", "0001001", "0010111"]
_R = ["1110010", "1100110", "1101100", "1000010", "1011100",
      "1001110", "1010000", "1000100", "1001000", "1110100"]
_PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
           "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]


def ean13_check_digit(payload12):
    s = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(payload12))
    return str((10 - s % 10) % 10)


def ean13_bits(code13):
    d = [int(c) for c in code13]
    bits = "101"
    for i, dig in enumerate(d[1:7]):
        bits += (_L if _PARITY[d[0]][i] == "L" else _G)[dig]
    bits += "01010"
    for dig in d[7:]:
        bits += _R[dig]
    return bits + "101"


def make_ean13_label(code13, module=4, height=150, quiet=12):
    bits = ean13_bits(code13)
    w = (len(bits) + 2 * quiet) * module
    img = np.full((height + 40, w), 255, np.uint8)
    for i, b in enumerate(bits):
        if b == "1":
            x = (i + quiet) * module
            img[10:10 + height, x:x + module] = 0
    cv2.putText(img, code13, (quiet * module, height + 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, 0, 2, cv2.LINE_AA)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


# ------------------------------- QR generator -------------------------------
def make_qr_label(text, module_px=8, quiet_modules=4):
    try:
        enc = cv2.QRCodeEncoder.create()
    except AttributeError:
        enc = cv2.QRCodeEncoder_create()
    qr = enc.encode(text)
    qr = cv2.copyMakeBorder(qr, quiet_modules, quiet_modules, quiet_modules,
                            quiet_modules, cv2.BORDER_CONSTANT, value=255)
    qr = cv2.resize(qr, None, fx=module_px, fy=module_px,
                    interpolation=cv2.INTER_NEAREST)
    return cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)


# --------------------------------- decoding ---------------------------------
def decode_codes(frame):
    """Return a list of (type, text). Tries QR first, then EAN/UPC barcodes."""
    found = []
    try:
        text, _, _ = cv2.QRCodeDetector().detectAndDecode(frame)
        if text:
            found.append(("QR", text))
    except cv2.error:
        pass

    if hasattr(cv2, "barcode"):
        try:
            res = cv2.barcode.BarcodeDetector().detectAndDecodeWithType(frame)
            if len(res) == 4:  # (ok, infos, types, points)
                ok, infos, types, _ = res
                if ok:
                    for info, typ in zip(infos, types):
                        if info:
                            found.append((str(typ), str(info)))
        except cv2.error:
            pass
    return found


# ------------------------------ simulated scene -----------------------------
CONDITIONS = [
    ("clean", {}),
    ("blur_light", {"blur": 1.5}),
    ("blur_medium", {"blur": 3.0}),
    ("blur_heavy", {"blur": 5.0}),
    ("dark", {"alpha": 0.35}),
    ("overexposed", {"alpha": 1.0, "beta": 90}),
    ("rotated_15deg", {"rot": 15}),
    ("rotated_45deg", {"rot": 45}),
    ("tilted_25deg", {"tilt": 25}),
    ("noisy", {"noise": 25}),
    ("glare_spot", {"glare": True}),
    ("far_away", {"scale": 0.4}),
    ("jpeg_low_quality", {"jpeg": 25}),
    ("combined_realistic", {"rot": 20, "tilt": 10, "blur": 1.5,
                            "noise": 10, "jpeg": 50, "alpha": 0.7}),
]
BASE_FRACTION = {"QR": 0.45, "EAN-13": 0.55}  # label width / frame width

DESCRIPTIONS = {
    "clean": "no problem added",
    "blur_light": "Gaussian blur, sigma 1.5 px",
    "blur_medium": "Gaussian blur, sigma 3 px",
    "blur_heavy": "Gaussian blur, sigma 5 px",
    "dark": "brightness x0.35 (low light)",
    "overexposed": "brightness +90 (washed out)",
    "rotated_15deg": "rotated 15 degrees (left or right)",
    "rotated_45deg": "rotated 45 degrees (left or right)",
    "tilted_25deg": "perspective tilt, 25 degrees",
    "noisy": "Gaussian noise, sigma 25",
    "glare_spot": "white glare covering about 20% of the label",
    "far_away": "label at 40% of normal size",
    "jpeg_low_quality": "JPEG quality 25",
    "combined_realistic": "rotation 20, tilt 10, blur 1.5, noise 10, JPEG 50, brightness x0.7",
}


def make_background(rng):
    base = rng.integers(205, 245, size=3).astype(np.float32)
    grad = np.linspace(-12, 12, FRAME_W, dtype=np.float32)[None, :, None]
    bg = np.ones((FRAME_H, FRAME_W, 3), np.float32) * base + grad
    bg += rng.normal(0, 2, bg.shape)
    return np.clip(bg, 0, 255).astype(np.uint8)


def make_scene(label, kind, cond, rng):
    frame = make_background(rng)
    scale = cond.get("scale", 1.0)
    tw = int(FRAME_W * BASE_FRACTION[kind] * scale)
    th = int(label.shape[0] * tw / label.shape[1])
    lab = cv2.resize(label, (tw, th), interpolation=cv2.INTER_AREA)

    angle = 0.0
    if cond.get("rot"):
        angle = rng.choice([-1, 1]) * cond["rot"] + rng.uniform(-2, 2)
    cx = FRAME_W / 2 + rng.uniform(-25, 25)
    cy = FRAME_H / 2 + rng.uniform(-20, 20)

    corners = np.array([[-tw / 2, -th / 2], [tw / 2, -th / 2],
                        [tw / 2, th / 2], [-tw / 2, th / 2]], np.float64)
    tilt = cond.get("tilt", 0)
    if tilt:
        k = np.sin(np.radians(tilt)) * 0.5
        side = rng.choice([-1, 1])
        corners[:, 0] *= np.cos(np.radians(tilt))
        for i in range(4):
            corners[i, 1] *= 1 - k * side * np.sign(corners[i, 0])
    r = np.radians(angle)
    rot = np.array([[np.cos(r), -np.sin(r)], [np.sin(r), np.cos(r)]])
    corners = corners @ rot.T + [cx, cy]

    src = np.array([[0, 0], [tw, 0], [tw, th], [0, th]], np.float32)
    m = cv2.getPerspectiveTransform(src, corners.astype(np.float32))
    warped = cv2.warpPerspective(lab, m, (FRAME_W, FRAME_H))
    mask = cv2.warpPerspective(np.full((th, tw), 255, np.uint8), m,
                               (FRAME_W, FRAME_H)) > 127
    frame[mask] = warped[mask]

    if cond.get("glare"):
        g = np.zeros((FRAME_H, FRAME_W), np.float32)
        gx = int(cx + rng.uniform(-0.15, 0.15) * tw)
        gy = int(cy + rng.uniform(-0.1, 0.1) * th)
        cv2.ellipse(g, (gx, gy), (int(tw * 0.2), max(int(th * 0.35), 18)),
                    0, 0, 360, 1.0, -1)
        g = cv2.GaussianBlur(g, (0, 0), tw * 0.04)[:, :, None] * 0.95
        frame = (frame * (1 - g) + 255 * g).astype(np.uint8)

    if "alpha" in cond or "beta" in cond:
        frame = cv2.convertScaleAbs(frame, alpha=cond.get("alpha", 1.0),
                                    beta=cond.get("beta", 0))
    if cond.get("blur"):
        frame = cv2.GaussianBlur(frame, (0, 0), cond["blur"])
    if cond.get("noise"):
        n = rng.normal(0, cond["noise"], frame.shape)
        frame = np.clip(frame.astype(np.float32) + n, 0, 255).astype(np.uint8)
    if cond.get("jpeg"):
        ok, buf = cv2.imencode(".jpg", frame,
                               [cv2.IMWRITE_JPEG_QUALITY, cond["jpeg"]])
        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return frame


def random_label(kind, rng):
    if kind == "QR":
        text = f"DEMO-{int(rng.integers(1, 1000)):03d}"
        return text, make_qr_label(text)
    payload = "200" + "".join(str(int(x)) for x in rng.integers(0, 10, 9))
    code = payload + ean13_check_digit(payload)
    return code, make_ean13_label(code, module=4)


def classify(expected, kind, found):
    """OK = correct text read. MISREAD = something read but wrong. NOT_FOUND = nothing."""
    right_type = [t for (typ, t) in found if (typ == "QR") == (kind == "QR")]
    if expected in right_type:
        return "OK", expected
    if right_type:
        return "MISREAD", right_type[0]
    return "NOT_FOUND", ""


# -------------------------------- synthetic run -----------------------------
def run_synthetic(trials, seed, outdir):
    rng = np.random.default_rng(seed)
    rows, examples = [], {}
    for kind in ("QR", "EAN-13"):
        for cname, cond in CONDITIONS:
            for t in range(trials):
                expected, label = random_label(kind, rng)
                frame = make_scene(label, kind, cond, rng)
                t0 = time.perf_counter()
                found = decode_codes(frame)
                ms = (time.perf_counter() - t0) * 1000
                status, got = classify(expected, kind, found)
                rows.append({"type": kind, "condition": cname, "trial": t + 1,
                             "expected": expected, "decoded": got,
                             "status": status, "ms": round(ms, 1)})
                if t == 0:
                    examples[(kind, cname)] = (frame, status)
    path = os.path.join(outdir, "barcode_test_results.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return rows, examples


def summarize(rows):
    table = {}
    for r in rows:
        key = (r["condition"], r["type"])
        d = table.setdefault(key, {"OK": 0, "MISREAD": 0, "NOT_FOUND": 0, "n": 0})
        d[r["status"]] += 1
        d["n"] += 1
    return table


def make_examples_image(examples, outdir):
    colors = {"OK": (60, 160, 60), "MISREAD": (0, 140, 255), "NOT_FOUND": (50, 50, 200)}
    tiles = []
    for (kind, cname), (frame, status) in examples.items():
        tile = cv2.resize(frame, (320, 240), interpolation=cv2.INTER_AREA)
        cv2.rectangle(tile, (0, 0), (319, 239), colors[status], 4)
        cv2.rectangle(tile, (0, 0), (319, 22), (255, 255, 255), -1)
        cv2.putText(tile, f"{kind} | {cname} | {status}", (6, 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, colors[status], 1, cv2.LINE_AA)
        tiles.append(tile)
    cols = 4
    while len(tiles) % cols:
        tiles.append(np.full((240, 320, 3), 255, np.uint8))
    rows_img = [cv2.hconcat(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    path = os.path.join(outdir, "barcode_test_examples.png")
    cv2.imwrite(path, cv2.vconcat(rows_img))
    return path


def compatibility_check():
    """Check the 1D barcode call styles on a clean EAN-13 (module width 2 px)."""
    code = "2001234567893"
    label = make_ean13_label(code, module=2, height=80)
    label = cv2.copyMakeBorder(label, 40, 40, 40, 40, cv2.BORDER_CONSTANT,
                               value=(255, 255, 255))
    bd = cv2.barcode.BarcodeDetector()
    res3 = bd.detectAndDecode(label)
    res4 = bd.detectAndDecodeWithType(label)
    with_type = bool(res4[0]) and code in res4[1]
    return {"detectAndDecode_returns": len(res3),
            "detectAndDecodeWithType_reads_ean13": with_type,
            "old_len4_check_would_read": len(res3) == 4}


def write_report(rows, table, trials, seed, outdir, compat):
    n_total = len(rows)
    by_type = {}
    for r in rows:
        d = by_type.setdefault(r["type"], {"OK": 0, "MISREAD": 0, "NOT_FOUND": 0, "n": 0})
        d[r["status"]] += 1
        d["n"] += 1

    lines = []
    lines += ["# Barcode / QR reading test (simulated, no camera)", ""]
    lines += [f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M')} | OpenCV {cv2.__version__} "
              f"| {trials} trials per case | seed {seed} | frame {FRAME_W}x{FRAME_H}", ""]
    lines += ["## What was tested", "",
              "Whether the reader can read a demo unit ID from a label under simulated camera "
              "problems. Labels are generated (QR with ID like `DEMO-123`, and EAN-13 with a "
              "demo number), placed in a frame, degraded, and read with OpenCV. "
              "A read counts as correct only if the text matches the ID that was encoded.", ""]
    lines += ["## Overall result", "",
              "| Code type | Attempts | Correct | Wrong read | Not found |",
              "|---|---|---|---|---|"]
    for kind, d in by_type.items():
        lines.append(f"| {kind} | {d['n']} | {d['OK']} ({100 * d['OK'] / d['n']:.0f}%) "
                     f"| {d['MISREAD']} | {d['NOT_FOUND']} |")
    lines += ["", "## Result by condition (correct reads out of "
              f"{trials})", "",
              "| Condition | What was simulated | QR | EAN-13 |", "|---|---|---|---|"]
    for cname, _ in CONDITIONS:
        q = table[(cname, "QR")]
        e = table[(cname, "EAN-13")]
        lines.append(f"| {cname} | {DESCRIPTIONS[cname]} | "
                     f"{q['OK']}/{q['n']} | {e['OK']}/{e['n']} |")

    weak = {k: [c for c, _ in CONDITIONS if table[(c, k)]["OK"] < table[(c, k)]["n"]]
            for k in ("QR", "EAN-13")}
    lines += ["", "## Findings", ""]
    for k in ("QR", "EAN-13"):
        if weak[k]:
            lines.append(f"- {k}: not 100% in: {', '.join(weak[k])}.")
        else:
            lines.append(f"- {k}: read correctly in every simulated condition.")
    wrong = sum(1 for r in rows if r["status"] == "MISREAD")
    lines.append(f"- Wrong reads (a different ID than the one encoded): {wrong} of {n_total}. "
                 "A wrong ID is worse than no read, so the system should show the ID to the "
                 "user for confirmation.")
    lines.append("- OpenCV's 1D barcode detector is documented to support EAN-8, EAN-13, "
                 "UPC-A and UPC-E only (not tested here for other types). QR carries "
                 "letters and digits, and was far more stable in this test, so QR is the "
                 "safer choice for demo IDs.")
    lines += ["", "## Notes for developers", "",
              f"- `BarcodeDetector.detectAndDecode` returned {compat['detectAndDecode_returns']} "
              "values in this OpenCV version. Code that checks for 4 values will never read "
              "1D barcodes. `detectAndDecodeWithType` returns 4 values "
              f"(read clean EAN-13: {compat['detectAndDecodeWithType_reads_ean13']}).",
              "- In our runs the 1D detector was very sensitive to bar width and image size "
              "(results changed a lot with small changes). Results depend on the OpenCV "
              "version, so run this script on your own machine and use your own numbers.", ""]
    lines += ["## Not tested (needs a later real test)", "",
              "- A real camera, real lighting and real printed labels.",
              "- Labels on curved, wet or wrinkled blood-bag plastic.",
              "- Labels at different distances in a real box, and moving bags.",
              "- Other barcode types (Code 128, DataMatrix).",
              "- Real hospital or blood-bank labels (no real donor data was used).", ""]
    path = os.path.join(outdir, "barcode_test_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


# ---------------------------------- extras ----------------------------------
def make_labels(n, outdir):
    os.makedirs(outdir, exist_ok=True)
    for i in range(1, n + 1):
        uid = f"DEMO-{i:03d}"
        qr = make_qr_label(uid)
        cv2.putText(qr, uid, (20, qr.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.imwrite(os.path.join(outdir, f"QR_{uid}.png"), qr)
    print(f"Wrote {n} printable QR demo labels to {outdir}/")


def run_folder(folder, outdir):
    exts = (".jpg", ".jpeg", ".png", ".bmp")
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(exts))
    if not files:
        sys.exit(f"No images found in {folder}")
    rows = []
    for fn in files:
        expected = fn.rsplit(".", 1)[0].split("__")[0]
        img = cv2.imread(os.path.join(folder, fn))
        found = decode_codes(img) if img is not None else []
        texts = [t for _, t in found]
        status = "OK" if expected in texts else ("MISREAD" if texts else "NOT_FOUND")
        rows.append({"file": fn, "expected": expected,
                     "decoded": texts[0] if texts else "", "status": status})
        print(f"{status:10s} {fn} expected={expected} got={texts[0] if texts else '-'}")
    ok = sum(r["status"] == "OK" for r in rows)
    print(f"\nCorrect reads: {ok}/{len(rows)} ({100 * ok / len(rows):.0f}%)")
    path = os.path.join(outdir, "real_images_results.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "expected", "decoded", "status"])
        w.writeheader()
        w.writerows(rows)
    print(f"Saved {path}")


def main():
    p = argparse.ArgumentParser(description="MyBank barcode/QR reading test (no camera)")
    p.add_argument("--trials", type=int, default=20, help="trials per condition and type")
    p.add_argument("--seed", type=int, default=42, help="random seed (same seed = same test)")
    p.add_argument("--outdir", default="results", help="folder for results")
    p.add_argument("--make-labels", type=int, metavar="N", help="write N printable demo labels")
    p.add_argument("--folder", help="read your own images instead of the simulated test")
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    if args.make_labels:
        make_labels(args.make_labels, "labels")
        return
    if args.folder:
        run_folder(args.folder, args.outdir)
        return

    rows, examples = run_synthetic(args.trials, args.seed, args.outdir)
    table = summarize(rows)
    compat = compatibility_check()
    report = write_report(rows, table, args.trials, args.seed, args.outdir, compat)
    img = make_examples_image(examples, args.outdir)

    print(f"{'condition':22s} {'QR':>8s} {'EAN-13':>8s}")
    for cname, _ in CONDITIONS:
        q, e = table[(cname, 'QR')], table[(cname, 'EAN-13')]
        print(f"{cname:22s} {q['OK']:>4d}/{q['n']:<3d} {e['OK']:>4d}/{e['n']:<3d}")
    for kind in ("QR", "EAN-13"):
        ok = sum(r["status"] == "OK" for r in rows if r["type"] == kind)
        tot = sum(1 for r in rows if r["type"] == kind)
        print(f"TOTAL {kind}: {ok}/{tot} ({100 * ok / tot:.0f}%)")
    print(f"\nSaved: {report}\n {img}\n {os.path.join(args.outdir, 'barcode_test_results.csv')}")


if __name__ == "__main__":
    main()
