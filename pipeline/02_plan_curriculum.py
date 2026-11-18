"""Step 2: Opus writes the curriculum knowledge base (one batch request per topic).

  python pipeline/02_plan_curriculum.py submit          # dry run: prints cost estimate
  python pipeline/02_plan_curriculum.py submit --yes    # really submit
  python pipeline/02_plan_curriculum.py status
  python pipeline/02_plan_curriculum.py collect [--wait]

Output: data/kb/curriculum_passages.jsonl  ({"text", "subject", "topic", "subtopic", "level"})
"""
import argparse

from lib import batch
from lib.common import CURRICULUM_PASSAGES, cfg, ensure_dirs, write_jsonl
from lib.curriculum import MATHS_TOPICS, SCIENCE_TOPICS
from lib.kbtext import ascii_fold

JOB = "curriculum"

SYSTEM = f"""You are an experienced Singapore primary school teacher. You are writing the
knowledge base for a tiny offline tutor that runs on a pocket computer. The tutor is
used by {cfg.LEARNER}.

{cfg.LOCALE_NOTES}

The tutor's knowledge base is a set of short "cards". Each card is shown to a very
small language model, which answers the child using that card, so every card must:
- be 45 to 70 words, plain sentences, no lists, no markdown, no line breaks
- stand alone: name the subject explicitly in the card (never "this" or "it" alone),
  so the card makes sense when it is the only thing the reader sees
- be 100% accurate and consistent with the Singapore MOE primary syllabus
- use simple words a 10-year-old understands, and explain any science word it uses
- use only plain ASCII characters: write multiplication as x, division as /,
  fractions as 3/4, degrees as "degrees", and no emojis
- for maths, include one small worked example with correct arithmetic
- for science, include one everyday Singapore example where it fits naturally
Different cards for the same subtopic must cover different facts or examples."""

SCHEMA = {
    "type": "object",
    "properties": {
        "subtopics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "level": {"type": "string", "enum": ["P3", "P4", "P5"]},
                    "cards": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "level", "cards"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["subtopics"],
    "additionalProperties": False,
}


def build_items():
    items = []
    topics = [("maths", t) for t in MATHS_TOPICS] + [("science", t) for t in SCIENCE_TOPICS]
    for i, (subject, topic) in enumerate(topics):
        user = (f"Subject: {subject}\nTopic: {topic}\n\n"
                f"Split this topic into {cfg.SUBTOPICS_PER_TOPIC} distinct subtopics that a "
                f"Primary 4 child might ask about (include a few Primary 3 revision and Primary 5 "
                f"stretch subtopics where they fit). For each subtopic write exactly "
                f"{cfg.PASSAGES_PER_SUBTOPIC} knowledge cards following the rules.")
        params = batch.make_params(cfg.PLANNER_MODEL, cfg.PLANNER_EFFORT, SYSTEM, user, SCHEMA)
        items.append((f"topic-{i:04d}", params, {"subject": subject, "topic": topic}))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["submit", "status", "collect"])
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--wait", action="store_true")
    a = ap.parse_args()
    ensure_dirs()
    if a.cmd == "submit":
        est = cfg.SUBTOPICS_PER_TOPIC * cfg.PASSAGES_PER_SUBTOPIC * 110 + 3000  # cards + thinking
        batch.submit(JOB, build_items(), cfg.PLANNER_MODEL, est, a.yes)
    elif a.cmd == "status":
        batch.status(JOB)
    else:
        rows = []
        for r in batch.collect(JOB, a.wait):
            for st in r["data"].get("subtopics", []):
                for card in st.get("cards", []):
                    text = ascii_fold(card)
                    if 25 <= len(text.split()) <= 110:
                        rows.append({"text": text, "subject": r["meta"]["subject"],
                                     "topic": r["meta"]["topic"], "subtopic": ascii_fold(st["title"]),
                                     "level": st["level"]})
        write_jsonl(CURRICULUM_PASSAGES, rows)
        print(f"wrote {len(rows)} cards -> {CURRICULUM_PASSAGES}")


if __name__ == "__main__":
    main()
