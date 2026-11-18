# CardMind design

This document explains how CardMind is built and why. For what Card can do and how to use it, see
[README.md](../README.md). For step-by-step procedures and the history of every model trained, see
[RUNBOOK.md](RUNBOOK.md).

## Contents

1. [Goals and constraints](#1-goals-and-constraints)
2. [Architecture overview](#2-architecture-overview)
3. [The model](#3-the-model)
4. [Memory budget](#4-memory-budget)
5. [One turn, end to end](#5-one-turn-end-to-end)
6. [Tools](#6-tools)
7. [Card scripts](#7-card-scripts)
8. [Training data](#8-training-data)
9. [Training and export](#9-training-and-export)
10. [C and Python twins](#10-c-and-python-twins)
11. [Firmware](#11-firmware)
12. [Testing and evaluation](#12-testing-and-evaluation)
13. [Design decisions and lessons](#13-design-decisions-and-lessons)
14. [Known limits and future work](#14-known-limits-and-future-work)

---

## 1. Goals and constraints

**Goal:** a useful assistant that runs entirely on a pocket microcontroller. It should report and control
the device it runs on and answer questions about it, without any network connection.

| Constraint | Value | Consequence |
|---|---|---|
| CPU | ESP32-S3, 2 × Xtensa LX7 at 240 MHz | Generating text is slow, so replies must be short |
| RAM | 512 KB on-chip SRAM, **no PSRAM** | Weights cannot live in RAM; the KV cache must be tiny |
| Flash | 8 MB | Room for a 3 MB app plus a model of about 4.9 MB |
| Display | 240 × 135 | Answers of 1 to 3 sentences |
| Input | built-in keyboard | Text in, text and voice out |
| Network | none (by design) | Everything must be computed on the device |

**What follows from these constraints:** a model of a few million parameters, int8 weights read in place
from flash, and an architecture where **code supplies the facts and the model supplies the language**.

## 2. Architecture overview

```
                       ┌──────────────────────── Cardputer (ESP32-S3) ────────────────────────┐
 keyboard ──► main.cpp ─┤                                                                       │
                        │  chat.c  build_ctx()                                                  │
                        │    ├─ device.c   dev_parse → intent ──► hw.cpp reads / acts          │
                        │    │                         └────────► dev_line → "Device: ..."      │
                        │    ├─ device.c   script request? ─────► "Mode: script." + hints       │
                        │    ├─ calc.c     calc_line ───────────► "Calculator: ..."             │
                        │    └─ kb.c       BM25 over kb.bin (SD) ► knowledge card               │
                        │                                                                       │
                        │  prompt = <ctx> facts <usr> question <bot>                            │
                        │  engine.c  int8 transformer (weights memory-mapped from flash)        │
                        │  sampling → reply ──► screen (main.cpp) + SAM voice (tts.cpp, core 0) │
                        │                  └──► "Script: ..." → script.c → Enter → hw.cpp       │
                        └───────────────────────────────────────────────────────────────────────┘

 PC side:  Gemini ─► pipeline/03 ─► 04 (replay through Python twins) ─► 05-07 train ─► 08 model.bin
                                                                                    └► 09 kb.bin
```

There are three layers:

1. **Portable C core** (`firmware/src/*.c`): the engine, tokenizer, chat, knowledge search, request
   matcher, calculator, script interpreter and TTS text expansion. There is no hardware access, so the
   same code builds for the Cardputer and for a PC (`firmware/host/`).
2. **Board layer** (`main.cpp`, `hw.cpp`, `tts.cpp`): the screen, keyboard, SD card, flash partition,
   sensors, actions and voice.
3. **Python pipeline** (`pipeline/`): data generation, dataset building, training and export, plus
   Python twins of every rule in the C core.

## 3. The model

| | Value |
|---|---|
| Type | decoder-only transformer (Llama-style) |
| Layers / width / heads | 6 / 192 / 6 (head size 32) |
| Key/value heads | 1 (multi-query attention) |
| Feed-forward | SwiGLU, hidden size 512 |
| Position encoding | RoPE, θ = 10000 |
| Normalisation | RMSNorm |
| Vocabulary | 2,048 (SentencePiece BPE with byte fallback, plus special tokens) |
| Context | up to 512 tokens (less if RAM is short at boot) |
| Parameters | about 2.7 million |
| Stored as | int8 weights with one float scale per row: 2.8 MB |
| Sampling | temperature 0.5, top-k 40, at most 120 reply tokens |

**Special tokens:** `<bos> <ctx> <usr> <bot> <eot> <eos>`. A conversation is laid out as:

```
<bos> <ctx> Device: battery 3.92 V, about 78%. <usr> battery? <bot> Battery is at 3.92 V, about 78%. ... <eot>
      <ctx> ... <usr> next question <bot> ... <eot>
```

`<ctx>` is optional on each turn. Earlier turns stay in the KV cache, so follow-up questions work until the
context fills up. At that point the history is dropped and the current question is kept.

**Why this shape:**
- **Multi-query attention** shrinks the KV cache by 6× compared with full multi-head attention. On this
  chip that saving is the difference between a 512-token context and a ~100-token one.
- **6 layers at width 192** was the best size for the data available. A 4.8M model (width 224, 8 layers)
  scored no better on 9,000 conversations: it overfitted and left less RAM for context.
- **A 2,048-token vocabulary** keeps the embedding table small (0.4 MB) while still encoding whole common
  words.
- **Temperature 0.5:** 0.7 made the model drift away from copying facts, and 0.3 made it repeat itself.

## 4. Memory budget

**Flash (8 MB):**

| Region | Offset | Size | Contents |
|---|---|---|---|
| bootloader, partition table, NVS | 0x0 | 64 KB | |
| app | 0x10000 | 3 MB | firmware (~1.2 MB used; boot logo 39 KB) |
| model | 0x310000 | ~4.9 MB | `model.bin` (2.8 MB), memory-mapped and read in place |

**RAM (512 KB SRAM, part of it used by the system and Wi-Fi driver):**

| Item | Size |
|---|---|
| Static data (globals, Wi-Fi driver, buffers) | 65 KB (build report: 64,904 bytes) |
| Engine working buffers (activations, logits, attention scores) | about 46 KB (`engine_work_bytes`) |
| Reserve left free for SD, keyboard, voice and system | 40 KB |
| **KV cache** | **432 bytes per token** (6 layers × (2 × 32 int8 + 2 float scales)): 512 tokens = 221 KB |

At boot the firmware measures free heap (after the voice task has started), subtracts the reserve and
working buffers, and sizes the context to fit, up to the model's 512 tokens. If fewer than 192 tokens fit,
it stops with an error. The KV cache is stored as **int8 with one scale per position**,
which takes a quarter of the RAM float32 would.

**Wi-Fi scans** need about 64 KB that is not normally free. `hw.cpp` calls a release hook that frees the
engine, runs the scan, then re-creates the engine. The conversation history is lost, and the README says so.

## 5. One turn, end to end

Example: `turn the led blue` on the Cardputer.

1. **Match** (`dev_parse`): word sets give `DEV_LED_SET`, colour index `blue`. It is not a how-to question
   and has no script cue.
2. **Plan and act** (`dev_plan`, then `hw.cpp`): the LED shares power with the backlight, so if brightness
   is 0 the plan raises it to 100 first. `hw.cpp` writes the WS2812 on G21.
3. **Device line** (`dev_line`): `Device: RGB LED set to blue.` (plus `screen brightness raised to 100%`
   when that happened).
4. **Context:** with a Device line present, the knowledge card is left out (it distracted the model), and
   the calculator only adds a line if the message contains maths.
5. **Prompt:** `<ctx> Device: RGB LED set to blue. <usr> turn the led blue <bot>` is encoded and fed in
   batches of 4 tokens (prefill).
6. **Generate:** one token at a time with top-k sampling. Each piece is streamed to the screen, and whole
   sentences go to the SAM voice task on core 0 while core 1 keeps generating.
7. **Script check:** if the reply starts with `Script:`, it is not spoken. It is parsed by `script.c`, and
   the screen shows `[Enter] run  [other key] cancel`.

`/ctx` on the device shows step 4's result for the last turn, which is how wrong replies are diagnosed.

## 6. Tools

### Request matcher and Device line (`device.c` ↔ `devtext.py`)

- **18 intents:** 12 readings (battery, temp, memory, sd, mic, wifi, grove, uptime, screen, volume, chip,
  status) and 5 actions (LED, brightness, volume, beep, IR), plus none.
- **Rules, not a classifier.** Lower-cased words are matched against word sets, with guards:
  - **How-to words** ("how do i", "pin", "code", "arduino") stop any reading or action, so the question
    gets a knowledge card instead.
  - **Questions are never actions:** "is the led on" is a reading.
  - **Status report** only when nothing specific matches, or when three or more topics are mentioned.
  - **Numbers** are parsed in decimal or `0x` hex, with ranges checked (IR 0 to 255, brightness 10 to 100).
- **The Device line** is the only place readings reach the model. Its format is fixed and short, e.g.
  `Device: SD card SDHC, 14.8 GB, 2 MB used.`, so the model learns to copy it.

### Calculator (`calc.c` ↔ `kbtext.py`)

This is left over from the maths tutor and still active. It handles fractions, mixed numbers,
percentages, "of", unit conversions and remainders. It skips hex numbers so that IR codes are not "solved".

### Knowledge search (`kb.c` ↔ `kbtext.py`)

- **BM25** over 59 hand-written cards plus your notes. The cards live in `pipeline/lib/device_cards.py`
  and are built into `kb.bin` by step 9.
- **The index is read from the SD card in place.** Hashed term buckets mean no index is loaded into RAM.
- **A minimum score** (`KB_MIN_SCORE` = 2.5, stored in `kb.bin`) stops weak matches from being shown.
- **Why hand-written cards and not the PDF manual:** chunks of the manual were long, mixed several topics,
  and the model copied the wrong half. Each card answers one topic in 2 to 4 sentences.

### Script hints (`dev_script_hints`)

For script requests the firmware converts the numbers itself, and the model only has to copy them:

```
"beep after 2 minutes, 0x20"  →  Mode: script. 2 min = 120000 ms = repeat 2 { wait 60000 }. 0x20 = 32.
```

It covers seconds, minutes, decimals ("0.5 s"), "half a second" and hex values, with up to 4 hints per
message.

## 7. Card scripts

**Why a script language at all:** "blink 5 times" needs timing and repetition, and the model's reply is
text. General code is out of reach: there is no compiler on the device, MicroPython would not fit next to
the model, and a 2.7M model cannot write correct C. A **tiny, fully validated language** keeps every
possible output safe.

**Grammar (informal):**

```
script    := stmt (";" stmt)*
stmt      := "led" COLOR | "bright" N | "vol" N | "beep" [N [N]] | "ir" N N | "wait" N
           | "show" READING | "repeat" N "{" script "}"
           | "if" READING OP N "{" script "}" ["else" "{" script "}"]
READING   := battery | temp | mic | ram | uptime | bright | vol
OP        := < | > | <= | >= | == | !=
```

**Safety model:**
- **The parser checks everything before anything runs.** Ranges, at most 200 characters, 48 nodes and a
  depth of 4. Errors have exact messages, for example `repeat: 1 to 100`.
- **Runtime limits:** at most 2,000 steps and 10 minutes of waiting in total. A mic reading counts as
  600 ms, because it records for that long.
- **The user always confirms:** a model-written script runs only after Enter, any key stops it, and it is
  never spoken.
- **`/do`** bypasses the model for exact scripts. **`/save` / `/run`** keep scripts on the SD card.

`script.c` and `scripttext.py` produce the same canonical text and the same execution trace. This was
checked on 2,515 fuzzed inputs. The training data stores scripts in canonical form, so the model learns
one spelling of each statement.

## 8. Training data

**Source:** Gemini 3.5 Flash-Lite writes conversations from structured prompts (`03_generate_device.py`).
Total spend for all current data is about $22, with a hard cap (`BUDGET_USD`) checked before each job.

| Round | What | Why |
|---|---|---|
| 1 | device conversations from **planned requests with simulated readings**; card Q&A; persona | base data |
| 2 | more data for the weak spots of model d1 (long status line, SD sizes, Grove) | targeted fixes |
| 3 | Card scripts across 12 themes, including over-the-limit requests | the script feature |
| 4 | hex IR, waits of several minutes, colour sequences, fades, fractions of a second | weak scripts in d9 |

**Simulated readings:** `devtext.simulate()` draws random but realistic status values (battery,
temperature, SD sizes, Wi-Fi results, I2C addresses). Gemini is told the planned request and the exact
`Device:` line, and writes the user message and Card's reply.

**Step 4 replays everything through the device's own rules** (`04_build_device_dataset.py`):
- every user message goes through the **Python twin of the matcher**. If it does not produce the planned
  intent, the turn is cut, so the model only learns from messages the device really understands;
- the `<ctx>` is rebuilt exactly as the firmware would build it;
- replies are cut if they:
  - miss the reading's key value;
  - state a number that is not in the ctx, the question or an earlier turn;
  - claim an action that did not happen;
- scripts must parse, and every number in the request must appear in the script. Seconds and minutes may
  appear as milliseconds, and minutes as `repeat N { wait 60000 }`. Scripts are stored in canonical form;
- **augmentation:** SD replies are copied with small amounts used (1 to 999 MB), with the number rewritten.
  Real cards often hold only a few MB, and without these copies the model mis-copied "2 MB" as "2.8 GB";
- **script examples appear twice** in the training set (`SCRIPT_REPEAT`), so the growing device data
  does not dilute them.

The current dataset has 15,304 conversations: 11,517 device, 2,033 script, 1,242 card and 512 persona.

## 9. Training and export

- **Training** (`07_train.py`, PyTorch): next-token loss on random windows of up to 512 tokens from the concatenated conversations, AdamW, a cosine
  learning rate from 1e-3 to 1e-4 with 300 warm-up steps, 6,000 iterations at batch 32, dropout 0.1. The
  best validation checkpoint is kept. It takes about 8 minutes on an RTX A4000.
- **Export** (`08_export.py`): one file holds a header (shape, special-token ids, offsets, CRC), the int8
  weights with per-row float scales, and the tokenizer. The firmware reads everything from the header, so
  nothing about the model is hard-coded in C.
- **Install:** the SD card holds `/espllm/model.bin`. At boot the firmware compares it with the flash
  partition and copies it if it differs (about 10 s), then memory-maps the partition.

## 10. C and Python twins

The model is trained on contexts built in Python and runs on contexts built in C. **If the two differ by
one character, the device quietly shows the model text it never saw in training.** So every rule exists
twice:

| C (device) | Python (pipeline) | Checked by `verify.py` |
|---|---|---|
| `tokenizer.c` | SentencePiece and a Python mirror | token ids on 300 texts |
| `device.c` | `lib/devtext.py` | intent, script flag and Device line on hundreds of requests |
| `device.c` `dev_script_hints` | `devtext.script_hints` | hint text on 130 requests |
| `calc.c` | `lib/kbtext.py` | calculator line on fixed test cases |
| `kb.c` | `lib/kbtext.py` `BM25Index` | top passage and score on 60 queries |
| `script.c` | `lib/scripttext.py` | canonical text and execution trace |
| `engine.c` | `lib/npref.py` (NumPy) | logits; int8 vs float KL divergence |

Rule for contributors: **change both, then run `sh firmware/host/build_host.sh && python pipeline/verify.py`**.

## 11. Firmware

- **Platform:** PlatformIO, Arduino on ESP-IDF, with the M5Cardputer library. IRremote handles NEC send
  and ESP8266SAM provides the voice.
- **Dual core:** the model runs on core 1. SAM speaks finished sentences on core 0, so the voice overlaps
  generation.
- **Screen:** a 1-bit console sprite (3.6 KB) with scrolling text. The boot logo is a 232 × 85 RGB565
  array in flash (`logo.h`, generated by `pipeline/tools/make_logo.py`).
- **Shared pins:** the mic and the speaker share G43, so speech stops during a mic reading. The LED is
  powered with the backlight, so the brightness is raised before the LED is lit.
- **SD layout:** `/espllm/model.bin`, `/espllm/kb.bin`, `/espllm/scripts/*.txt`.
- **Safety:** actions use clamped ranges, scripts need confirmation, and the device never connects to a
  network (Wi-Fi is used only to scan).

## 12. Testing and evaluation

| Tool | What it checks |
|---|---|
| `pipeline/verify.py` | C and Python give identical results (section 10) |
| `pipeline/eval_device.py` | 144 fresh requests with random readings: reading stated, numbers invented |
| `pipeline/eval_scripts.py` | 26 script requests (valid / exactly right) plus 4 over-the-limit requests |
| `pipeline/eval_sd.py` | 30 SD replies, 22 of them with less than 1 GB used |
| `firmware/host/host_chat` | interactive chat with the device code; `/status k=v` sets readings |
| on the device: `/ctx` | shows the exact context of the last turn |

The evals run the **C code** (through `host_chat`), not the Python model, so they measure what the device
will do. Each model is kept in `data/dN/` with its log, so models can be compared side by side.

## 13. Design decisions and lessons

| Decision | Alternative tried | Why |
|---|---|---|
| Facts come from tools; the model copies | let the model answer from training | A 2.7M model invents numbers; copying a short line is learnable |
| Rules-based request matcher | have the model choose the intent | Deterministic, testable, and identical between PC and device |
| No knowledge card when there is a Device line | always add the best card (d3) | The card's numbers distracted the model; reading accuracy fell |
| Replay all data through the matcher | trust the generated labels | Removes messages the device would misunderstand |
| Strict number filters only on device conversations (d6) | strict everywhere (d5) | Strict filters on fact answers removed too much good data |
| Script mode in the ctx (d8) | infer scripts from the question alone (d7: 4/26 right) | An explicit mode marker gave 13/26 |
| Firmware number hints (d9, d11) | let the model convert units | 13 → 16 → 23 of 26 right |
| Small-MB SD augmentation (d12) | more generated data | Free, and fixed a bug seen on the device (17 → 30 of 30) |
| Scripts twice in training (d13) | plain mix (d12: 19/26) | Recovered script accuracy without new data |
| 2.7M model | 4.8M (d2) | No better on this data, and less RAM left for context |
| One mode per message | multi-intent replies | Simpler data; "status report" covers combined readings |

**General lesson:** for a model this small, accuracy came from **better context and cleaner data, not
size.** Every big jump (d3 → d4, d7 → d8, d9 → d11) came from changing what the model is shown.

## 14. Known limits and future work

**Limits:**
- Hex IR codes in scripts can come out with address and command swapped.
- Over-the-limit requests get a shortened script instead of a refusal (the user still confirms).
- The sentence after a reading sometimes adds a number that is not in the reading (about 10% of replies).
- Open chit-chat is weak by design.

**Phase 2: boards with more memory.** The planned port is to the Waveshare ESP32-S3-RLCD-4.2, which has
16 MB flash, 8 MB PSRAM, a reflective LCD, a temperature and humidity sensor and an RTC, but no keyboard.
- **Split the firmware** into the shared portable core and `boards/<name>/` folders (screen, input, `hw.cpp`).
- **Chat from a phone** over the board's own Wi-Fi hotspot, with a small built-in web page and Run/Stop
  buttons for scripts.
- **Use the PSRAM:** a full context with Wi-Fi always on, and room for a larger model.
- **New readings and cards:** room temperature and humidity, the date and time, and time-of-day scripts.
  Then retrain.
