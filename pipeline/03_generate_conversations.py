"""Step 3: Opus writes training conversations in the character's voice.

Three kinds of request:
  cur-*   grounded on a curriculum card from step 2
  src-*   grounded on a chunk of your notes / device manuals from step 1
  per-*   persona: chit-chat, encouragement, safety, "I'm not sure", device help

  python pipeline/03_generate_conversations.py submit [--yes]
  python pipeline/03_generate_conversations.py status
  python pipeline/03_generate_conversations.py collect [--wait]

Output: data/generated/conversations.jsonl  ({"kind", "turns": [{"user", "bot"}]})
"""
import argparse
import random

from lib import batch
from lib.common import (CONVERSATIONS, CURRICULUM_PASSAGES, GEN_DIR, SOURCE_PASSAGES, cfg, ensure_dirs,
                        read_jsonl, write_jsonl)
from lib.curriculum import PERSONA_THEMES, PERSONA_THEMES_R2

JOB = "conversations"
N = cfg.CONVERSATIONS_PER_REQUEST

SYSTEM = f"""You write training conversations for {cfg.CHARACTER_NAME}, {cfg.CHARACTER_DESCRIPTION}.
{cfg.CHARACTER_NAME} is a maths and science guide for {cfg.LEARNER}. {cfg.CHARACTER_NAME}
lives inside an M5Stack Cardputer, a tiny pocket computer with a small screen and keyboard.
The child types a message and presses Enter; {cfg.CHARACTER_NAME} shows the reply on screen and
reads it aloud in a robot voice. Typing /new starts a new chat, /mute turns the voice off and
/talk turns it back on.

{cfg.LOCALE_NOTES}

These conversations will train a very small language model, so the style must be simple
and consistent. Rules for {cfg.CHARACTER_NAME}'s replies:
- usually 15 to 45 words, never more than 60; one to four short sentences
- plain ASCII only: no emojis, no markdown, no bullet points, no line breaks
- write maths as digits with x for multiply and / for divide, e.g. 12 x 7 = 84
- arithmetic must be exactly right; when solving, show the key step briefly
- for word problems, guide with the bar model: say what the bars stand for and how they compare
- prefer guiding questions and hints over just giving homework answers, then confirm the answer
- often end with a short question or tiny challenge to keep the child thinking
- only state facts from the reference card or very basic, certain knowledge; if unsure,
  say so honestly and suggest asking a teacher or parent
- warm, encouraging, never sarcastic, never scary; refer to itself as {cfg.CHARACTER_NAME} when asked
- safety: for anything about being hurt, unsafe, sad or grown-up topics, respond kindly and tell
  the child to talk to a trusted grown-up such as a parent or teacher

Rules for the child's messages:
- realistic for a 10-year-old typing on a tiny keyboard: often short, sometimes all lowercase,
  sometimes with small typos or missing punctuation, sometimes a full sentence
- vary personality: curious, confused, impatient, proud, silly, worried
- follow-up turns react to what {cfg.CHARACTER_NAME} just said (try an answer, ask why, change topic)

Each conversation has 1 to 4 turns. Write {N} conversations that are clearly different from
each other in opening question, child personality and length."""

