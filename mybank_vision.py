#!/usr/bin/env python3
"""
MyBank - Vision module (hackathon proof of concept)

What it does
  1. Reads a QR code / barcode to get a DEMO unit ID.
  2. Runs image-quality checks (blur, brightness, glare).
  3. Compares a test image against a reference image of a TRAINING bag
     and reports a "visual difference" percentage.
  4. Logs every result to a CSV file with a timestamp.

What it does NOT do
  It does not detect clots or hemolysis and does not decide whether blood is
  safe. Output wording is intentionally limited to
  "visual difference flagged - human review required".
  Use training bags / test images only, never real human blood.

Usage examples
  Live camera:    python mybank_vision.py --camera 0
  Single images:  python mybank_vision.py --reference ref.jpg --image test.jpg
  With ROI:       python mybank_vision.py --camera 0 --roi 200,100,300,400

Live-mode keys
  r = save current frame as REFERENCE     SPACE = analyze current frame
  s = scan QR/barcode for unit ID         q = quit
"""

import argparse
import csv
import os
import sys
from datetime import datetime

import cv2
import numpy as np

# ----------------------------- configuration ------------------------------
BLUR_MIN = 60.0          # Laplacian variance below this = too blurry
BRIGHT_MIN, BRIGHT_MAX = 60, 210   # mean gray level range
GLARE_MAX_PCT = 2.0      # % of near-white pixels allowed
PIXEL_DELTA_THR = 25.0   # LAB color distance for a pixel to count as "changed"
DIFF_FLAG_PCT = 5.0      # % changed pixels needed to flag for human review
DEFAULT_LOG = "mybank_log.csv"
REF_PATH = "reference.jpg"
WORK_SIZE = (640, 480)


# ------------------------------- helpers ---------------------------------
def parse_roi(text):
    if not text:
        return None
    try:
        x, y, w, h = [int(v) for v in text.split(",")]
        return x, y, w, h
    except ValueError:
        sys.exit("--roi must look like x,y,w,h (e.g. 200,100,300,400)")


def crop_roi(img, roi):
    if roi is None:
        return img
    x, y, w, h = roi
    return img[y:y + h, x:x + w]


def prepare(img, roi=None):
    """Crop to ROI, resize to a fixed size, light blur to reduce sensor noise."""
    img = crop_roi(img, roi)
    img = cv2.resize(img, WORK_SIZE, interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(img, (5, 5), 0)


# ---------------------------- QR / barcode -------------------------------
def decode_codes(frame):
    """Return a list of (type, text) found in the frame. Tries QR, then 1D barcodes."""
    found = []

    qr = cv2.QRCodeDetector()
    try:
        text, _, _ = qr.detectAndDecode(frame)
        if text:
            found.append(("QR", text))
    except cv2.error:
        pass

    # 1D barcodes need OpenCV >= 4.8 (cv2.barcode). Fails gracefully if missing.
    if hasattr(cv2, "barcode"):
        try:
            bd = cv2.barcode.BarcodeDetector()
            res = bd.detectAndDecode(frame)
            if len(res) == 4:                      # (ok, infos, types, points)
                ok, infos, types, _ = res
                if ok:
                    for info, typ in zip(infos, types):
                        if info:
                            found.append((str(typ) or "BARCODE", info))
        except cv2.error:
            pass
    return found


def get_unit_id(frame, fallback):
    codes = decode_codes(frame)
    if codes:
        return codes[0][1], codes[0][0]
    return fallback, "manual"


# ---------------------------- image quality ------------------------------
def quality_check(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    bright = float(gray.mean())
    glare = float((gray > 245).mean() * 100)

    problems = []
    if blur < BLUR_MIN:
        problems.append("blurry")
    if bright < BRIGHT_MIN:
        problems.append("too dark")
    if bright > BRIGHT_MAX:
        problems.append("too bright")
    if glare > GLARE_MAX_PCT:
        problems.append("glare/reflection")

    return {
        "blur": round(blur, 1),
        "brightness": round(bright, 1),
        "glare_pct": round(glare, 2),
        "ok": not problems,
        "problems": problems,
    }


# -------------------------- visual difference ----------------------------
def visual_difference(ref, test):
    """
    Compare test vs reference in LAB color space.
    Brightness is matched first so small lighting changes matter less.
    Returns (changed_pct, mean_delta, heatmap_image).
    """
    ref_lab = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB).astype(np.float32)
    test_lab = cv2.cvtColor(test, cv2.COLOR_BGR2LAB).astype(np.float32)

    # match overall lightness (L channel) to reduce lighting influence
    test_lab[:, :, 0] += ref_lab[:, :, 0].mean() - test_lab[:, :, 0].mean()

    delta = np.linalg.norm(ref_lab - test_lab, axis=2)
    mask = (delta > PIXEL_DELTA_THR).astype(np.uint8) * 255
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)   # drop speckle noise

    changed_pct = float((mask > 0).mean() * 100)
    mean_delta = float(delta.mean())

    heat = cv2.applyColorMap(
        np.clip(delta * 4, 0, 255).astype(np.uint8), cv2.COLORMAP_JET
    )
    return changed_pct, mean_delta, heat


