# MyBank

**Smart Blood Bag Inspection & Cold-Chain Tracking System: Hackathon Proof of Concept**

> **Not a medical device.** This is an educational prototype built for a hackathon (Medathon). It uses a **training bag or test images only** and must **never** be used with real human blood or to decide whether blood is safe for transfusion. It does not diagnose clots or hemolysis.

---

## Overview

Blood banks need to document storage and transport conditions, flag unusual visual patterns for human review, and keep expiry and inventory information in one place. MyBank demonstrates how an inexpensive setup could support that workflow:

| Function | What the prototype demonstrates |
|---|---|
| Visual inspection | Captures an image under consistent lighting and flags visible color/shape differences versus a reference image |
| Cold-chain tracking | Reads enclosure temperature (ESP32 + DS18B20) and raises an alert when a **demo** threshold is crossed |
| Digital record | Links a demo unit ID (QR/barcode) to timestamp, inspection result and alerts |

The output is always worded as **"Visual difference flagged - human review required"**, never "clot detected".

## Repository structure

```
mybank/
├── mybank_vision.py   # OpenCV vision + QR/barcode + CSV logging
├── generate_qr.py      # Creates a QR label for a demo unit ID
├── requirements.txt    # Python dependencies
├── README.md
├── .gitignore
└── firmware/           # (add) ESP32 + DS18B20 Arduino sketch
```

## Hardware (low-cost prototype)

- ESP32 development board, breadboard, jumper wires, USB cable
- DS18B20 temperature sensor (with 4.7 kΩ pull-up resistor)
- LED + current-limiting resistor
- Transparent acrylic/plastic box (imaging chamber) holding a **training bag**
- White LED lamp/strip for consistent lighting
- Laptop + webcam or USB camera
- Optional printed QR label

Keep the ESP32 and breadboard **outside** the chamber on a dry base.

## Quick start

```bash
# 1. Clone
git clone https://github.com/<your-username>/mybank.git
cd mybank

# 2. (Recommended) virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install
pip install -r requirements.txt
```

### Make a QR label

```bash
python generate_qr.py DEMO-001
```

Print `qr_DEMO-001.png` and stick it on the training bag. Use a demo ID only, with no personal data.

### Run live with a camera

```bash
python mybank_vision.py --camera 0
```

| Key | Action |
|---|---|
| `r` | Save the current frame as the **reference** image |
| `s` | Scan QR/barcode to set the unit ID |
| `SPACE` | Analyze the current frame against the reference |
| `q` | Quit |

If the bag only fills part of the view, pass a region of interest: `--roi x,y,w,h`.

### Run on image files

```bash
python mybank_vision.py --reference ref.jpg --image test.jpg --unit-id DEMO-001
```

Results are printed, a `diff_heatmap.jpg` is saved, and a row is appended to `mybank_log.csv`.

## How the vision pipeline works

1. **Unit ID**: `cv2.QRCodeDetector` reads QR codes; `cv2.barcode.BarcodeDetector` (OpenCV 4.8+) reads 1D barcodes.
2. **Quality check**: rejects blurry (Laplacian variance), too dark/bright, or glare-heavy images and asks for a retake.
3. **Visual difference**: crop to ROI → resize → Gaussian blur → match lightness → per-pixel color distance in LAB space → threshold → remove speckle → percentage of changed pixels.
4. **Status**: flags for human review if the changed area exceeds a demo threshold (`DIFF_FLAG_PCT`).
5. **Log**: timestamp, unit ID, status, metrics and image path saved to CSV.

Thresholds are at the top of `mybank_vision.py` and should be tuned for your lighting and camera. They are **demo values, not validated limits**.

## Demo script for judges

1. Scan the QR label to show the unit ID.
2. Press `r` to capture the reference image of the training bag.
3. Press `SPACE`: the system reports no large difference.
4. Change the test condition (e.g., swap in a bag/image with a different color patch) and press `SPACE`: the system flags **visual difference, human review required**.
5. Trigger the simulated temperature alert (LED + dashboard).
6. State clearly that this is a demonstration, not a clinical diagnosis.

# MyBank Unit

[Open Interactive 3D Model](https://username.github.io/repository/model.html)

A 3D model of the add-on from the design sheet. The camera, backlight and probes sit inside the existing fridge. The processor, battery, screen and alarm stay outside, joined by a flat cable that passes under the door gasket.

View

Show

Path

Screen

Drag to rotate · scroll to zoom · right-drag to pan

Intelligence path: image, then decision Safety path: temperature, then alarm Blood bag Optional part

Schematic model built from the Blood Guard Unit design sheet. The bag-to-window distance (about 20 cm) and diffuser-to-cradle distance (about 3 cm) follow the sheet; every other proportion is approximate. It is a concept for the hackathon, not a certified medical device.

## Limitations

- Temperature inside the enclosure is not the temperature of the bag contents.
- Visible-light imaging cannot reliably detect clots or hemolysis; that would need dedicated spectral imaging and clinical validation.
- Thresholds are experimental; no accuracy, sensitivity or specificity has been measured.
- Not an approved storage device, incubator or quality-control system.

## Future work

- De-identified, specialist-labelled images and independent test data
- Measured sensitivity, specificity and false-alert rate
- Calibrated temperature logging against a reference thermometer
- Dashboard with unit history, cloud sync and inventory/expiry forecasting
- Cybersecurity, privacy and Saudi regulatory review before any clinical use

## Team

Medathon Team. Electrical & computer engineering plus medicine.

## License

MIT. See `LICENSE` (choose it when creating the repository on GitHub).
