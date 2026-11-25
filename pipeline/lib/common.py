"""Paths, config access and small IO helpers shared by every pipeline step."""
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config as cfg  # noqa: E402  (repo-root config.py)


def _load_dotenv(path):
    """KEY=value lines from repo-root .env (API keys). Values in .env win over the shell."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")


_load_dotenv(ROOT / ".env")

if os.environ.get("ESPLLM_DEMO"):  # tiny settings for the plumbing test (00_demo_data.py)
    cfg.VOCAB_SIZE, cfg.DIM, cfg.N_LAYERS, cfg.N_HEADS, cfg.HIDDEN_DIM = 400, 64, 2, 2, 128
    cfg.MAX_SEQ_LEN, cfg.MAX_ITERS, cfg.WARMUP_ITERS, cfg.EVAL_INTERVAL, cfg.EVAL_ITERS = 256, 300, 30, 100, 5
    cfg.BATCH_SIZE, cfg.DROPOUT, cfg.VAL_FRACTION = 16, 0.0, 0.05

# Board: CARDMIND_BOARD (or BOARD in config.py) picks the device matcher, the knowledge cards and the
# default data folder: "cardputer" -> data/, "rlcd" (Waveshare ESP32-S3-RLCD-4.2) -> data_rlcd/.
BOARD = os.environ.get("CARDMIND_BOARD", getattr(cfg, "BOARD", "cardputer"))
cfg.BOARD = BOARD
from .devtext import set_board as _set_board  # noqa: E402
_set_board(BOARD)
if BOARD == "rlcd":
    from . import kbtext as _kbtext  # noqa: E402
    _kbtext.add_stopwords(_kbtext.RLCD_STOPWORDS)

# ESPLLM_DATA lets the demo run in its own folder without touching real data.
DATA = ROOT / os.environ.get("ESPLLM_DATA", "data_rlcd" if BOARD == "rlcd" else "data")
SOURCES = DATA / "sources"           # sources/notes/*, sources/manuals/*
KB_DIR = DATA / "kb"                 # passages (jsonl) for the knowledge base
BATCH_DIR = DATA / "batches"         # Batch API state, manifests, raw results
GEN_DIR = DATA / "generated"         # parsed Claude output
DS_DIR = DATA / "dataset"            # final conversations + token files
TOK_DIR = DATA / "tokenizer"
CKPT_DIR = DATA / "ckpt"
SD_DIR = DATA / "sd_card" / "espllm"  # copy this folder to the SD card root

SOURCE_PASSAGES = KB_DIR / "source_passages.jsonl"
CURRICULUM_PASSAGES = KB_DIR / "curriculum_passages.jsonl"
CONVERSATIONS = GEN_DIR / "conversations.jsonl"

# Special tokens. Order matters: SentencePiece assigns user-defined symbols
# ids 3.. in this order (unk=0, bos=1, eos=2).
SPECIALS = ["<ctx>", "<usr>", "<bot>", "<eot>"]


def ensure_dirs():
    for p in (SOURCES / "notes", SOURCES / "manuals", KB_DIR, BATCH_DIR, GEN_DIR,
              DS_DIR, TOK_DIR, CKPT_DIR, SD_DIR):
        p.mkdir(parents=True, exist_ok=True)


def read_jsonl(path):
    path = pathlib.Path(path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_kb_passages():
    """Knowledge-base passages, in a stable order (ids = list index).

    Curriculum passages are limited to cfg.SUBJECTS; your notes and manuals are always kept.
    """
    subjects = getattr(cfg, "SUBJECTS", None)
    rows = [r for r in read_jsonl(CURRICULUM_PASSAGES) if not subjects or r.get("subject") in subjects]
    texts = [r["text"] for r in rows]
    if subjects and "device" in subjects:
        if BOARD == "rlcd":
            from .rlcd_cards import CARDS
        else:
            from .device_cards import CARDS
        texts += CARDS
    kinds = getattr(cfg, "KB_SOURCE_KINDS", None)
    return texts + [r["text"] for r in read_jsonl(SOURCE_PASSAGES) if not kinds or r.get("kind") in kinds]
