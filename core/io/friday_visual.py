"""
friday_visual.py — Friday 3.0
Visual answers. When a question is better answered with something to SEE, Friday
opens the right visual in the browser alongside her spoken/text answer.

Built-in handlers (first match wins):
  • places            "where is / map of / how big is / directions to X"  -> map
  • today's news      "today's / latest news (about X)"                    -> news
  • images            "show me / picture of / what does X look like"       -> image search
  • weather           "weather in X"                                       -> weather
  • finance           "X stock price"                                      -> finance
  • video             "video of X / show me a video of X"                  -> YouTube

Extensible: append a (kind, regex, builder) entry to _HANDLERS. `builder(subject)`
returns (url, caption). Capture the subject in a named group `q`.
"""

import re
import sys
import logging
import webbrowser
from urllib.parse import quote_plus
from typing import Optional

log = logging.getLogger("friday.visual")

_HERE = __import__("pathlib").Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


# ── URL builders ────────────────────────────────────────────────────────────--
def _google(q: str) -> str:   return f"https://www.google.com/search?q={quote_plus(q)}"
def _maps(p: str) -> str:     return f"https://www.google.com/maps/search/?api=1&query={quote_plus(p)}"
def _images(q: str) -> str:   return f"https://www.google.com/search?tbm=isch&q={quote_plus(q)}"
def _youtube(q: str) -> str:  return f"https://www.youtube.com/results?search_query={quote_plus(q)}"
def _news(topic: str) -> str:
    return "https://news.google.com/" if not topic else \
           f"https://news.google.com/search?q={quote_plus(topic)}"


def _clean(subject: str) -> str:
    s = (subject or "").strip().rstrip("?.!,").strip()
    s = re.sub(r"\b(please|for me|right now|now)\b\s*$", "", s, flags=re.I).strip()
    s = re.sub(r"^(the|a|an)\s+", "", s, flags=re.I).strip()
    return s


# ── handlers: (kind, pattern, builder(subject) -> (url, caption)) ───────────────
_HANDLERS = [
    ("video",  r"\b(?:show me a |a )?videos? (?:of|about|on) (?P<q>.+)",
     lambda s: (_youtube(s), f"Pulling up videos of {s}.")),

    ("news",   r"\b(?:today'?s|latest|breaking|recent) news(?:\s+(?:about|on|regarding)\s+(?P<q>.+))?",
     lambda s: (_news(s), f"Latest news{(' on ' + s) if s else ' for today'}.")),
    ("news",   r"\bnews (?:about|on|regarding) (?P<q>.+)",
     lambda s: (_news(s), f"Latest news on {s}.")),
    ("news",   r"\b(?:what'?s happening|what is happening|headlines)(?:\s+(?:in|with)\s+(?P<q>.+))?",
     lambda s: (_news(s), f"Headlines{(' in ' + s) if s else ''}.")),

    ("weather", r"\bweather (?:in|at|for) (?P<q>.+)",
     lambda s: (_google(f"weather {s}"), f"Weather for {s}.")),
    ("weather", r"\b(?:what'?s|hows|how is) the weather(?:\s+(?:in|at|for)\s+(?P<q>.+))?",
     lambda s: (_google(f"weather {s}".strip()), f"Weather{(' in ' + s) if s else ''}.")),

    ("finance", r"\bstock price (?:of|for) (?P<q>.+)",
     lambda s: (_google(f"{s} stock price"), f"Stock price for {s}.")),
    ("finance", r"\b(?P<q>[\w .&-]{2,40}?) stock price\b",
     lambda s: (_google(f"{s} stock price"), f"Stock price for {s}.")),

    ("image",  r"\b(?:show me (?:a |an )?(?:picture|image|photo)s? of|"
               r"picture of|pictures of|images? of|photos? of) (?P<q>.+)",
     lambda s: (_images(s), f"Showing images of {s}.")),
    ("image",  r"\bwhat (?:do|does) (?P<q>.+?) look like",
     lambda s: (_images(s), f"Here's what {s} looks like.")),

    ("map",    r"\bmap of (?P<q>.+)",
     lambda s: (_maps(s), f"Opening a map of {s}.")),
    ("map",    r"\b(?:where (?:is|are)|location of) (?P<q>.+)",
     lambda s: (_maps(s), f"Showing {s} on the map.")),
    ("map",    r"\bdirections? to (?P<q>.+)",
     lambda s: (_maps(s), f"Directions to {s}.")),
    ("map",    r"\bhow (?:big|large|far) (?:is|are) (?P<q>.+)",
     lambda s: (_maps(s), f"Here's {s} on the map for scale.")),
]


def visual_answer(query: str, open_browser: bool = True) -> Optional[dict]:
    """Detect a visual intent and (optionally) open the visual. Returns details or None."""
    if not query or not query.strip():
        return None
    ql = query.lower()
    for kind, pattern, build in _HANDLERS:
        m = re.search(pattern, ql)
        if not m:
            continue
        # extract subject from the ORIGINAL query (preserve case) if captured
        subj = ""
        if "q" in m.groupdict() and m.group("q") is not None:
            subj = _clean(query[m.start("q"):m.end("q")])
        url, caption = build(subj)
        if open_browser:
            try:
                webbrowser.open(url, new=2)
            except Exception as e:
                log.debug("browser open failed: %s", e)
        log.info("Visual answer [%s]: %s", kind, url)
        return {"kind": kind, "subject": subj, "url": url,
                "caption": caption, "opened": bool(open_browser)}
    return None


def maybe_show(query: str) -> Optional[dict]:
    """Best-effort visual answer for the main answer path (never raises)."""
    try:
        return visual_answer(query, open_browser=True)
    except Exception as e:
        log.debug("visual answer failed: %s", e)
        return None


# ── CLI ───────────────────────────────────────────────────────────────────────-
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    q = " ".join(sys.argv[1:]) or "where is New York City"
    res = visual_answer(q, open_browser=True)
    print(res if res else "(no visual intent detected)")
