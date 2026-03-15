# 🦆 Duck Hunt — Hand Gesture + Voice Control Edition

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-4.x-green?style=for-the-badge&logo=opencv&logoColor=white)
![MediaPipe](https://img.shields.io/badge/MediaPipe-Hand%20Tracking-orange?style=for-the-badge)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Mac%20%7C%20Linux-lightgrey?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)

**A real-time hand gesture + voice controlled duck shooting game built entirely in Python.**  
No mouse. No keyboard. Just your hand and your voice.

</div>

---

## 📌 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Tech Stack](#-tech-stack)
- [How It Works](#-how-it-works)
- [Installation](#-installation)
- [How to Play](#-how-to-play)
- [Project Structure](#-project-structure)
- [Game Mechanics](#-game-mechanics)
- [Screenshots](#-screenshots)
- [Future Scope](#-future-scope)
- [Author](#-author)

---

## 🎯 Overview

Duck Hunt is a computer vision project that lets you play a duck shooting game using **only hand gestures and voice commands** — no traditional input devices required.

Your webcam silently tracks your hand in the background. The screen displays a fully animated scenic game world — sky, clouds, trees, birds, pond — with no webcam feed visible. This makes it ideal for demo recordings and presentations.

> **"Move your hand to aim. Pinch to shoot. Say 'fire' to shoot. No mouse needed."**

This project was built to demonstrate real-world application of:
- Real-time computer vision with MediaPipe and OpenCV
- Gesture recognition using hand landmark geometry
- Voice command integration using SpeechRecognition
- Python software architecture using OOP and threading

---

## ✨ Features

| Feature | Description |
|---|---|
| 🖐️ **Hand Gesture Aiming** | Index fingertip (landmark #8) maps to crosshair position in real time |
| 🤏 **Pinch to Shoot** | Euclidean distance between thumb and index tip triggers shoot event |
| 🎤 **Voice Command** | Say **"shoot"**, **"fire"**, **"bang"**, or **"hit"** to trigger shot |
| 🌄 **Animated Scene** | Fully animated background — drifting clouds, flying birds, rippling pond, moving sun |
| 🦆 **Full Body Hit Detection** | Hitting any part of the duck (beak, head, wing, body) registers as a hit |
| 💥 **Explosion + Particles** | Feather particle burst + expanding explosion ring on every kill |
| 🔢 **Combo System** | Hit ducks quickly in succession for multiplier bonus (+2, +3, +4...) |
| 📈 **Difficulty Scaling** | Ducks get faster every 5 points — up to Level 5 |
| 🏆 **High Score Persistence** | Best score saved to `highscore.json` across sessions |
| 📊 **Accuracy Tracking** | Shots fired vs hits — shown on Game Over screen |
| 🎬 **Showcase Ready** | No webcam feed on screen — clean professional display for recordings |

---

## 🛠 Tech Stack

```
Language     : Python 3.10+
CV Library   : OpenCV (cv2)         — frame rendering, drawing, display
Hand Tracking: MediaPipe            — 21-point hand landmark detection
Voice Input  : SpeechRecognition    — Google Speech API transcription
Audio Backend: sounddevice          — microphone recording (PyAudio-free)
Array Ops    : NumPy                — cursor smoothing, audio processing
Threading    : Python threading     — non-blocking voice listener
```

### Why these libraries?

- **MediaPipe** was chosen over other hand tracking solutions for its accuracy, speed, and Google-maintained support. It detects 21 landmarks per hand at ~30 FPS on a standard webcam.
- **sounddevice** was used instead of PyAudio because PyAudio does not have pre-built wheels for Python 3.13, making it impossible to install via pip on newer Python versions.
- **OpenCV** handles all rendering — the entire game UI, animations, ducks, HUD, and effects are drawn directly onto NumPy arrays using OpenCV drawing primitives.

---

## ⚙️ How It Works

### Hand Gesture Control

```
Webcam Feed (640x480, hidden)
        ↓
MediaPipe HandLandmarker (VIDEO mode)
        ↓
Extract Landmark #8 (Index Fingertip) → map to screen coords (1280x720)
        ↓
Exponential Moving Average smoothing (α = 0.4)
        ↓
Crosshair follows finger position
```

### Shoot Detection (Pinch)

```
Thumb Tip  (landmark #4)
Index Tip  (landmark #8)
        ↓
Euclidean distance = √((x₁-x₂)² + (y₁-y₂)²)
        ↓
distance < 0.06 threshold → SHOOT triggered
```

### Voice Command Flow

```
sounddevice → records 2s audio chunk (16kHz, mono)
        ↓
RMS silence check → skip if background noise only
        ↓
in-memory WAV → SpeechRecognition → Google Speech API
        ↓
"shoot" / "fire" / "bang" / "hit" detected → shoot flag set
        ↓
Game loop picks flag next frame → fires at current cursor position
```

### Full Body Hit Detection

```
For each duck, cursor point (px, py) is tested against:

  1. Body ellipse  → ((px-cx)/36)² + ((py-cy)/22)² ≤ 1
  2. Head circle   → √((px-hx)² + (py-hy)²) ≤ 17
  3. Beak triangle → cv2.pointPolygonTest()
  4. Wing region   → bounding box check

Any zone hit → BOOM triggered at impact point
```

---

## 💻 Installation

### Prerequisites

- Python **3.10 or higher** (tested on 3.13)
- Webcam (built-in or USB)
- Microphone (for voice commands)
- Internet connection (for Google Speech API + MediaPipe model download)

### Step 1 — Clone the Repository

```bash
git clone https://github.com/master1556/shootingduck.git
cd shootingduck
```

### Step 2 — Install Dependencies

```bash
pip install opencv-python mediapipe numpy sounddevice SpeechRecognition
```

> **Windows users:** If you face issues with `sounddevice`, try:
> ```bash
> pip install sounddevice --pre
> ```

### Step 3 — Run the Game

```bash
python duck_shooting_game_v1_py313.py
```

On first run, the MediaPipe hand landmarker model (~9MB) downloads automatically.

---

## 🎮 How to Play

| Action | Control |
|---|---|
| **Aim** | Move your hand in front of the webcam |
| **Shoot (gesture)** | Pinch — bring index finger and thumb together |
| **Shoot (voice)** | Say **"shoot"**, **"fire"**, **"bang"**, or **"hit"** |
| **Quit** | Press `Q` or `ESC` |
| **Restart** | Press `R` on Game Over screen |

### Tips

- Keep your hand clearly visible to the webcam — good lighting helps
- Pinch firmly and release to avoid accidental repeat shots
- For voice: speak clearly and at a normal volume
- Hit ducks quickly back-to-back to build your combo multiplier
- Ducks speed up every 5 points — stay focused at higher levels

---

## 📁 Project Structure

```
shootingduck/
│
├── duck_shooting_game_v4_py313.py   ← Main game (all-in-one)
│
├── requirements.txt                  ← pip dependencies
├── highscore.json                    ← Auto-created on first run
├── hand_landmarker.task              ← Auto-downloaded on first run
│
├── README.md                         ← This file
└── demo.gif                          ← Gameplay demo
```

### Key Classes

| Class | Responsibility |
|---|---|
| `Config` | All game constants in one place — tweak values here |
| `AnimatedBackground` | Renders scenic background every frame (no webcam) |
| `Duck` | Duck movement, wing animation, full-body hit detection |
| `HandTracker` | MediaPipe setup, landmark extraction, pinch detection |
| `VoiceController` | Background thread mic listener using sounddevice |
| `GameSession` | All mutable state for one round (score, combo, ducks) |
| `HighScoreManager` | Loads and saves best score to JSON |
| `FloatingText` | Animated "+1", "+3 x3!" popups on kill |

---

## 🎲 Game Mechanics

### Scoring
- Each duck killed = **+1 point base**
- Combo multiplier applies if next duck hit within **2 seconds**
- Example: 3 quick kills = +1, +2, +3 = **6 points total**

### Difficulty Levels
| Level | Unlocks at | Duck Speed |
|---|---|---|
| 1 | Start | Base |
| 2 | 5 points | Base + 1 |
| 3 | 10 points | Base + 2 |
| 4 | 15 points | Base + 3 |
| 5 | 20 points | Base + 4 |

### Hit Zones
Every duck has **4 hittable zones** — aim anywhere on the duck:
- 🟢 Body (ellipse)
- 🔵 Head (circle)
- 🟡 Beak (triangle polygon)
- 🟠 Wing area (bounding box)

---

## 🚀 Future Scope

- [ ] **Multiplayer** — Two hands = two players simultaneously
- [ ] **Duck sprites** — Replace OpenCV drawings with PNG sprite images
- [ ] **Sound effects** — Gunshot and quack audio files
- [ ] **Web version** — Flask + WebRTC for browser-based play
- [ ] **Leaderboard** — SQLite database for multi-session score history
- [ ] **Custom gesture modes** — Gun pose, finger gun, open palm
- [ ] **Offline voice** — Vosk for local speech recognition (no internet needed)

---

## 🧠 What I Learned

- Real-time video processing pipeline design at 30 FPS
- MediaPipe hand landmark coordinate system and normalisation
- Euclidean geometry for gesture recognition (pinch distance)
- Polygon-based collision detection using OpenCV primitives
- Python threading for non-blocking microphone listening
- Cross-platform audio handling (sounddevice vs PyAudio)
- Game loop architecture — state machines, delta time, FPS tracking

---

## 👤 Author

**AK**
MBA Student — Andhra University CDOE (4th Semester)
QA Engineer & Automation Developer

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-blue?style=flat&logo=linkedin)](https://www.linkedin.com/in/akshaykombathula)
[![GitHub](https://img.shields.io/badge/GitHub-Follow-black?style=flat&logo=github)](https://github.com/master1556)

---

## 📄 License

This project is licensed under the MIT License.  
Free to use, modify, and distribute with attribution.

---

<div align="center">

**Built with Python, OpenCV, MediaPipe, and a pinch of creativity 🤏**

⭐ Star this repo if you found it useful!

</div>