SCHEMA = {
    "type": "object",
    "properties": {
        "conversations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "turns": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"child": {"type": "string"}, "tutor": {"type": "string"}},
                            "required": ["child", "tutor"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["turns"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["conversations"],
    "additionalProperties": False,
}

ANGLES = [
    "Open with a direct question about the card's idea.",
    "Open with a homework-style question or word problem related to the card.",
    "Open with a confused or wrong idea the child has about the card's topic.",
    "Open with a curious 'why' or 'what if' question connected to the card.",
    "Include one turn where the child tries an answer and gets it wrong, then right.",
    "Make one conversation a single short exchange.",
]

# Round 2 (--round 2): new angles and themes for more varied data, and Bolt states exact
# results first, so the model learns to use the calculator line it is shown.
ANGLES_R2 = [
    "Open with an everyday Singapore situation (hawker centre, MRT, HDB flat, canteen, rain, a family outing) where the card's idea is needed.",
    "Open with the child mixing up the card's idea with a similar idea; help them tell the two apart.",
    "Open with the child explaining the card's idea in their own words, partly wrong; fix the wrong part kindly.",
    "Open with a multi-step word problem; over the turns, solve it step by step with the bar model.",
    "Open with the child asking for a quick quiz question on the card; ask one, the child answers, then check it.",
    "Open with a 'how do we know' or 'what could I try at home' question about the card's idea.",
]
SYSTEM_R2_EXTRA = f"""
Extra rule for this set: when the child's message contains a calculation (for example
"what is 23 x 4"), {cfg.CHARACTER_NAME} first states the exact result using the same numbers
(23 x 4 = 92) and then explains or checks one key step."""
REQUESTS_PER_PASSAGE_R2 = 2
PERSONA_REQUESTS_R2 = 400


def build_items(rng, rnd=1):
    angles, themes = (ANGLES, PERSONA_THEMES) if rnd == 1 else (ANGLES_R2, PERSONA_THEMES_R2)
    system = SYSTEM if rnd == 1 else SYSTEM + SYSTEM_R2_EXTRA
    per_passage = cfg.REQUESTS_PER_PASSAGE if rnd == 1 else REQUESTS_PER_PASSAGE_R2
    n_persona = cfg.PERSONA_REQUESTS if rnd == 1 else PERSONA_REQUESTS_R2
    items = []
    for i, p in enumerate(read_jsonl(CURRICULUM_PASSAGES)):
        for r in range(per_passage):
            angle = rng.choice(angles)
            user = (f"Reference card (the tutor can see this):\n{p['text']}\n\n"
                    f"Subject: {p['subject']}. Topic: {p['topic']}. Subtopic: {p['subtopic']} ({p['level']}).\n"
                    f"Write {N} conversations where the child asks about this card's subject. {angle}")
            items.append((f"cur-{i:05d}-{r}", batch.make_params(
                cfg.GENERATOR_MODEL, cfg.GENERATOR_EFFORT, system, user, SCHEMA), {"kind": "curriculum"}))
    for i, p in enumerate(read_jsonl(SOURCE_PASSAGES)):
        for r in range(cfg.REQUESTS_PER_SOURCE_CHUNK):
            user = (f"Reference card from the family's own {p['kind']} (the tutor can see this):\n"
                    f"{p['text']}\n\n"
                    f"Write {N} conversations where the child (or once, a parent) asks about something "
                    f"in this card. {cfg.CHARACTER_NAME} answers in simple words using only what the card "
                    f"says; if the card does not answer the question, {cfg.CHARACTER_NAME} says it is not sure.")
            items.append((f"src-{i:05d}-{r}", batch.make_params(
                cfg.GENERATOR_MODEL, cfg.GENERATOR_EFFORT, system, user, SCHEMA), {"kind": p["kind"]}))
    for i in range(n_persona):
        theme = themes[i % len(themes)]
        user = (f"Theme: {theme}.\nThere is no reference card. Write {N} conversations on this theme. "
                f"If a maths or science question comes up, keep it to very basic, certain facts.")
        items.append((f"per-{i:05d}", batch.make_params(
            cfg.GENERATOR_MODEL, cfg.GENERATOR_EFFORT, system, user, SCHEMA), {"kind": "persona"}))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["submit", "status", "collect"])
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--round", type=int, default=1, help="2 = second, more varied data set")
    a = ap.parse_args()
    ensure_dirs()
    JOB = "conversations" if a.round == 1 else f"conversations_r{a.round}"
    out_path = CONVERSATIONS if a.round == 1 else GEN_DIR / f"conversations_r{a.round}.jsonl"
    if a.cmd == "submit":
        items = build_items(random.Random(cfg.SEED + a.round - 1), a.round)
        if not items:
            raise SystemExit("No passages found. Run steps 1 and 2 first.")
        batch.submit(JOB, items, cfg.GENERATOR_MODEL, N * 450 + 1500, a.yes)
    elif a.cmd == "status":
        batch.status(JOB)
    else:
        # remember which card each conversation was written from (step 4 uses it as the ctx)
        cards = {"cur": [p["text"] for p in read_jsonl(CURRICULUM_PASSAGES)],
                 "src": [p["text"] for p in read_jsonl(SOURCE_PASSAGES)]}
        rows = []
        for r in batch.collect(JOB, a.wait):
            pre, _, rest = r["custom_id"].partition("-")
            card = cards[pre][int(rest.split("-")[0])] if pre in cards else None
            for conv in r["data"].get("conversations", []):
                turns = [{"user": t["child"], "bot": t["tutor"]} for t in conv.get("turns", [])]
                if turns:
                    rows.append({"kind": r["meta"].get("kind", "?"), "card": card, "turns": turns})
        write_jsonl(out_path, rows)
        print(f"wrote {len(rows)} conversations -> {out_path}")


if __name__ == "__main__":
    main()
