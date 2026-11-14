/*******************************************************************************
 *  SMART BLOOD BANK BOX MONITOR
 *  ---------------------------------------------------------------------------
 *  Board   : ESP32-S3 N8R2 (8 MB flash, 2 MB PSRAM)  ->  "ESP32S3 Dev Module"
 *
 *  Hardware:
 *    - HC-SR04 ultrasonic sensor (400 cm class) or JSN-SR04T waterproof type
 *      (note: JSN-SR04T min. range is ~25 cm, HC-SR04 min. is ~2 cm)
 *    - Buzzer (passive recommended - all tones are generated in this code)
 *    - Red LED 1 (proximity warning) + Red LED 2 (alarm)
 *    - 1.3" I2C OLED 128x64 (SH1106 controller - see constructor below)
 *    - Magnetic reed door sensor
 *    - DS18B20 1-Wire temperature sensor
 *
 *  What it does:
 *    1. Distance to the box is sampled ~8x per second (median filtered)
 *       and shown on the OLED together with temperature and door state.
 *    2. Person closer than PROX_WARN_CM  -> simple slow beep, LED1 blinks.
 *       Person closer than PROX_ALARM_CM -> faster beep, LED1 flashes fast.
 *    3. Box door opened (reed no longer sees the magnet) ->
 *       loud, rapid, near-continuous alarm tone + BOTH LEDs flash fast.
 *       (highest priority - overrides all other alarms)
 *    4. Temperature below TEMP_LOW_C (or above TEMP_HIGH_C) ->
 *       different two-tone alarm sound + BOTH LEDs flash at a slower rate.
 *    5. Every second a status line is printed to the Serial Monitor (115200).
 *
 *  WIRING:
 *    Ultrasonic  VCC -> 5V (VIN pin),  GND -> GND
 *                TRIG -> GPIO4
 *                ECHO -> GPIO5   *** ECHO idles at 5 V! Use a divider:
 *                    ECHO --[1 kOhm]-- GPIO5 --[2 kOhm]-- GND ***
 *    Buzzer      +  -> GPIO7   (direct if it draws < ~12 mA; otherwise use
 *                    an NPN transistor: buzzer+ -> 5V, buzzer- -> collector,
 *                    emitter -> GND, base -> GPIO7 via 1 kOhm)
 *                -  -> GND
 *    Red LED 1   GPIO15 -> 220R -> LED -> GND     (proximity / warning)
 *    Red LED 2   GPIO16 -> 220R -> LED -> GND     (alarm)
 *    Reed switch GPIO17 <-> GND   (internal pull-up, no external resistor)
 *                Door CLOSED = magnet near = switch closed = pin reads LOW.
 *                (NC reed type? change DOOR_OPEN_LEVEL below)
 *    DS18B20     VCC -> 3V3,  GND -> GND,  DATA -> GPIO6
 *                + 4.7 kOhm pull-up between DATA and 3V3 (required!)
 *    OLED 1.3"   VCC -> 3V3,  GND -> GND,  SDA -> GPIO8,  SCL -> GPIO9
 *
 *  Arduino IDE - Tools menu:
 *    Board: "ESP32S3 Dev Module"
 *    Flash Size: 8MB          PSRAM: QSPI PSRAM
 *    USB CDC On Boot: Enabled (needed to see the Serial Monitor over USB-C)
 *
 *  Libraries (Arduino IDE > Library Manager):
 *    U8g2              (olikraus)
 *    OneWire           (Paul Stoffregen)
 *    DallasTemperature (Miles Burton)
 ******************************************************************************/

#include <Wire.h>
#include <U8g2lib.h>
#include <OneWire.h>
#include <DallasTemperature.h>

/* ============================ USER CONFIG ============================ */

/* ---- Pins (change here if you wired differently) ---- */
#define PIN_TRIG      4      // ultrasonic TRIG
#define PIN_ECHO      5      // ultrasonic ECHO (through voltage divider!)
#define PIN_DS18B20   6      // DS18B20 DATA (4.7k pull-up to 3V3)
#define PIN_BUZZER    7      // buzzer (+)
#define PIN_SDA       8      // OLED SDA
#define PIN_SCL       9      // OLED SCL
#define PIN_LED_PROX 15      // red LED 1 - proximity warning
#define PIN_LED_ALRM 16      // red LED 2 - alarm
#define PIN_DOOR     17      // magnetic reed switch (other leg to GND)

#define DOOR_OPEN_LEVEL  HIGH   // NO reed switch: door closed = LOW.
                                // For a NC reed switch set this to LOW.