def analyze(ref_img, test_img, roi=None):
    ref = prepare(ref_img, roi)
    test = prepare(test_img, roi)

    q = quality_check(test)
    changed_pct, mean_delta, heat = visual_difference(ref, test)

    if not q["ok"]:
        status = "RETAKE IMAGE (" + ", ".join(q["problems"]) + ")"
    elif changed_pct >= DIFF_FLAG_PCT:
        status = "Visual difference flagged - human review required"
    else:
        status = "No large visual difference vs reference"

    return {
        "status": status,
        "changed_pct": round(changed_pct, 2),
        "mean_delta": round(mean_delta, 2),
        "quality": q,
        "heatmap": heat,
        "test_prepared": test,
    }


# -------------------------------- logging --------------------------------
LOG_FIELDS = [
    "timestamp", "unit_id", "id_source", "status", "changed_pct",
    "mean_delta", "blur", "brightness", "glare_pct", "image_file",
]


def log_result(path, unit_id, id_source, result, image_file):
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "unit_id": unit_id,
            "id_source": id_source,
            "status": result["status"],
            "changed_pct": result["changed_pct"],
            "mean_delta": result["mean_delta"],
            "blur": result["quality"]["blur"],
            "brightness": result["quality"]["brightness"],
            "glare_pct": result["quality"]["glare_pct"],
            "image_file": image_file,
        })


def save_capture(img, unit_id):
    os.makedirs("captures", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_id = "".join(c for c in unit_id if c.isalnum() or c in "-_")[:40] or "unit"
    path = os.path.join("captures", f"{safe_id}_{stamp}.jpg")
    cv2.imwrite(path, img)
    return path


def draw_text(img, lines, color=(255, 255, 255)):
    y = 25
    for line in lines:
        cv2.putText(img, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    color, 1, cv2.LINE_AA)
        y += 24


# ------------------------------- run modes -------------------------------
def run_files(args):
    ref = cv2.imread(args.reference)
    test = cv2.imread(args.image)
    if ref is None or test is None:
        sys.exit("Could not read --reference or --image file.")

    roi = parse_roi(args.roi)
    unit_id, src = get_unit_id(test, args.unit_id)
    result = analyze(ref, test, roi)
    log_result(args.log, unit_id, src, result, args.image)

    print(f"Unit ID     : {unit_id} ({src})")
    print(f"Status      : {result['status']}")
    print(f"Changed px  : {result['changed_pct']}%")
    print(f"Quality     : {result['quality']}")
    out = "diff_heatmap.jpg"
    cv2.imwrite(out, result["heatmap"])
    print(f"Heatmap saved to {out}. Logged to {args.log}")


def run_live(args):
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        sys.exit(f"Cannot open camera {args.camera}. Try --camera 1.")

    roi = parse_roi(args.roi)
    ref = cv2.imread(REF_PATH) if os.path.exists(REF_PATH) else None
    unit_id, src = args.unit_id, "manual"
    last = ["Press r = set reference, SPACE = analyze, s = scan code, q = quit"]

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Camera read failed.")
            break

        view = frame.copy()
        if roi:
            x, y, w, h = roi
            cv2.rectangle(view, (x, y), (x + w, y + h), (255, 200, 0), 2)
        draw_text(view, [f"Unit: {unit_id} ({src})",
                         f"Reference: {'loaded' if ref is not None else 'NOT SET'}"]
                  + last)
        cv2.imshow("MyBank - vision demo (not a medical device)", view)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("r"):
            ref = frame.copy()
            cv2.imwrite(REF_PATH, ref)
            last = ["Reference saved."]
        elif key == ord("s"):
            codes = decode_codes(frame)
            if codes:
                unit_id, src = codes[0][1], codes[0][0]
                last = [f"Scanned {src}: {unit_id}"]
            else:
                last = ["No QR/barcode found. Hold it closer, avoid glare."]
        elif key == ord(" "):
            if ref is None:
                last = ["Set a reference first (press r)."]
                continue
            result = analyze(ref, frame, roi)
            path = save_capture(frame, unit_id)
            log_result(args.log, unit_id, src, result, path)
            last = [result["status"],
                    f"Changed: {result['changed_pct']}%  "
                    f"blur={result['quality']['blur']} "
                    f"bright={result['quality']['brightness']}"]
            cv2.imshow("Difference heatmap", result["heatmap"])

    cap.release()
    cv2.destroyAllWindows()


def main():
    p = argparse.ArgumentParser(description="MyBank vision demo (not a medical device)")
    p.add_argument("--camera", type=int, default=0, help="camera index for live mode")
    p.add_argument("--reference", help="reference image (file mode)")
    p.add_argument("--image", help="test image (file mode)")
    p.add_argument("--roi", help="region of interest x,y,w,h around the bag")
    p.add_argument("--unit-id", default="DEMO-001", help="fallback unit ID if no code is scanned")
    p.add_argument("--log", default=DEFAULT_LOG, help="CSV log path")
    args = p.parse_args()

    if args.reference and args.image:
        run_files(args)
    else:
        run_live(args)


if __name__ == "__main__":
    main()
