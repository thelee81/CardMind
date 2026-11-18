"""Optional: fake data so you can test steps 4-9, verify.py and the firmware without spending
API credits. The resulting model only parrots templates - it is a plumbing test, not a tutor.

  set ESPLLM_DATA=data_demo & set ESPLLM_DEMO=1        (PowerShell: $env:ESPLLM_DATA="data_demo"; $env:ESPLLM_DEMO="1")
  python pipeline/00_demo_data.py
  then steps 01, 04-09 as usual (skip 02 and 03).
"""
import random

from lib.common import CONVERSATIONS, CURRICULUM_PASSAGES, SOURCES, cfg, ensure_dirs, write_jsonl

CARDS = [
    ("science", "Light: shadows", "A shadow forms when an opaque object blocks light. The shadow is on the side of the object away from the light source. When the light source moves, the shadow changes its length and direction. At noon in Singapore the Sun is high, so shadows are short."),
    ("science", "Changes of state", "Evaporation is when a liquid changes into a gas. Wet clothes hung at an HDB corridor dry faster on a hot, windy day because heat and wind help water evaporate. Condensation is the opposite: water vapour cools and turns back into tiny water droplets."),
    ("science", "Magnets", "A magnet has two poles, a north pole and a south pole. Like poles repel each other and unlike poles attract each other. Magnets attract magnetic materials such as iron, steel, nickel and cobalt, but not plastic, wood or aluminium."),
    ("science", "Plant parts", "The roots of a plant hold it firmly in the soil and take in water and mineral salts. The stem holds the plant up and carries water from the roots to the leaves. The leaves make food for the plant using sunlight. This process is called photosynthesis."),
    ("science", "Life cycle of a butterfly", "A butterfly has four stages in its life cycle: egg, larva, pupa and adult. The larva is also called a caterpillar and it eats a lot of leaves. Inside the pupa, the caterpillar changes into an adult butterfly. This big change is called metamorphosis."),
    ("science", "Heat conductors", "Metals such as copper and steel are good conductors of heat, so heat moves through them quickly. Wood, plastic and air are poor conductors of heat. That is why a metal spoon in hot soup gets hot quickly, but a wooden spoon does not."),
    ("maths", "Fractions of a set", "To find a fraction of a set, divide the set into equal groups. The bottom number tells how many groups, and the top number tells how many groups to take. For example, 3/4 of 20: 20 / 4 = 5, then 3 x 5 = 15. So 3/4 of 20 is 15."),
    ("maths", "Bar model", "The bar model helps solve word problems. Draw a bar for each quantity so that bigger amounts have longer bars. For example, Ali has 12 stickers and Mei has 3 times as many. Draw 1 unit for Ali and 3 units for Mei. 1 unit is 12, so 3 units is 3 x 12 = 36."),
    ("maths", "Area and perimeter", "The perimeter of a rectangle is the distance around it. The area is the space it covers. For a rectangle 5 cm long and 3 cm wide, the perimeter is 5 + 3 + 5 + 3 = 16 cm and the area is 5 x 3 = 15 square centimetres."),
    ("maths", "Rounding", "To round a number to the nearest 10, look at the ones digit. If it is 5 or more, round up. If it is less than 5, round down. For example, 47 rounds to 50 and 43 rounds to 40. Rounding helps us estimate answers quickly."),
]

NOTES = """# Cardputer quick guide
Press the keys to type a message to Bolt, then press Enter to send it.
Type /new and press Enter to start a new chat.
Charge the Cardputer with a USB-C cable. The small light turns off when it is full.
Keep the Cardputer away from water and do not drop it.
"""

PRAISE = ["Great job!", "Well done!", "Nice thinking!", "You got it!", "Super!"]
OPEN = ["what is {a} x {b}", "{a} times {b}?", "whats {a} + {b}", "{a} plus {b} pls", "what is {a} - {b}",
        "can you help me with {a} x {b}", "{a} divided by {b}"]


def arith_conv(rng):
    a, b = rng.randint(2, 99), rng.randint(2, 12)
    q = rng.choice(OPEN).format(a=a, b=b)
    if "x" in q or "times" in q:
        expr, r = f"{a} x {b}", a * b
    elif "+" in q or "plus" in q:
        expr, r = f"{a} + {b}", a + b
    elif "-" in q:
        expr, r = f"{a} - {b}", a - b
    else:
        expr, r = f"{a} / {b}", None
    if r is None:
        bot = f"{a} / {b} is {a // b} remainder {a % b}. {rng.choice(PRAISE)} Can you check it by multiplying?"
    else:
        bot = f"{expr} = {r}. {rng.choice(PRAISE)} Want to try a harder one?"
    return {"kind": "demo", "turns": [{"user": q, "bot": bot}]}


def card_conv(rng, card):
    subject, title, text = card
    first = text.split(". ")[0] + "."
    q = rng.choice([f"tell me about {title.lower()}", f"what is {title.split(':')[-1].strip().lower()}",
                    f"i dont get {title.lower()}", f"can you explain {title.lower()}?"])
    return {"kind": "demo", "turns": [{"user": q, "bot": f"{first} {rng.choice(PRAISE)} What do you think happens next?"}]}


def main():
    ensure_dirs()
    rng = random.Random(cfg.SEED)
    write_jsonl(CURRICULUM_PASSAGES, [{"text": f"{t}: {x}", "subject": s, "topic": t, "subtopic": t, "level": "P4"}
                                      for s, t, x in CARDS])
    (SOURCES / "notes" / "cardputer_guide.md").write_text(NOTES, encoding="utf-8")
    convs = [arith_conv(rng) for _ in range(1500)] + [card_conv(rng, rng.choice(CARDS)) for _ in range(600)]
    convs += [{"kind": "demo", "turns": [{"user": "hi", "bot": f"Hi! I am {cfg.CHARACTER_NAME}. Ask me about maths or science!"}]}
              for _ in range(10)]
    write_jsonl(CONVERSATIONS, convs)
    print(f"demo data: {len(CARDS)} cards, {len(convs)} conversations")


if __name__ == "__main__":
    main()
