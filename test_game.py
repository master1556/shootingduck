import cv2
import mediapipe as mp
import numpy as np
import random
import math
import time
import os
import sys
import json
import threading
import urllib.request

# ─────────────────────────────────────────────
#  CROSS-PLATFORM SOUND
# ─────────────────────────────────────────────
def _beep(freq: int, duration_ms: int):
    try:
        if sys.platform == "win32":
            import winsound
            winsound.Beep(freq, duration_ms)
        else:
            sys.stdout.write('\a')
            sys.stdout.flush()
    except Exception:
        pass

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
class Config:
    WIDTH            = 1280
    HEIGHT           = 720
    WINDOW_TITLE     = "Duck Hunt  |  Hand Gesture + Voice Edition"

    GAME_DURATION    = 60
    MAX_DUCKS        = 5

    PINCH_THRESHOLD  = 0.06
    SMOOTH_ALPHA     = 0.4
    SHOOT_COOLDOWN   = 0.25

    LEVEL_SCORE_STEP = 5
    MAX_LEVEL        = 5
    COMBO_TIMEOUT    = 2.0

    SHOOT_FREQ       = 1200
    SHOOT_DUR        = 80
    HIT_FREQ         = 350
    HIT_DUR          = 200

    HIGHSCORE_FILE   = "highscore.json"
    MODEL_PATH       = "hand_landmarker.task"
    MODEL_URL        = (
        "https://storage.googleapis.com/mediapipe-models/"
        "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
    )

    # Voice trigger words (add more if needed)
    VOICE_TRIGGERS   = ["shoot", "fire", "bang", "hit"]

class GameState:
    MENU      = "MENU"
    PLAYING   = "PLAYING"
    GAME_OVER = "GAME_OVER"

# ─────────────────────────────────────────────
#  VOICE CONTROLLER  (sounddevice backend)
#  Works on Python 3.13 — no PyAudio needed
#  pip install sounddevice SpeechRecognition
# ─────────────────────────────────────────────
class VoiceController:
    """
    Background thread that listens for voice commands.
    Uses sounddevice as audio backend — works on Python 3.13.
    Say "shoot", "fire", "bang", or "hit" to trigger a shot.
    If libraries are missing, voice is silently disabled.
    """

    def __init__(self):
        self._shoot_flag  = threading.Event()
        self._running     = True
        self._available   = False
        self._status      = "Voice: initialising..."
        self._last_heard  = ""
        self._thread      = threading.Thread(
            target=self._loop, daemon=True, name="VoiceThread"
        )
        self._thread.start()

    # ── public ──────────────────────────────

    @property
    def available(self) -> bool:
        return self._available

    @property
    def status(self) -> str:
        return self._status

    @property
    def last_heard(self) -> str:
        return self._last_heard

    def check_shoot(self) -> bool:
        """Returns True once per voice-shoot event, then resets."""
        if self._shoot_flag.is_set():
            self._shoot_flag.clear()
            return True
        return False

    def stop(self):
        self._running = False

    # ── private ─────────────────────────────

    def _loop(self):
        # Check imports
        try:
            import speech_recognition as sr
        except ImportError:
            self._status = "Voice: OFF (pip install SpeechRecognition)"
            return

        try:
            import sounddevice as sd
        except ImportError:
            self._status = "Voice: OFF (pip install sounddevice)"
            return

        import numpy as np
        import io
        import wave

        SAMPLE_RATE = 16000
        CHANNELS    = 1

        recogniser = sr.Recognizer()
        recogniser.energy_threshold         = 300
        recogniser.dynamic_energy_threshold = True

        # ── Ambient calibration (1 second) ──
        try:
            self._status = "Voice: calibrating mic..."
            print("[Voice] Calibrating microphone — 1 second...")
            calib = sd.rec(
                int(SAMPLE_RATE * 1.0),
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16"
            )
            sd.wait()
            rms = float(np.sqrt(np.mean(calib.astype(np.float32) ** 2)))
            recogniser.energy_threshold = max(300, rms * 1.5)
            print(f"[Voice] Ready. Energy threshold: {recogniser.energy_threshold:.0f}")
        except Exception as e:
            self._status = f"Voice: mic error ({e})"
            return

        self._available = True
        self._status    = "Voice: READY — say 'shoot' / 'fire'"

        # ── Listen loop ──
        while self._running:
            try:
                # Record 2-second chunk
                recording = sd.rec(
                    int(SAMPLE_RATE * 2.0),
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16"
                )
                sd.wait()

                # Skip if too quiet (silence detection — avoids wasting API calls)
                rms_chunk = float(np.sqrt(
                    np.mean(recording.astype(np.float32) ** 2)
                ))
                if rms_chunk < recogniser.energy_threshold * 0.6:
                    continue

                # Convert numpy array → in-memory WAV → AudioData
                buf = io.BytesIO()
                with wave.open(buf, "wb") as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(2)          # int16 = 2 bytes
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes(recording.tobytes())
                buf.seek(0)

                with sr.AudioFile(buf) as source:
                    audio = recogniser.record(source)

                # Send to Google Speech API
                text = recogniser.recognize_google(audio).lower().strip()
                self._last_heard = text
                print(f"[Voice] Heard: '{text}'")

                if any(word in text for word in Config.VOICE_TRIGGERS):
                    self._shoot_flag.set()
                    self._status = f"Voice: SHOOT! ('{text}')"
                else:
                    self._status = f"Voice: '{text}'"

            except sr.UnknownValueError:
                pass        # unclear audio — keep going
            except sr.RequestError as e:
                self._status = f"Voice: network error ({e})"
                time.sleep(2)
            except Exception as e:
                self._status = f"Voice: error {e}"
                time.sleep(1)

