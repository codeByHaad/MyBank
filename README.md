<div align="center">

# MyBank

**Smart blood bag inspection and cold-chain monitoring**

*Medathon Hackathon · Electrical and computer engineering + medicine*

</div>

> **Not a medical device.** MyBank is a hackathon prototype and product concept. It uses a **training bag or test images only** and must never be used with real human blood or to decide whether blood is safe for transfusion. MyBank raises flags for human review. It does not diagnose, and the technician always decides.

---

## Explore the project

| Stage | What you will see | Open |
|---|---|---|
| **Stage 1: Prototype** | The interactive design sheet of what we built for this hackathon: system architecture, cold-head cross-section, alarm escalation, parts list and cost | **[▶ Open the interactive prototype](https://codebyhaad.github.io/MyBank/)** |
| **Stage 2: Market-ready product** | The 3D model of the product we intend to deliver. Every part is numbered and clickable, with a colour key and a full reference table | **[▶ Open the 3D product model](https://codebyhaad.github.io/MyBank/mybank_market_ready_3d.html)** |

*Tip for the 3D model: drag to rotate, scroll to zoom, click any part to read what it is. Use the drawer slider to slide the drawer open and closed.*

---

## The problem

Blood banks must document storage conditions, notice unusual bag appearance, and keep expiry and inventory in one record. Today this relies on manual checks and on fridges that may not log what happens inside them.

## The solution

MyBank is an **add-on** that works inside the blood bank's existing refrigerator, so no fridge needs replacing. It:

- **Inspects** each bag with consistent backlighting and flags visible differences for human review
- **Tracks temperature** and raises an alarm when the 1 to 6 °C range is left
- **Records** each unit by barcode, with timestamps, results and alerts

All results are worded as *"Visual difference flagged - human review required"*, never as a diagnosis.

---

## Stage 1: Hackathon prototype

A low-cost working demonstration using a training bag.

| Function | What the prototype demonstrates |
|---|---|
| Visual inspection | Captures an image under fixed lighting and flags colour or shape differences versus a reference |
| Cold-chain tracking | ESP32 + DS18B20 reads temperature and raises an alert when a **demo** threshold is crossed |
| Digital record | Links a demo unit ID (QR or barcode) to timestamp, result and alerts |

### Run it

```bash
git clone https://github.com/codebyhaad/MyBank.git
cd MyBank
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python generate_qr.py DEMO-001          # make a QR label for a demo unit
python mybank_vision.py --camera 0      # run live with a camera
```

| Key | Action |
|---|---|
| `r` | Save the current frame as the reference image |
| `s` | Scan QR/barcode to set the unit ID |
| `SPACE` | Analyse the current frame against the reference |
| `q` | Quit |

To run on image files: `python mybank_vision.py --reference ref.jpg --image test.jpg --unit-id DEMO-001`. Results are printed, a `diff_heatmap.jpg` is saved, and a row is added to `mybank_log.csv`.

### How the vision pipeline works

1. **Unit ID:** reads QR codes and 1D barcodes with OpenCV.
2. **Quality check:** rejects blurry, too dark or bright, or glare-heavy images and asks for a retake.
3. **Visual difference:** crop, resize, blur, match lightness, compare colour in LAB space, threshold, remove speckle, and report the percentage changed.
4. **Status:** flags for human review if the change exceeds a demo threshold (`DIFF_FLAG_PCT`).
5. **Log:** timestamp, unit ID, status and metrics saved to CSV.

Thresholds are demo values, not validated limits.

### Hardware

ESP32, DS18B20 sensor with 4.7 kΩ pull-up, LED, transparent box holding a training bag, white LED lighting, a laptop and webcam, and an optional printed QR label. Keep the ESP32 and breadboard outside the chamber, on a dry base.

---

## Stage 2: Market-ready MyBank Unit

The product we intend to deliver: an add-on that sits inside an existing blood bank fridge (1 to 6 °C) and watches **five** red cell or whole blood units at a time for clots, discoloration and temperature excursions.

| Part | What it is |
|---|---|
| **1. Fixed housing** | Rests on a standard fridge shelf. Five downward-facing cameras behind heated anti-fog windows and light-tight baffles, five backlight panels (white plus 850 nm), a vibration exciter, a glycol probe bay with two redundant PT1000 probes, an air probe, a door sensor, an interface board and a flat-cable gland |
| **2. Passive drawer** | Clear, wipe-clean plastic with no electronics. Five compartments, a spring-hinged press plate that sets bag thickness without squeezing, a glove-friendly pull bar, label holders, stainless soft-close rails and a stop |
| **3. Outer hub** | On a side arm outside the fridge. Bilingual touchscreen, status beacon, speaker, badge-tap pad and acknowledge button, with the compute module, an independent safety MCU and a backup battery inside |

A thin flat cable runs from the housing under the door gasket to the hub.

**Why five slots?** Five is a deliberate choice for the first version of the product. It is a design decision, not a technical or medical limit:

- **Every slot has its own hardware.** Each bag lies flat over its own backlight panel, under its own camera, with its own label holder and status light.
- **Bags must lie flat and never touch each other.** They cannot be stacked, so every extra bag needs more floor area. Five bags side by side is designed to fit one fridge shelf.
- **One simple drawer.** All five bags are served by one drawer, one glove-friendly pull bar and one clear view of every unit.
- **Cost and complexity grow with every slot.** More slots mean more cameras, lights, heaters and cabling, which makes the product harder to build, clean and maintain. Starting with five keeps the first product simple and reliable.
- **It can scale later.** The design is modular, so a larger fridge could take more units or a wider drawer once the first version is proven.

**Safety first.** The safety path (temperature, then alarm) is separate and **never passes through the AI**. If the vision model or compute module fails, the alarm still works.

**Designed for real blood banks.** Bags never touch cold walls or get squeezed; barcodes face up for the camera; units follow first-expiry-first-out and a quarantined unit is obvious at a glance; fogging, condensation and door-open spikes are expected and handled; and all surfaces are chemical-resistant, with rounded radii, no exposed screws and sealed glands.

---

## Limitations

- Prototype temperature is measured in the enclosure, not inside the bag. The market design adds a glycol probe, which is not yet built or calibrated.
- Visible-light imaging cannot reliably detect clots or hemolysis. This needs dedicated imaging and clinical validation.
- No accuracy, sensitivity or specificity has been measured; thresholds are experimental.
- The 3D model is a schematic concept. Proportions beyond the design sheet are approximate.

## Path to market

- **SFDA registration** as a medical device or accessory, depending on classification
- Electrical safety and EMC testing
- Calibration records and documented periodic calibration
- Clinical evaluation, with thresholds set by the blood bank's medical team
- Cybersecurity and privacy review

## Future work

De-identified, specialist-labelled images; measured sensitivity and false-alert rate; calibrated temperature logging against a reference thermometer; a dashboard with unit history and expiry forecasting; and a blood bank trial.

## Team

Medathon Team: electrical and computer engineering plus medicine.

## License

MIT. See `LICENSE`.
