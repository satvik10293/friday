"""
setup.py — Friday 3.0
Run this once before launching Friday.
Installs all dependencies and verifies the environment.
Usage: python setup.py
"""

import sys
import subprocess
import os
from pathlib import Path

ROOT = Path(__file__).parent

def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def pip(packages):
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade"] + packages,
        capture_output=False
    )
    return result.returncode == 0

print("""
 ███████╗██████╗ ██╗██████╗  █████╗ ██╗   ██╗
 ██╔════╝██╔══██╗██║██╔══██╗██╔══██╗╚██╗ ██╔╝
 █████╗  ██████╔╝██║██║  ██║███████║ ╚████╔╝
 ██╔══╝  ██╔══██╗██║██║  ██║██╔══██║  ╚██╔╝
 ██║     ██║  ██║██║██████╔╝██║  ██║   ██║
 ╚═╝     ╚═╝  ╚═╝╚═╝╚═════╝ ╚═╝  ╚═╝   ╚═╝
 
 Setup v3.0 — Installing dependencies
""")

# ── 1. Core brain ─────────────────────────────────────────────────────────────
print("[1/7] Core brain dependencies...")
pip([
    "requests",
    "groq",
    "google-generativeai",
    "openai",
])

# ── 2. Memory ─────────────────────────────────────────────────────────────────
print("[2/7] Memory (FAISS + embeddings)...")
pip([
    "faiss-cpu",
    "sentence-transformers",
    "numpy",
])

# ── 3. Voice ──────────────────────────────────────────────────────────────────
print("[3/7] Voice (STT + TTS)...")
pip([
    "faster-whisper",
    "edge-tts",
    "sounddevice",
    "soundfile",
    "pygame",
])

# ── 4. Senses / perception ────────────────────────────────────────────────────
print("[4/7] Senses...")
pip([
    "mss",
    "easyocr",
    "pyperclip",
    "keyboard",
    "psutil",
])

# ── 5. Actions ────────────────────────────────────────────────────────────────
print("[5/7] Actions...")
pip([
    "pyautogui",
    "pygetwindow",
    "pywhatkit",
])

# ── 6. Web / world ────────────────────────────────────────────────────────────
print("[6/7] Web + world...")
pip([
    "duckduckgo-search",
    "flask",
    "flask-cors",
])

# ── 7. Notifications ──────────────────────────────────────────────────────────
print("[7/7] Notifications...")
pip([
    "plyer",
    "win10toast ; sys_platform=='win32'",
])

# ── Create data dirs ──────────────────────────────────────────────────────────
print("\n[Setup] Creating data directories...")
for d in ["data", "data/world", "core/voice"]:
    (ROOT / d).mkdir(parents=True, exist_ok=True)
print("  ✓ data/")
print("  ✓ data/world/")

# ── Check config ──────────────────────────────────────────────────────────────
config = ROOT / "friday_config.json"
if not config.exists():
    print("\n[Setup] friday_config.json not found — creating template...")
    import json
    template = {
        "groq_api_key":        "",
        "groq_model":          "llama-3.3-70b-versatile",
        "groq_fallback_model": "llama-3.1-8b-instant",
        "gemini_api_key":      "",
        "gemini_model":        "gemini-2.0-flash",
        "openai_api_key":      "",
        "openai_model":        "gpt-4o-mini",
        "elevenlabs_api_key":  "",
        "owner_name":          "Satvik",
        "friday_version":      "3.0",
        "voice": {
            "engine":   "edge-tts",
            "voice_id": "en-US-GuyNeural"
        },
        "stt": {
            "model":        "base",
            "device":       "cpu",
            "compute_type": "int8"
        }
    }
    config.write_text(json.dumps(template, indent=2))
    print("  ✓ friday_config.json created")
    print("  ⚠  Add your API keys to friday_config.json before running Friday")
else:
    import json
    try:
        cfg = json.loads(config.read_text())
        keys = {k: bool(v) for k, v in cfg.items() if "api_key" in k}
        print(f"\n[Setup] API keys status: {keys}")
    except Exception:
        pass

# ── Verify critical imports ───────────────────────────────────────────────────
print("\n[Setup] Verifying imports...")
checks = [
    ("requests",             "requests"),
    ("faster_whisper",       "faster-whisper"),
    ("edge_tts",             "edge-tts"),
    ("sounddevice",          "sounddevice"),
    ("flask",                "flask"),
    ("psutil",               "psutil"),
    ("faiss",                "faiss-cpu"),
    ("sentence_transformers","sentence-transformers"),
    ("duckduckgo_search",    "duckduckgo-search"),
]

all_ok = True
for mod, pkg in checks:
    try:
        __import__(mod)
        print(f"  ✓ {pkg}")
    except ImportError:
        print(f"  ✗ {pkg} — run: pip install {pkg}")
        all_ok = False

# ── Done ──────────────────────────────────────────────────────────────────────
print()
if all_ok:
    print("=" * 50)
    print("  Friday 3.0 setup complete.")
    print()
    print("  Next steps:")
    print("  1. Add API keys to friday_config.json")
    print("  2. Run Friday.bat  (voice mode)")
    print("     or: python friday_face.py  (UI mode)")
    print("=" * 50)
else:
    print("=" * 50)
    print("  Setup done with warnings.")
    print("  Fix missing packages above, then run again.")
    print("=" * 50)

input("\nPress Enter to exit...")