# ─────────────────────────────────────────────
#  HIGH SCORE
# ─────────────────────────────────────────────
class HighScoreManager:
    def __init__(self, filepath: str):
        self.filepath   = filepath
        self.high_score = self._load()

    def _load(self) -> int:
        try:
            if os.path.exists(self.filepath):
                with open(self.filepath) as f:
                    return int(json.load(f).get("high_score", 0))
        except Exception:
            pass
        return 0

    def update(self, score: int) -> bool:
        if score > self.high_score:
            self.high_score = score
            try:
                with open(self.filepath, "w") as f:
                    json.dump({"high_score": score}, f)
            except Exception:
                pass
            return True
        return False

# ─────────────────────────────────────────────
#  FLOATING SCORE TEXT
# ─────────────────────────────────────────────
class FloatingText:
    def __init__(self, x: int, y: int, text: str, color=(0, 255, 100)):
        self.x        = x
        self.y        = y
        self.text     = text
        self.color    = color
        self.start    = time.time()
        self.lifetime = 0.9

    @property
    def alive(self) -> bool:
        return (time.time() - self.start) < self.lifetime

    def draw(self, frame):
        elapsed  = time.time() - self.start
        alpha    = max(0.0, 1.0 - elapsed / self.lifetime)
        offset_y = int(elapsed * 90)
        px, py   = self.x - 30, self.y - offset_y
        color    = tuple(int(c * alpha) for c in self.color)
        cv2.putText(frame, self.text, (px + 2, py + 2),
                    cv2.FONT_HERSHEY_DUPLEX, 1.1, (0, 0, 0), 4)
        cv2.putText(frame, self.text, (px, py),
                    cv2.FONT_HERSHEY_DUPLEX, 1.1, color, 2)