/* ---- Behaviour thresholds ---- */
const int   PROX_WARN_CM  = 120;   // closer than this -> slow warning beeps
const int   PROX_ALARM_CM =  60;   // closer than this -> fast alarm beeps
const float TEMP_LOW_C    = 23;//2.0;   // blood must stay 2..6 C: alarm below this
const float TEMP_HIGH_C   = 30;//8.0;   // ...and above this (set 99 to disable)
const float TEMP_HYST     = 0.5;   // anti-chatter band around thresholds (C)

/* ---- Timing ---- */
const uint16_t ECHO_TIMEOUT_US  = 25000;  // ~4.3 m, covers the 400 cm sensor
const uint16_t DIST_INTERVAL_MS = 120;    // ultrasonic sample period
const uint16_t TEMP_INTERVAL_MS = 2000;   // DS18B20 sample period
const uint16_t DISP_INTERVAL_MS = 250;    // OLED refresh period
/* ===================================================================== */

/* ========================== BUZZER (LEDC tone) ========================
 * Compatible with ESP32 Arduino core 2.x (ledcSetup) and 3.x (ledcAttach).
 * An ACTIVE buzzer also works: it will beep on/off with the patterns,
 * just with its own internal pitch.                                     */
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  #define BUZZER_INIT()   ledcAttach(PIN_BUZZER, 2000, 10)
  #define BUZZER_TONE(f)  ledcWriteTone(PIN_BUZZER, (f))
#else
  #define BUZZER_CH       0
  #define BUZZER_INIT()   do { ledcSetup(BUZZER_CH, 2000, 10); \
                               ledcAttachPin(PIN_BUZZER, BUZZER_CH); } while (0)
  #define BUZZER_TONE(f)  ledcWriteTone(BUZZER_CH, (f))
#endif

/* ======================== ALARM SOUND PATTERNS ========================
 * Each pattern is a repeating list of steps { frequency_Hz, duration_ms }.
 * frequency 0 = silence. Edit freely to create your own sounds.         */
struct ToneStep { uint16_t freq; uint16_t ms; };

const ToneStep PAT_OFF[]       = { {0,    500} };                // silent
const ToneStep PAT_PROX_WARN[] = { {1000,  70}, {0,   530} };    // slow beep
const ToneStep PAT_PROX_ALRM[] = { {1300,  70}, {0,   180} };    // fast beep
const ToneStep PAT_DOOR[]      = { {2500,  90}, {0,    30} };    // loud, rapid, near-continuous
const ToneStep PAT_TEMP[]      = { {1400, 130}, {0,   130},
                                   {2000, 130}, {0,   130} };    // distinct two-tone

const ToneStep* curPattern = nullptr;
uint8_t  curSteps  = 0;
uint8_t  curStep   = 0;
uint32_t stepStart = 0;

void buzzerPlay(const ToneStep* pattern, uint8_t count) {
  if (pattern == curPattern) return;          // pattern unchanged, keep going
  curPattern = pattern;  curSteps = count;  curStep = 0;
  stepStart  = millis();
  BUZZER_TONE(pattern[0].freq);               // freq 0 = silence
}

void buzzerUpdate(uint32_t now) {
  if (!curPattern || curSteps == 0) return;
  if (now - stepStart < curPattern[curStep].ms) return;
  curStep = (curStep + 1) % curSteps;
  stepStart = now;
  BUZZER_TONE(curPattern[curStep].freq);
}

/* ============================ DISPLAY =================================
 * A 1.3" 128x64 I2C OLED is almost always an SH1106 controller.
 * If the screen stays blank try:
 *   - SSD1306 (typical for 0.96"): use
 *       U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);
 *   - another I2C address: uncomment setI2CAddress() in setup().        */
U8G2_SH1106_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

/* ============================ DS18B20 ================================= */
OneWire oneWire(PIN_DS18B20);
DallasTemperature ds18b20(&oneWire);

/* ========================== RUNTIME STATE ============================= */
float    distanceCm = 999.0;    // median-filtered distance, 999 = nothing near
float    tempC      = NAN;      // last good DS18B20 reading
bool     doorOpen   = false;    // debounced reed switch state
bool     tempAlarm  = false;    // temperature alarm (with hysteresis)

uint32_t tTrig = 0, tTempReq = 0, tDisp = 0, tSer = 0;

/* ---- ultrasonic median filter ---- */
const uint8_t NDIST = 5;
float   dBuf[NDIST];
uint8_t dIdx = 0, dCnt = 0;

/* ---- door debounce ---- */
bool     doorRaw = false;
uint32_t doorChangedAt = 0;

/* ========================== ULTRASONIC ================================ */
float readDistanceOnce() {
  digitalWrite(PIN_TRIG, LOW);   delayMicroseconds(4);
  digitalWrite(PIN_TRIG, HIGH);  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);
  unsigned long us = pulseIn(PIN_ECHO, HIGH, ECHO_TIMEOUT_US);
  if (us == 0) return -1.0;                     // no echo = nothing in range
  float cm = us * 0.0343f / 2.0f;               // sound speed 343 m/s
  if (cm < 2.0f || cm > 450.0f) return -1.0;    // outside sensor spec
  return cm;
}

