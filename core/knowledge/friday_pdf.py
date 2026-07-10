"""
friday_pdf.py — Friday 3.0
Read a PDF, summarise it with her LLM, and save a Google-Keep-style note into her
Obsidian vault: a short title, a TL;DR, and key-point bullets. The note is linked
into her knowledge graph and embedded, so it also feeds her local reasoning.

  pdf_to_note(path) -> dict        # extract -> summarise -> save note
  summarize(text)   -> str         # markdown note from raw text
  CLI:  python core/friday_pdf.py <file.pdf>
"""

import re
import sys
import logging
from pathlib import Path

log = logging.getLogger("friday.pdf")

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

_CHUNK_CHARS = 6000
_MAX_CHUNKS  = 12      # cap very long PDFs so summarisation stays bounded

_NOTE_SYSTEM = (
    "You are Friday turning a document into a concise, useful study note. "
    "Output GitHub-flavored markdown ONLY, in exactly this shape:\n"
    "# <short descriptive title>\n\n"
    "**TL;DR:** <one or two sentence summary>\n\n"
    "## Key points\n- <specific point>\n- <specific point>\n"
    "(4-8 bullets, concrete, no filler)\n\n"
    "Add a '## Action items' section with bullets only if the document implies tasks. "
    "No preamble, no 'here is your note' — output the note directly."
)


# ── extraction ──────────────────────────────────────────────────────────────--
def extract_text(pdf_path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(pdf_path))
    parts = []
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        if t.strip():
            parts.append(t)
    return "\n".join(parts).strip()


def _chunks(text: str, size: int = _CHUNK_CHARS) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)] or [text]


# ── summarisation (via the Intelligence OS — same cognition stack as voice) ─────
def summarize(text: str) -> str:
    from core.intelligence.service import think_text
    parts = _chunks(text)

    if len(parts) == 1:
        return think_text(
            f"{_NOTE_SYSTEM}\n\nTurn this document into the note.\n\n"
            f"Document:\n{parts[0]}",
            task="summarize",
        )

    # map-reduce for long documents
    partials = []
    for i, chunk in enumerate(parts[:_MAX_CHUNKS], 1):
        s = think_text(
            f"Summarize section {i} into 3-5 key bullet points.\n\n"
            f"Section:\n{chunk}",
            task="summarize",
        )
        partials.append(s)
    combined = "\n".join(partials)
    return think_text(
        f"{_NOTE_SYSTEM}\n\nCombine these section notes into one clean note.\n\n"
        f"Notes:\n{combined}",
        task="summarize",
    )


def _title_from(md: str, fallback: str) -> str:
    m = re.search(r"(?m)^#\s+(.+)$", md)
    return (m.group(1).strip() if m else fallback)[:120]


# ── pipeline ────────────────────────────────────────────────────────────────--
def pdf_to_note(pdf_path) -> dict:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    text = extract_text(pdf_path)
    if len(text) < 30:
        raise ValueError(
            "No extractable text — this looks like a scanned/image PDF (OCR not wired in)."
        )

    note_md = summarize(text)
    title   = _title_from(note_md, pdf_path.stem)

    # Save into the vault: linked into the graph + FAISS-embedded (feeds local QA).
    from core.knowledge.friday_world import get_world, WorldEntry
    entry = WorldEntry(
        source    = f"pdf:{pdf_path.name}",
        category  = "note",
        title     = title,
        content   = note_md,
        relevance = 0.7,
    )
    get_world()._store_entries([entry])
    log.info("Saved PDF note '%s' (%d chars source)", title, len(text))
    return {"title": title, "chars": len(text), "note": note_md, "source": pdf_path.name}


# ── CLI ───────────────────────────────────────────────────────────────────────-
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    if len(sys.argv) < 2:
        print("usage: python core/friday_pdf.py <file.pdf>")
        sys.exit(1)
    res = pdf_to_note(sys.argv[1])
    print(f"\n=== NOTE: {res['title']}  ({res['chars']} chars source) ===\n")
    print(res["note"])