# ─────────────────────────────────────────────
#  DUCK
# ─────────────────────────────────────────────
class Duck:
    """
    Duck with full-body hit detection.

    The duck is drawn using three shapes:
      - Body ellipse  : centre (cx, cy),      axes (36, 22)
      - Head circle   : centre (cx+40, cy-16), radius 17
      - Beak triangle : roughly cx+53..cx+68, cy-16

    check_hit() tests the cursor point against all three shapes,
    so hitting the wing tip, beak tip, or head all register as hits.
    """

    COLORS = [(34, 160, 34), (30, 120, 220), (210, 70, 70), (160, 30, 160)]

    def __init__(self, screen_w: int, screen_h: int, speed_bonus: int = 0):
        self.screen_w    = screen_w
        self.screen_h    = screen_h
        self.speed_bonus = speed_bonus
        self.reset()

    def reset(self):
        self.x         = -80
        self.y         = random.randint(90, self.screen_h - 180)
        self.speed     = random.randint(4, 8) + self.speed_bonus
        self.alive     = True
        self.hit       = False
        self.hit_timer = 0.0
        self.color     = random.choice(self.COLORS)
        self.wing_up   = True
        self.wing_t    = time.time()

    def move(self):
        if self.alive:
            self.x += self.speed
            if time.time() - self.wing_t > 0.18:
                self.wing_up = not self.wing_up
                self.wing_t  = time.time()

    def is_off_screen(self) -> bool:
        return self.x > self.screen_w + 120

    # ── Hit detection — full body ─────────────
    def check_hit(self, px: float, py: float) -> bool:
        """
        Returns True if (px, py) is inside ANY part of the duck:
          body ellipse, head circle, or beak triangle.
        """
        cx, cy = self.x, self.y

        # 1. Body ellipse  (36 wide, 22 tall)
        if ((px - cx) / 36) ** 2 + ((py - cy) / 22) ** 2 <= 1.0:
            return True

        # 2. Head circle  (radius 17, offset right+up)
        hx, hy = cx + 40, cy - 16
        if math.hypot(px - hx, py - hy) <= 17:
            return True

        # 3. Beak triangle  (three vertices)
        beak = np.array([[cx + 53, cy - 16],
                         [cx + 68, cy - 14],
                         [cx + 53, cy - 10]], dtype=np.float32)
        if cv2.pointPolygonTest(beak, (float(px), float(py)), False) >= 0:
            return True

        # 4. Wing bounding area (approximate — covers wing polygon)
        wx1, wx2 = cx - 10, cx + 25
        wy1, wy2 = cy - 24, cy + 12
        if wx1 <= px <= wx2 and wy1 <= py <= wy2:
            return True

        return False

    # ── Drawing ───────────────────────────────
    def draw(self, frame):
        cx, cy = int(self.x), int(self.y)

        # Explosion
        if self.hit:
            elapsed = time.time() - self.hit_timer
            radius  = int(elapsed * 180)
            alpha   = max(0.0, 1.0 - elapsed / 0.4)
            ov      = frame.copy()
            cv2.circle(ov, (cx, cy), max(1, radius), (40, 100, 255), -1)
            cv2.addWeighted(ov, alpha * 0.75, frame, 1 - alpha * 0.75, 0, frame)
            cv2.putText(frame, "BOOM!", (cx - 38, cy - 18),
                        cv2.FONT_HERSHEY_DUPLEX, 1.1, (30, 50, 255), 3)
            for angle in range(0, 360, 45):
                r   = int(elapsed * 140)
                fpx = cx + int(r * math.cos(math.radians(angle)))
                fpy = cy + int(r * math.sin(math.radians(angle)))
                a   = max(0.0, alpha)
                cv2.circle(frame, (fpx, fpy), 5,
                           tuple(int(c * a) for c in self.color), -1)
            return

        # Shadow
        cv2.ellipse(frame, (cx + 2, cy + 28), (32, 8), 0, 0, 360,
                    (0, 80, 0), -1)

        # Wing (animated)
        if self.wing_up:
            wing = np.array([[cx - 8, cy - 4],  [cx + 8, cy - 24],
                              [cx + 22, cy - 10], [cx + 8, cy + 4]], np.int32)
        else:
            wing = np.array([[cx - 8, cy + 4],  [cx + 8, cy + 12],
                              [cx + 22, cy + 2],  [cx + 8, cy - 6]], np.int32)
        darker = tuple(max(0, c - 50) for c in self.color)
        cv2.fillPoly(frame, [wing], darker)
        cv2.polylines(frame, [wing], True, (0, 0, 0), 1)

        # Body
        cv2.ellipse(frame, (cx, cy), (36, 22), 0, 0, 360, self.color, -1)
        cv2.ellipse(frame, (cx, cy), (36, 22), 0, 0, 360, (0, 0, 0), 2)

        # Head
        cv2.circle(frame, (cx + 40, cy - 16), 17, self.color, -1)
        cv2.circle(frame, (cx + 40, cy - 16), 17, (0, 0, 0), 2)

        # Eye
        cv2.circle(frame, (cx + 46, cy - 20), 5, (255, 255, 255), -1)
        cv2.circle(frame, (cx + 48, cy - 20), 2, (0, 0, 0), -1)

        # Beak
        beak = np.array([[cx + 53, cy - 16], [cx + 68, cy - 14],
                          [cx + 53, cy - 10]], np.int32)
        cv2.fillPoly(frame, [beak], (0, 190, 255))
        cv2.polylines(frame, [beak], True, (0, 0, 0), 1)

        # Feet
        for lx in [cx - 8, cx + 8]:
            cv2.line(frame, (lx, cy + 22), (lx, cy + 36), (0, 140, 220), 3)
        cv2.line(frame, (cx - 8, cy + 36), (cx - 22, cy + 36), (0, 140, 220), 3)
        cv2.line(frame, (cx + 8, cy + 36), (cx + 4,  cy + 36), (0, 140, 220), 3)