void updateDistance(uint32_t now) {
  if (now - tTrig < DIST_INTERVAL_MS) return;
  tTrig = now;

  float d = readDistanceOnce();
  dBuf[dIdx] = (d < 0) ? 999.0f : d;
  dIdx = (dIdx + 1) % NDIST;
  if (dCnt < NDIST) dCnt++;

  float tmp[NDIST];
  memcpy(tmp, dBuf, dCnt * sizeof(float));
  for (uint8_t i = 1; i < dCnt; i++) {          // insertion sort
    float k = tmp[i]; int8_t j = i - 1;
    while (j >= 0 && tmp[j] > k) { tmp[j + 1] = tmp[j]; j--; }
    tmp[j + 1] = k;
  }
  distanceCm = tmp[dCnt / 2];                   // median rejects false echoes
}

/* ========================== TEMPERATURE =============================== */
void updateTemperature(uint32_t now) {
  if (tTempReq == 0) {                          // first run: start conversion
    ds18b20.requestTemperatures();
    tTempReq = now;
    return;
  }
  if (now - tTempReq < TEMP_INTERVAL_MS) return;
  tTempReq = now;

  float t = ds18b20.getTempCByIndex(0);         // read previous conversion
  if (t > -100.0f && t < 85.0f) tempC = t;      // -127 = sensor disconnected
  ds18b20.requestTemperatures();                // start the next conversion

  /* low/high temperature alarm with hysteresis (non-blocking) */
  if (!isnan(tempC)) {
    if (!tempAlarm && (tempC < TEMP_LOW_C || tempC > TEMP_HIGH_C)) {
      tempAlarm = true;
    } else if (tempAlarm && tempC > TEMP_LOW_C + TEMP_HYST &&
                              tempC < TEMP_HIGH_C - TEMP_HYST) {
      tempAlarm = false;
    }
  }
}

/* ========================== DOOR SENSOR =============================== */
void updateDoor(uint32_t now) {
  bool raw = (digitalRead(PIN_DOOR) == DOOR_OPEN_LEVEL);
  if (raw != doorRaw) { doorRaw = raw; doorChangedAt = now; }
  if (now - doorChangedAt >= 40) doorOpen = doorRaw;    // 40 ms debounce
}

/* ============================= LEDS =================================== */
void updateLeds(uint32_t now) {
  bool l1 = false, l2 = false;
  if (doorOpen) {                               // both LEDs, very fast flash
    l1 = l2 = (((now / 80)  & 1) == 0);
  } else if (tempAlarm) {                       // both LEDs, slower flash
    l1 = l2 = (((now / 250) & 1) == 0);
  } else if (distanceCm <= PROX_ALARM_CM) {     // LED1 fast blink
    l1 = (((now / 120) & 1) == 0);
  } else if (distanceCm <= PROX_WARN_CM) {      // LED1 slow blink
    l1 = (((now / 400) & 1) == 0);
  }
  digitalWrite(PIN_LED_PROX, l1 ? HIGH : LOW);
  digitalWrite(PIN_LED_ALRM, l2 ? HIGH : LOW);
}

/* ============================= OLED =================================== */
void drawDisplay() {
  bool proxAlarm = (distanceCm <= PROX_ALARM_CM);
  bool proxWarn  = (distanceCm <= PROX_WARN_CM);
  bool anyAlarm  = doorOpen || tempAlarm || proxAlarm;

  const char* status;
  if      (doorOpen)  status = "! BOX OPEN !";
  else if (tempAlarm) status = "! TEMP ALERT !";
  else if (proxAlarm) status = "! KEEP AWAY !";
  else if (proxWarn)  status = "APPROACHING";
  else                status = "SYSTEM SECURE";

  char line[28];

  u8g2.clearBuffer();

  /* header */
  u8g2.setFont(u8g2_font_6x10_tr);
  u8g2.drawStr((u8g2.getDisplayWidth() -
                u8g2.getStrWidth("BLOOD BANK MONITOR")) / 2, 10,
               "BLOOD BANK MONITOR");
  u8g2.drawLine(0, 12, u8g2.getDisplayWidth() - 1, 12);

  /* status bar - inverted whenever an alarm is active */
  u8g2.setFont(u8g2_font_9x15B_tr);
  if (anyAlarm) {
    u8g2.drawBox(0, 15, u8g2.getDisplayWidth(), 18);
    u8g2.setDrawColor(0);
  }
  u8g2.drawStr((u8g2.getDisplayWidth() - u8g2.getStrWidth(status)) / 2, 29, status);
  if (anyAlarm) u8g2.setDrawColor(1);

  /* distance */
  u8g2.setFont(u8g2_font_9x15_tr);
  if (distanceCm > 450) snprintf(line, sizeof(line), "Dist:  --- cm");
  else                  snprintf(line, sizeof(line), "Dist: %3d cm",
                                 (int)(distanceCm + 0.5f));
  u8g2.drawStr(2, 48, line);

  /* temperature + door state */
  u8g2.setFont(u8g2_font_6x10_tr);
  char tstr[12];
  if (isnan(tempC)) snprintf(tstr, sizeof(tstr), "T: --.-C");
  else              snprintf(tstr, sizeof(tstr), "T: %4.1fC", tempC);
  snprintf(line, sizeof(line), "%s  Door:%s", tstr, doorOpen ? "OPEN" : "CLSD");
  u8g2.drawStr(2, 63, line);

  u8g2.sendBuffer();
}

