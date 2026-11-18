"""Step 1: turn your notes and device manuals into short knowledge-base passages.

Put files in:
  data/sources/notes/     your own notes (.md, .txt)
  data/sources/manuals/   device manuals (.md, .txt; .pdf/.docx/.pptx/.html are
                          converted with the `markitdown` command if it is on PATH)

Output: data/kb/source_passages.jsonl  ({"text", "source", "kind"})
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from lib.common import SOURCE_PASSAGES, SOURCES, cfg, ensure_dirs, write_jsonl
from lib.kbtext import ascii_fold

TEXT_EXT = {".md", ".txt"}
CONVERT_EXT = {".pdf", ".docx", ".pptx", ".html", ".htm", ".xlsx", ".epub"}


def load_text(path: Path):
    if path.suffix.lower() in TEXT_EXT:
        return path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() in CONVERT_EXT:
        exe = shutil.which("markitdown")
        if not exe:
            print(f"  skip {path.name}: install markitdown or convert it to .md first")
            return None
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.md"
            subprocess.run([exe, str(path), "-o", str(out)], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if not out.exists() or out.stat().st_size == 0:
                print(f"  skip {path.name}: no text extracted (scanned PDF? see README)")
                return None
            return out.read_text(encoding="utf-8", errors="ignore")
    return None


def strip_markdown(md: str) -> str:
    md = re.sub(r"```.*?```", " ", md, flags=re.S)          # code blocks
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md)            # images
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)         # links -> text
    md = re.sub(r"<[^>]+>", " ", md)                         # html tags
    md = re.sub(r"^\s*[#>*\-+|]+\s*", "", md, flags=re.M)    # headings, bullets, quotes, tables
    md = re.sub(r"[|*_`#]+", " ", md)
    md = re.sub(r"\n\s*\n", "\n\n", md)
    return md


def chunk(text: str, title: str):
    """Word chunks with overlap, each prefixed with its source title (helps retrieval)."""
    words = ascii_fold(text).split()
    size, overlap = cfg.CHUNK_WORDS, cfg.CHUNK_OVERLAP_WORDS
    step = max(1, size - overlap)
    for start in range(0, max(1, len(words) - overlap), step):
        piece = words[start:start + size]
        if len(piece) < 12:
            continue
        yield f"{title}: " + " ".join(piece)


def main():
    ensure_dirs()
    rows = []
    for kind in ("notes", "manuals"):
        folder = SOURCES / kind
        files = sorted(p for p in folder.rglob("*") if p.is_file())
        print(f"{kind}: {len(files)} files in {folder}")
        for p in files:
            raw = load_text(p)
            if not raw:
                continue
            title = ascii_fold(p.stem.replace("_", " ").replace("-", " "))
            n0 = len(rows)
            for c in chunk(strip_markdown(raw), title):
                rows.append({"text": c, "source": str(p.relative_to(SOURCES)), "kind": kind})
            print(f"  {p.name}: {len(rows) - n0} passages")
    write_jsonl(SOURCE_PASSAGES, rows)
    print(f"wrote {len(rows)} passages -> {SOURCE_PASSAGES}")


if __name__ == "__main__":
    main()
