"""Athena's simple spoken output (pyttsx3, offline).

The engine initializes lazily on the first speak() — importing this module
used to spin up the SAPI COM engine and audio driver as a side effect,
which ambushed anything that merely imported it.
"""

import pyttsx3

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = pyttsx3.init()
        _engine.setProperty("rate", 170)
    return _engine


def speak(text):
    print(f"\nAthena: {text}\n")
    engine = _get_engine()
    engine.say(text)
    engine.runAndWait()