void drawSplash() {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_10x20_tr);
  u8g2.drawStr((128 - u8g2.getStrWidth("BLOOD BANK")) / 2, 24, "BLOOD BANK");
  u8g2.setFont(u8g2_font_9x15_tr);
  u8g2.drawStr((128 - u8g2.getStrWidth("BOX MONITOR")) / 2, 42, "BOX MONITOR");
  u8g2.setFont(u8g2_font_6x10_tr);
  u8g2.drawStr((128 - u8g2.getStrWidth("starting sensors...")) / 2, 60,
               "starting sensors...");
  u8g2.sendBuffer();
}

/* ========================== SETUP / LOOP ============================== */
void setup() {
  Serial.begin(115200);
  Serial.println("\n=== Smart Blood Bank Box Monitor ===");

  pinMode(PIN_TRIG, OUTPUT);     digitalWrite(PIN_TRIG, LOW);
  pinMode(PIN_ECHO, INPUT);
  pinMode(PIN_LED_PROX, OUTPUT); digitalWrite(PIN_LED_PROX, LOW);
  pinMode(PIN_LED_ALRM, OUTPUT); digitalWrite(PIN_LED_ALRM, LOW);
  pinMode(PIN_DOOR, INPUT_PULLUP);

  BUZZER_INIT();

  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);              // fast I2C for smooth OLED updates
  // u8g2.setI2CAddress(0x3D * 2);    // uncomment if your OLED is at 0x3D
  u8g2.begin();
  u8g2.setBusClock(400000);

  ds18b20.begin();
  ds18b20.setResolution(12);
  ds18b20.setWaitForConversion(false);   // non-blocking temperature reads

  drawSplash();

  /* quick self test: both LEDs + short beep */
  digitalWrite(PIN_LED_PROX, HIGH);
  digitalWrite(PIN_LED_ALRM, HIGH);
  BUZZER_TONE(1500);  delay(200);
  BUZZER_TONE(0);
  digitalWrite(PIN_LED_PROX, LOW);
  digitalWrite(PIN_LED_ALRM, LOW);
  delay(800);                            // leave the splash visible a moment
}

void loop() {
  uint32_t now = millis();

  updateDistance(now);
  updateTemperature(now);
  updateDoor(now);

  /* ---- alarm priority: door tamper > temperature > proximity ---- */
  if      (doorOpen)                    buzzerPlay(PAT_DOOR,
                                              sizeof(PAT_DOOR)      / sizeof(ToneStep));
  else if (tempAlarm)                   buzzerPlay(PAT_TEMP,
                                              sizeof(PAT_TEMP)      / sizeof(ToneStep));
  else if (distanceCm <= PROX_ALARM_CM) buzzerPlay(PAT_PROX_ALRM,
                                              sizeof(PAT_PROX_ALRM) / sizeof(ToneStep));
  else if (distanceCm <= PROX_WARN_CM)  buzzerPlay(PAT_PROX_WARN,
                                              sizeof(PAT_PROX_WARN) / sizeof(ToneStep));
  else                                  buzzerPlay(PAT_OFF,
                                              sizeof(PAT_OFF)       / sizeof(ToneStep));

  buzzerUpdate(now);
  updateLeds(now);

  if (now - tDisp >= DISP_INTERVAL_MS) {
    tDisp = now;
    drawDisplay();
  }

  if (now - tSer >= 1000) {
    tSer = now;
    char d[12], t[12];
    if (distanceCm > 450) snprintf(d, sizeof(d), "---");
    else                  snprintf(d, sizeof(d), "%d", (int)(distanceCm + 0.5f));
    if (isnan(tempC))     snprintf(t, sizeof(t), "--.-");
    else                  snprintf(t, sizeof(t), "%.1f", tempC);
    Serial.printf("Distance: %s cm | Temp: %s C | Door: %s\n",
                  d, t, doorOpen ? "OPEN" : "CLOSED");
  }
}
