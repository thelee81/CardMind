"""espLLM settings - edit this file, then re-run the pipeline steps.

Everything the pipeline needs lives here. The firmware reads model shape and
special-token ids from model.bin, and the retrieval threshold from kb.bin, so
there is nothing to keep in sync by hand on the C side.
"""

# ---------------------------------------------------------------- character
# Use case since 2026-11-17: "Card", a device assistant for makers (pipeline/03_generate_device.py).
# The maths tutor "Bolt" (v5c) is backed up in backup/maths_tutor_2026-11-17; its settings were
# SUBJECTS maths, the 4.8M model shape, and the Bolt description below (still used by step 3).
DEVICE_NAME = "Card"
DEVICE_DESCRIPTION = (
    "a concise, friendly technical assistant built into an M5Stack Cardputer v1.1, for makers and "
    "engineers; it reports the device's live readings, carries out simple actions on the device and "
    "answers questions about the Cardputer's hardware from its knowledge cards"
)
CHARACTER_NAME = "Bolt"
CHARACTER_DESCRIPTION = (
    "a cheerful, curious little robot who loves maths and science, is patient, "
    "encouraging, and a bit playful, and never makes the child feel silly"
)
LEARNER = "a 10-year-old Singapore primary school student (Primary 4)"
LOCALE_NOTES = (
    "Use simple English with British spelling (colour, metre, maths, centimetre). "
    "Use Singapore everyday contexts where natural: hawker centres, MRT trains, HDB "
    "flats, void decks, Gardens by the Bay, East Coast Park, Singapore dollars and "
    "cents, hot and rainy weather, school recess and canteen. Follow Singapore MOE "
    "primary syllabus methods, for example the bar model (model drawing) for word "
    "problems, and the terms Singapore teachers use. Write standard English, not Singlish."
)

# ---------------------------------------------------------------- data-writing LLM
# The planner writes the knowledge cards (step 2), the generator writes the conversations (step 3).
# PROVIDER picks who writes the training data: "gemini" (GEMINI_API_KEY in .env) or
# "anthropic" (ANTHROPIC_API_KEY, Message Batches API).
PROVIDER = "gemini"
if PROVIDER == "gemini":
    PLANNER_MODEL = "gemini-2.5-flash"          # 50 requests: quality matters, volume is small
    GENERATOR_MODEL = "gemini-3.5-flash-lite"   # thousands of requests (2.5-flash-lite is retired)
else:
    PLANNER_MODEL = "claude-opus-5-5"
    GENERATOR_MODEL = "claude-opus-5-5"
BUDGET_USD = 30.0             # Gemini hard cap on total spend (all steps), from reported token usage
GEMINI_CONCURRENCY = 16       # parallel requests (lower it if you hit 429 rate limits)
PLANNER_EFFORT = "medium"     # low | medium | high | xhigh | max
GENERATOR_EFFORT = "low"
MAX_TOKENS = 16000            # thinking counts toward this
# list prices in USD per 1M tokens, used only for the cost estimate printed before submit
PRICE_INPUT = {"claude-opus-5-5": 4.0, "claude-sonnet-5-5": 2.0, "claude-haiku-5-5": 0.10}
PRICE_OUTPUT = {"claude-opus-5-5": 20.0, "claude-sonnet-5-5": 10.0, "claude-haiku-5-5": 0.50}
# Gemini paid-tier list prices (USD per 1M; output includes thinking). Check ai.google.dev/pricing.
PRICE_INPUT.update({"gemini-2.5-flash": 0.30, "gemini-3.5-flash-lite": 0.30})
PRICE_OUTPUT.update({"gemini-2.5-flash": 2.50, "gemini-3.5-flash-lite": 2.50})

# ---------------------------------------------------------------- subjects
# Curriculum subjects kept in the knowledge base and the training set (steps 4 and 9).
# "device" = the hand-written Cardputer cards in pipeline/lib/device_cards.py (device assistant).
# The maths tutor used ("maths",); its generated data stays on disk.
SUBJECTS = ("device",)
KB_SOURCE_KINDS = ("notes",)    # source passages kept in the KB ("manuals" are covered by the device cards)

# ---------------------------------------------------------------- data volume
SUBTOPICS_PER_TOPIC = 20        # ~45 topics -> ~900 subtopics
PASSAGES_PER_SUBTOPIC = 2       # knowledge-base cards written by the planner
CONVERSATIONS_PER_REQUEST = 4
REQUESTS_PER_PASSAGE = 3        # curriculum passages
REQUESTS_PER_SOURCE_CHUNK = 2   # your notes and device manuals
PERSONA_REQUESTS = 600          # chit-chat, encouragement, safety, "I'm not sure"
VAL_FRACTION = 0.02
SEED = 1337

# ---------------------------------------------------------------- knowledge base (SD card)
CHUNK_WORDS = 60                # notes/manual chunk size
CHUNK_OVERLAP_WORDS = 15
KB_MIN_SCORE = 2.5              # BM25 score needed before a passage is shown to the model (59 device cards)
KB_BUCKETS = 4096

# ---------------------------------------------------------------- tokenizer
VOCAB_SIZE = 2048

# ---------------------------------------------------------------- model (~2.7M params, ~2.8 MB int8; flash partition holds ~5.1 MB)
DIM = 192                       # d1 (2.7M). d2 tried 224 / 8 layers / 7 heads / 640 (4.8M): no better on
N_LAYERS = 6                    # 9k conversations (val 0.361 vs 0.355; it overfits) and only ctx ~300
N_HEADS = 6                     # head_dim 32
N_KV_HEADS = 1                  # multi-query attention keeps the KV cache tiny
HIDDEN_DIM = 512
MAX_SEQ_LEN = 512               # firmware shrinks this at runtime if RAM is short
ROPE_THETA = 10000.0

# ---------------------------------------------------------------- training
BATCH_SIZE = 32
LEARNING_RATE = 1e-3
MIN_LR = 1e-4
WARMUP_ITERS = 300
MAX_ITERS = 6000                # maths + persona from rounds 1 and 2 (~26k conversations)
WEIGHT_DECAY = 0.1
DROPOUT = 0.1                   # maths-only data is smaller: keep regularising
GRAD_CLIP = 1.0
EVAL_INTERVAL = 250
EVAL_ITERS = 50
DEVICE = "auto"                 # auto | cuda | cpu

# ---------------------------------------------------------------- generation (PC simulator; firmware has its own copy in chat.h)
TEMPERATURE = 0.5             # device: CHAT_TEMPERATURE in firmware/src/chat.h (keep equal)
TOP_K = 40
MAX_ANSWER_TOKENS = 120