# ─────────────────────────────────────────────
#  ANIMATED BACKGROUND
# ─────────────────────────────────────────────
class AnimatedBackground:
    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        self._static = np.zeros((h, w, 3), dtype=np.uint8)
        self._build_static()
        self.clouds = [
            [random.randint(0, w), random.randint(30, h // 4),
             random.uniform(0.7, 1.3), random.uniform(0.3, 0.8)]
            for _ in range(6)
        ]
        self.birds = [
            [random.randint(0, w), random.randint(40, h // 3),
             random.uniform(1.0, 2.5), random.uniform(0, math.pi * 2)]
            for _ in range(8)
        ]
        self._start    = time.time()
        self._prev_t   = 0.0

    def _build_static(self):
        c = self._static
        w, h = self.w, self.h

        # Far hills
        cv2.fillPoly(c, [np.array([[0, h//2],[w//5,int(h*.35)],[2*w//5,h//2]])],
                     (60, 120, 60))
        cv2.fillPoly(c, [np.array([[w//3,h//2],[w//2,int(h*.32)],[2*w//3,h//2]])],
                     (45, 100, 55))
        cv2.fillPoly(c, [np.array([[w//2,h//2],[3*w//4,int(h*.38)],[w,h//2]])],
                     (70, 130, 65))

        # Ground
        cv2.rectangle(c, (0, h//2), (w, h), (34, 110, 34), -1)

        # Pond
        cv2.ellipse(c, (w//2, int(h*.72)), (160, 70), 0, 0, 360,
                    (120, 160, 210), -1)
        cv2.ellipse(c, (w//2, int(h*.72)), (160, 70), 0, 0, 360,
                    (80, 120, 180), 3)

        # Trees left
        for tx, ty in [(w//9, h//2), (w//6, int(h*.52))]:
            cv2.line(c, (tx, ty), (tx, int(h*.85)), (80, 50, 20), 18)
            cv2.ellipse(c, (tx, int(ty - h*.06)), (38, 72), 0, 0, 360,
                        (20, 130, 30), -1)
            cv2.ellipse(c, (tx, int(ty - h*.06)), (38, 72), 0, 0, 360,
                        (10, 100, 20), 2)

        # Trees right
        for tx, ty in [(7*w//8, h//2), (5*w//6, int(h*.52))]:
            cv2.line(c, (tx, ty), (tx, int(h*.85)), (80, 50, 20), 18)
            cv2.ellipse(c, (tx, int(ty - h*.06)), (38, 72), 0, 0, 360,
                        (20, 130, 30), -1)
            cv2.ellipse(c, (tx, int(ty - h*.06)), (38, 72), 0, 0, 360,
                        (10, 100, 20), 2)

        # Fence
        for fx in range(80, w - 80, 80):
            cv2.line(c, (fx, int(h*.52)), (fx, int(h*.60)), (160, 110, 60), 5)
        cv2.line(c, (80, int(h*.55)), (w-80, int(h*.55)), (160, 110, 60), 3)
        cv2.line(c, (80, int(h*.58)), (w-80, int(h*.58)), (160, 110, 60), 3)

        # Flowers
        random.seed(42)
        for _ in range(30):
            fx = random.randint(80, w - 80)
            fy = random.randint(int(h*.55), int(h*.85))
            fc = random.choice([(255,100,200),(255,220,50),(255,150,50),(255,255,255)])
            cv2.circle(c, (fx, fy), 5, fc, -1)
            cv2.circle(c, (fx, fy), 2, (255, 220, 0), -1)
        random.seed()

    def _sky_gradient(self, canvas, t):
        h = canvas.shape[0]
        phase = (math.sin(t * 0.05) + 1) / 2
        for y in range(h // 2):
            r = y / (h // 2)
            canvas[y, :] = (
                min(255, int((120 + phase*60)  + r * (180 + phase*40 - (120 + phase*60)))),
                min(255, int((200 + phase*30)  + r * (230 + phase*15 - (200 + phase*30)))),
                min(255, int((180 + phase*50)  + r * (220 + phase*20 - (180 + phase*50)))),
            )

    def _draw_sun(self, canvas, t):
        w = self.w
        sx = int(w*.15 + (w*.7) * ((math.sin(t*.02)+1)/2))
        sy = int(self.h * .12)
        for r in range(55, 15, -8):
            a  = (55 - r) / 55 * 0.25
            ov = canvas.copy()
            cv2.circle(ov, (sx, sy), r, (30, 200, 255), -1)
            cv2.addWeighted(ov, a, canvas, 1-a, 0, canvas)
        cv2.circle(canvas, (sx, sy), 28, (30, 210, 255), -1)
        cv2.circle(canvas, (sx, sy), 22, (60, 230, 255), -1)

    def _draw_clouds(self, canvas, dt):
        w, h = self.w, self.h
        for cloud in self.clouds:
            cloud[0] += cloud[3] * dt * 30
            if cloud[0] > w + 200:
                cloud[0] = -200
                cloud[1] = random.randint(30, h//4)
            cx, cy, sc = int(cloud[0]), int(cloud[1]), cloud[2]
            for dx, ew, eh in [(0,80,38),(-30,52,26),(30,52,26)]:
                ov = canvas.copy()
                cv2.ellipse(ov,(cx+dx,cy+6),(int(ew*sc),int(eh*sc*.4)),0,0,360,(170,185,200),-1)
                cv2.addWeighted(ov,.3,canvas,.7,0,canvas)
                cv2.ellipse(canvas,(cx+dx,cy),(int(ew*sc),int(eh*sc)),0,0,360,(248,250,255),-1)

    def _draw_birds(self, canvas, t, dt):
        for b in self.birds:
            b[0] += b[2] * dt * 40
            if b[0] > self.w + 60:
                b[0] = -60
                b[1] = random.randint(40, self.h//3)
            bx, by  = int(b[0]), int(b[1])
            phase   = math.sin(t * 4 + b[3]) * 6
            cv2.line(canvas, (bx-12, by),     (bx-4, int(by-phase)), (30,30,30), 2)
            cv2.line(canvas, (bx+4, int(by-phase)), (bx+12, by),  (30,30,30), 2)

    def _draw_pond_ripple(self, canvas, t):
        cx, cy = self.w//2, int(self.h*.72)
        for i in range(3):
            phase = (t*1.5 + i*0.8) % 3.0
            alpha = max(0.0, 1.0 - phase/3.0) * 0.5
            ov    = canvas.copy()
            cv2.ellipse(ov, (cx,cy), (int(40+phase*60), int(10+phase*15)),
                        0, 0, 360, (200,220,255), 2)
            cv2.addWeighted(ov, alpha, canvas, 1-alpha, 0, canvas)

    def render(self) -> np.ndarray:
        t          = time.time() - self._start
        dt         = t - self._prev_t
        self._prev_t = t
        canvas = np.zeros((self.h, self.w, 3), dtype=np.uint8)
        self._sky_gradient(canvas, t)
        self._draw_sun(canvas, t)
        self._draw_clouds(canvas, dt)
        self._draw_birds(canvas, t, dt)
        mask = self._static.sum(axis=2) > 0
        canvas[mask] = self._static[mask]
        self._draw_pond_ripple(canvas, t)
        return canvas

# ─────────────────────────────────────────────
#  UI HELPERS
# ─────────────────────────────────────────────
def _panel(frame, x1, y1, x2, y2, alpha=0.65, border=(0, 200, 80)):
    ov = frame.copy()
    cv2.rectangle(ov, (x1, y1), (x2, y2), (15, 15, 15), -1)
    cv2.addWeighted(ov, alpha, frame, 1-alpha, 0, frame)
    cv2.rectangle(frame, (x1, y1), (x2, y2), border, 2)


def draw_crosshair(frame, x: float, y: float, shooting: bool):
    xi, yi = int(x), int(y)
    color  = (0, 60, 255) if shooting else (0, 240, 60)
    size   = 30
    thick  = 3
    gap    = 8
    cv2.circle(frame, (xi, yi), size, color, thick)
    cv2.line(frame, (xi-size-6, yi),   (xi-gap, yi),   color, thick)
    cv2.line(frame, (xi+gap,    yi),   (xi+size+6, yi), color, thick)
    cv2.line(frame, (xi, yi-size-6),   (xi, yi-gap),   color, thick)
    cv2.line(frame, (xi, yi+gap),      (xi, yi+size+6), color, thick)
    cv2.circle(frame, (xi, yi), 3, color, -1)
    if shooting:
        cv2.circle(frame, (xi, yi), size + 14, (30, 80, 255), 2)


def draw_hand_indicator(frame, hand_visible: bool, pinching: bool,
                        voice_status: str, voice_flash: bool):
    """Bottom-right corner — hand + voice status."""
    h, w  = frame.shape[:2]
    bx    = w - 310
    by    = h - 115
    _panel(frame, bx-10, by-10, w-8, h-48,
           alpha=0.70, border=(70,70,70))

    # Hand dot
    dot = (0, 255, 100) if hand_visible else (80, 80, 80)
    cv2.circle(frame, (bx+8, by+8), 8, dot, -1)
    label = "HAND DETECTED" if hand_visible else "NO HAND"
    cv2.putText(frame, label, (bx+24, by+14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, dot, 1)

    if pinching:
        cv2.putText(frame, "  PINCH SHOOT!", (bx+24, by+34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 80, 255), 2)

    # Voice status
    v_color = (0, 200, 255) if voice_flash else (160, 160, 160)
    cv2.putText(frame, voice_status[:38], (bx+2, by+56),
                cv2.FONT_HERSHEY_SIMPLEX, 0.48, v_color, 1)


def draw_hud(frame, score, high_score, time_left, misses,
             level, combo, fps, voice_flash: bool):
    h, w = frame.shape[:2]

    # Top bar
    _panel(frame, 0, 0, w, 68)
    cv2.putText(frame, f"SCORE  {score:04d}", (18, 46),
                cv2.FONT_HERSHEY_DUPLEX, 1.25, (60, 255, 120), 2)
    cv2.putText(frame, f"BEST  {high_score:04d}", (260, 46),
                cv2.FONT_HERSHEY_DUPLEX, 1.0, (255, 210, 0), 2)
    t_color = (60, 255, 255) if time_left > 15 else (0, 60, 255)
    cv2.putText(frame, f"{int(time_left):02d}s", (w//2-42, 50),
                cv2.FONT_HERSHEY_DUPLEX, 1.5, t_color, 3)
    cv2.putText(frame, f"LVL {level}", (w//2+90, 46),
                cv2.FONT_HERSHEY_DUPLEX, 1.0, (255, 150, 30), 2)
    cv2.putText(frame, f"MISS {misses:02d}", (w-280, 46),
                cv2.FONT_HERSHEY_DUPLEX, 1.0, (120, 120, 255), 2)
    cv2.putText(frame, f"{fps:.0f}fps", (w-110, 46),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (160, 255, 255), 1)

    # Combo badge
    if combo >= 2:
        cx_color = (0, 200, 255) if combo < 5 else (0, 80, 255)
        _panel(frame, 10, h-110, 260, h-58, alpha=0.72, border=cx_color)
        cv2.putText(frame, f"x{combo}  COMBO!", (20, h-70),
                    cv2.FONT_HERSHEY_DUPLEX, 1.1, cx_color, 3)

    # Voice flash banner (briefly shows "VOICE SHOOT!")
    if voice_flash:
        _panel(frame, w//2-180, h-110, w//2+180, h-58,
               alpha=0.75, border=(0,80,255))
        cv2.putText(frame, "  VOICE SHOOT!", (w//2-160, h-70),
                    cv2.FONT_HERSHEY_DUPLEX, 1.1, (40, 120, 255), 3)

    # Bottom bar
    _panel(frame, 0, h-38, w, h, alpha=0.70, border=(60,60,60))
    cv2.putText(frame,
                "PINCH = Shoot  |  Say 'SHOOT'/'FIRE' = Voice Shoot  |  Q/ESC = Quit  |  R = Restart",
                (14, h-12), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (200,200,200), 1)


def draw_menu(frame, high_score: int, hand_visible: bool, voice_status: str):
    h, w = frame.shape[:2]
    _panel(frame, w//2-400, h//2-210, w//2+400, h//2+250, alpha=0.80)

    cv2.putText(frame, "DUCK  HUNT", (w//2-295, h//2-125),
                cv2.FONT_HERSHEY_DUPLEX, 3.0, (40,230,80), 7)
    cv2.putText(frame, "DUCK  HUNT", (w//2-295, h//2-125),
                cv2.FONT_HERSHEY_DUPLEX, 3.0, (60,255,110), 4)

    cv2.putText(frame, "Hand Gesture + Voice Edition",
                (w//2-225, h//2-55),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200,200,200), 2)

    cv2.putText(frame, f"High Score :  {high_score}",
                (w//2-160, h//2+20),
                cv2.FONT_HERSHEY_DUPLEX, 1.1, (255,210,0), 2)

    if hand_visible:
        cv2.putText(frame, "Hand detected — Starting...",
                    (w//2-220, h//2+95),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (60,255,120), 2)
    else:
        pulse = int(128 + 127*math.sin(time.time()*3))
        cv2.putText(frame, "Show your HAND to begin",
                    (w//2-215, h//2+95),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,pulse,200), 2)

    cv2.putText(frame, voice_status,
                (w//2-240, h//2+148),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0,200,255), 1)

    cv2.putText(frame, "Pinch = Shoot  |  Say 'shoot'/'fire' = Voice  |  Q/ESC = Quit",
                (w//2-295, h//2+198),
                cv2.FONT_HERSHEY_SIMPLEX, 0.78, (170,170,170), 1)


def draw_game_over(frame, score, misses, high_score, new_record, accuracy):
    h, w = frame.shape[:2]
    _panel(frame, w//2-400, h//2-240, w//2+400, h//2+280, alpha=0.84)

    cv2.putText(frame, "GAME  OVER", (w//2-265, h//2-155),
                cv2.FONT_HERSHEY_DUPLEX, 2.8, (0,40,220), 6)
    cv2.putText(frame, "GAME  OVER", (w//2-265, h//2-155),
                cv2.FONT_HERSHEY_DUPLEX, 2.8, (30,80,255), 3)

    if new_record:
        pulse = int(180 + 75*math.sin(time.time()*5))
        cv2.putText(frame, "NEW HIGH SCORE!", (w//2-215, h//2-90),
                    cv2.FONT_HERSHEY_DUPLEX, 1.3, (0,pulse,255), 3)

    for i, (txt, col) in enumerate([
        (f"Score      :  {score}",        (60,255,110)),
        (f"Best       :  {high_score}",   (255,210,0)),
        (f"Misses     :  {misses}",        (120,120,255)),
        (f"Accuracy   :  {accuracy:.1f}%",(0,220,220)),
    ]):
        cv2.putText(frame, txt, (w//2-200, h//2-20+i*58),
                    cv2.FONT_HERSHEY_DUPLEX, 1.1, col, 2)

    cv2.putText(frame, "R = Play Again     Q / ESC = Quit",
                (w//2-245, h//2+240),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (210,210,210), 2)

# ─────────────────────────────────────────────
#  HAND TRACKER
# ─────────────────────────────────────────────
class HandTracker:
    def __init__(self):
        self._ensure_model()
        opts = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(
                model_asset_path=Config.MODEL_PATH),
            running_mode=mp.tasks.vision.RunningMode.VIDEO
        )
        self.landmarker  = mp.tasks.vision.HandLandmarker.create_from_options(opts)
        self.ImageFormat = mp.ImageFormat

    @staticmethod
    def _ensure_model():
        if not os.path.exists(Config.MODEL_PATH):
            print("[HandTracker] Downloading MediaPipe model...")
            urllib.request.urlretrieve(Config.MODEL_URL, Config.MODEL_PATH)
            print("[HandTracker] Done.")

    def process(self, bgr_frame, timestamp_ms: int):
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        img = mp.Image(image_format=self.ImageFormat.SRGB, data=rgb)
        return self.landmarker.detect_for_video(img, timestamp_ms)

    @staticmethod
    def cursor_pos(landmarks, w, h):
        tip = landmarks[8]
        return tip.x * w, tip.y * h

    @staticmethod
    def is_pinching(landmarks) -> bool:
        t, i = landmarks[4], landmarks[8]
        return math.hypot(t.x - i.x, t.y - i.y) < Config.PINCH_THRESHOLD

# ─────────────────────────────────────────────
#  GAME SESSION
# ─────────────────────────────────────────────
class GameSession:
    def __init__(self, w, h):
        self.score        = 0
        self.misses       = 0
        self.total_shots  = 0
        self.level        = 1
        self.combo        = 0
        self.last_hit_t   = 0.0
        self.ducks        = [Duck(w, h) for _ in range(Config.MAX_DUCKS)]
        self.floats: list[FloatingText] = []
        self.start_time   = time.time()
        self.last_shot_t  = 0.0
        self.shooting_fx  = False
        self.fx_timer     = 0.0
        self.prev_cursor  = np.array([w/2.0, h/2.0])
        self.voice_flash  = False
        self.vflash_timer = 0.0

    @property
    def time_left(self) -> float:
        return max(0.0, Config.GAME_DURATION - (time.time()-self.start_time))

    @property
    def accuracy(self) -> float:
        if self.total_shots == 0:
            return 0.0
        return (self.score / self.total_shots) * 100.0

    def update_level(self):
        new_lv = min(Config.MAX_LEVEL,
                     1 + self.score // Config.LEVEL_SCORE_STEP)
        if new_lv != self.level:
            self.level = new_lv
            for d in self.ducks:
                d.speed_bonus = new_lv - 1

# ─────────────────────────────────────────────
#  SHOOT LOGIC (shared by pinch + voice)
# ─────────────────────────────────────────────
def do_shoot(session: GameSession, cursor, now: float, voice: bool = False):
    """Execute one shot at cursor position. voice=True shows voice flash."""
    _beep(Config.SHOOT_FREQ, Config.SHOOT_DUR)
    session.last_shot_t = now
    session.shooting_fx = True
    session.fx_timer    = now
    session.total_shots += 1

    if voice:
        session.voice_flash  = True
        session.vflash_timer = now

    hit = False
    for duck in session.ducks:
        if duck.alive and duck.check_hit(cursor[0], cursor[1]):
            duck.alive     = False
            duck.hit       = True
            duck.hit_timer = now
            if (now - session.last_hit_t) < Config.COMBO_TIMEOUT:
                session.combo += 1
            else:
                session.combo = 1
            session.last_hit_t = now
            pts = session.combo
            session.score += pts
            _beep(Config.HIT_FREQ, Config.HIT_DUR)
            lbl = f"+{pts}" if pts < 2 else f"+{pts}  x{session.combo}!"
            col = (0, 255, 100) if pts < 3 else (0, 80, 255)
            session.floats.append(
                FloatingText(int(cursor[0]), int(cursor[1]), lbl, col))
            hit = True
            break

    if not hit:
        session.combo   = 0
        session.misses += 1

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
def run():
    tracker    = HandTracker()
    hs_manager = HighScoreManager(Config.HIGHSCORE_FILE)
    bg         = AnimatedBackground(Config.WIDTH, Config.HEIGHT)
    voice      = VoiceController()     # starts background thread

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)

    W, H       = Config.WIDTH, Config.HEIGHT
    state      = GameState.MENU
    session    = GameSession(W, H)
    new_record = False
    fps_times: list[float] = []

    print("─" * 60)
    print("  🦆  Duck Hunt — Hand Gesture + Voice Edition  v4.0")
    print("─" * 60)
    print("  Webcam   : INVISIBLE (hand tracking only)")
    print("  Shoot    : Pinch gesture  OR  Say 'shoot' / 'fire'")
    print("  Display  : Animated scenic background")
    print("  Q / ESC → Quit  |  R → Restart")
    print("─" * 60)

    while cap.isOpened():
        t0 = time.time()

        ret, cam_frame = cap.read()
        if not ret:
            continue
        cam_frame = cv2.flip(cam_frame, 1)

        # ── Hand tracking ──
        ts_ms    = int(cv2.getTickCount() / cv2.getTickFrequency() * 1000)
        results  = tracker.process(cam_frame, ts_ms)

        hand_visible = False
        pinching     = False
        raw_cursor   = np.array([W/2.0, H/2.0])

        if results.hand_landmarks:
            lm           = results.hand_landmarks[0]
            raw_cursor   = np.array(tracker.cursor_pos(lm, W, H))
            pinching     = tracker.is_pinching(lm)
            hand_visible = True

        session.prev_cursor += Config.SMOOTH_ALPHA * (
            raw_cursor - session.prev_cursor)
        cursor = session.prev_cursor

        now = time.time()

        # ── Check voice command ──
        voice_shoot = voice.check_shoot()

        # ── Scenic frame ──
        frame = bg.render()

        # ── Voice flash timeout ──
        if session.voice_flash and (now - session.vflash_timer) > 0.5:
            session.voice_flash = False

        # ══════════════════════════
        #  MENU
        # ══════════════════════════
        if state == GameState.MENU:
            draw_menu(frame, hs_manager.high_score,
                      hand_visible, voice.status)
            draw_hand_indicator(frame, hand_visible, pinching,
                                voice.status, False)
            if hand_visible:
                state   = GameState.PLAYING
                session = GameSession(W, H)

        # ══════════════════════════
        #  PLAYING
        # ══════════════════════════
        elif state == GameState.PLAYING:
            if session.time_left <= 0:
                new_record = hs_manager.update(session.score)
                state = GameState.GAME_OVER
            else:
                shoot_ready = (now - session.last_shot_t) > Config.SHOOT_COOLDOWN

                # Pinch shoot
                if pinching and shoot_ready:
                    do_shoot(session, cursor, now, voice=False)

                # Voice shoot
                elif voice_shoot and shoot_ready:
                    do_shoot(session, cursor, now, voice=True)

                if session.shooting_fx and (now - session.fx_timer) > 0.14:
                    session.shooting_fx = False

                # Duck movement
                for duck in session.ducks:
                    duck.move()
                    if duck.is_off_screen():
                        if duck.alive:
                            session.misses += 1
                            session.combo   = 0
                        duck.reset()
                    elif duck.hit and (now - duck.hit_timer) > 0.45:
                        duck.reset()

                session.update_level()

                for duck in session.ducks:
                    duck.draw(frame)

                session.floats = [f for f in session.floats if f.alive]
                for ft in session.floats:
                    ft.draw(frame)

                draw_crosshair(frame, cursor[0], cursor[1], session.shooting_fx)

                fps_avg = (sum(fps_times[-30:]) / len(fps_times[-30:])) \
                          if fps_times else 0.033
                fps = 1.0 / fps_avg if fps_avg > 0 else 0

                draw_hud(frame, session.score, hs_manager.high_score,
                         session.time_left, session.misses,
                         session.level, session.combo, fps,
                         session.voice_flash)
                draw_hand_indicator(frame, hand_visible, pinching,
                                    voice.status, session.voice_flash)

        # ══════════════════════════
        #  GAME OVER
        # ══════════════════════════
        elif state == GameState.GAME_OVER:
            for duck in session.ducks:
                duck.draw(frame)
            draw_game_over(frame, session.score, session.misses,
                           hs_manager.high_score, new_record, session.accuracy)
            draw_hand_indicator(frame, hand_visible, pinching,
                                voice.status, False)

        cv2.imshow(Config.WINDOW_TITLE, frame)

        fps_times.append(time.time() - t0)
        if len(fps_times) > 60:
            fps_times.pop(0)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break
        if key == ord('r') and state == GameState.GAME_OVER:
            session    = GameSession(W, H)
            new_record = False
            state      = GameState.PLAYING

    voice.stop()
    cap.release()
    cv2.destroyAllWindows()
    print(f"\n[Game] Final Score : {session.score}")
    print(f"[Game] High Score  : {hs_manager.high_score}")
    print(f"[Game] Accuracy    : {session.accuracy:.1f}%")


if __name__ == "__main__":
    run()