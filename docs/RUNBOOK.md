# CardMind runbook

Step-by-step procedures for building, testing, flashing and debugging CardMind (formerly espLLM).
Background is in `README.md` and the rules that keep the C and Python code in step are in `docs/DESIGN.md` (section 10).

## Current status (2026-11-17, device assistant)

| Item | State |
|---|---|
| Pipeline (steps 00–09, verify, chat) | Done. The demo run in `data_demo/` passes `verify.py`. |
| Firmware build | Compiles with the SAM voice. Uses 33 KB static RAM (10%) and 0.68 MB flash (22% of app0). |
| Trained model | **2026-11-16:** 2.68M params, best val loss 0.890 (6,000 steps, about 11 min on an RTX A4000, CUDA torch 2.12.1+cu130). `verify.py` passes all checks. `model.bin` (2.77 MB) is flashed to 0x310000. |
| Data | Gemini: 2,001 cards and 23,565 conversations (5.45M tokens), $10.14 in total. |
| SD card | Now mounts: on boot the firmware looks for `/sd/espllm/model.bin`. Copy `data/sd_card/espllm/` onto the card to enable the knowledge base (`kb.bin`, 0.97 MB). |
| v2 (grounded data) | Step 4 now uses the card each conversation was written from when search picks a worse one (15,755 turns), cuts turns that drift from the calculator's numbers (1,008 cut, 2,375 kept), and keeps about 10% of card/reply mismatches. Flashed. v1 is backed up in `data/v1/`. |
| v3 (bigger model, on device) | dim 224, 8 layers, 7 heads, hidden 640, dropout 0.1: 4.82M params, `model.bin` 4.93 MB (flash partition fits about 5.1 MB). Best val loss 0.953 (v2 1.016); it started overfitting around step 5,750. On device: **ctx 355** (RAM-limited, was 512), **44 KB free RAM**. v2 is in `data/v2/`, v1 in `data/v1/`. |
| v4 | v3 shape trained on round 1 + round 2 data (38,115 conversations; round 2 = `03 --round 2`, new angles and themes, Bolt states exact results first). 8,000 steps, best val loss 0.918, train/val gap about 0.10 (v3: 0.20). Gemini total **$16.64**. Device: ctx 355, 44 KB free RAM. Backups in `data/v1`..`data/v4`. |
| Grounding eval | `python pipeline/eval_grounding.py data/v3/model.bin data/sd_card/espllm/model.bin`. Calculator drift (of 15): v1 10, v2 8, v3 4, **v4 1**. Correct result stated first: v3 4, **v4 13**. Card overlap: 0.30 / 0.31 / 0.35 / **0.36**. |
| v5 (maths only, 2026-11-17) | `SUBJECTS = ("maths",)` in `config.py`: science cards and conversations are left out of the KB and the training set (still on disk). The calculator now handles fractions (`3/4 + 1/8 = 7/8 (or 0.875)`), mixed numbers, `of` (`3/4 of 20 = 15`), percentages (`25% of 80`) and lone conversions (`11/4 = 2 3/4`), and C matches Python on 3,045 fuzz cases. Step 4 cuts replies that write the sum with a wrong answer (`9 x 9 = 36`), and puts the result first in replies that never state it (`STATE_RESULT_FIRST`). The TTS reads `2 3/4` as "two and three quarters". 22,207 conversations. Three runs: **v5a** 2.7M params (worse: whole 9/15, fractions 1/15), **v5b** 4.8M without result-first (fractions 0/15), **v5c** 4.8M with result-first (chosen). Backups in `data/v4/{dataset,tokenizer,code}` and `data/v5a`..`data/v5c`. **v5c is on the device (2026-11-17): firmware uploaded, and model.bin written to 0x310000 with esptool (hash verified).** |
| Grounding eval v5 | `python pipeline/eval_grounding.py data/v4/model.bin,data/v4/kb.bin data/v5c/model.bin,data/v5c/kb.bin` (now maths questions, with a fractions group). 120 random questions, answer stated: whole numbers v4 41/60, **v5c 46/60**; fractions and % v4 6/60, **v5c 33/60**. Card overlap is about the same (0.38 vs 0.35). |
| **Device assistant "Card" (d1, 2026-11-17)** | Use case changed from the maths tutor (backed up in `backup/maths_tutor_2026-11-17/`, see its README). Card reads battery, chip temperature, RAM, SD, mic level, Wi-Fi scan, Grove I2C scan, uptime, brightness, volume, chip info, and does actions (RGB LED colour, brightness, volume, beep, IR NEC send). Request matcher: `firmware/src/device.c` + twin `pipeline/lib/devtext.py` (checked by `verify.py`); hardware: `firmware/src/hw.cpp`; the firmware puts a `Device:` line first in the ctx. Knowledge: 59 hand-written cards in `pipeline/lib/device_cards.py` (`SUBJECTS = ("device",)`). Data: `03_generate_device.py` (2,474 Gemini requests, **$3.08**; total Gemini spend $19.77, `BUDGET_USD` now $30) and `04_build_device_dataset.py` (replays every message through the matcher; 9,092 conversations kept). Model 2.68M (Wi-Fi adds 26 KB static RAM; a scan needs ~64 KB free heap), best val loss 0.355. `eval_device.py`: reading stated 131/144, invented a number 10/144; weak spots: Grove "found nothing" (4/9), chip info (5/9), SD sizes sometimes garbled, status report invents numbers (4/9). Backup in `data/d1/`. **Flashed 2026-11-17: firmware over COM3, d1 model.bin at 0x310000 (hash verified, still in flash after a boot).** |
| Wi-Fi RAM fix (2026-11-17) | On the device the Wi-Fi scan always said not enough free RAM. Now `hw.cpp` frees the engine (KV cache) for the scan via `hw_set_ram_hooks` in `main.cpp`, then re-creates it (same ctx, or 32 smaller steps down to 192). A scan restarts the chat. The 64 KB boot reserve was removed, so ctx is back to the RAM limit. Serial logs `[wifi] free heap N KB before scan`. Firmware re-flashed; kb.bin rebuilt (Wi-Fi card text). **Confirmed on the device (2026-11-17): Wi-Fi scan, readings, knowledge cards, mic, beep, LED, brightness, volume, Grove scan and IR all work.** |
| d2 test (4.8M) | Same data as d1: best val 0.361 (d1 0.355), overfits after ~3,000 steps; eval stated 128/144 (d1 130), invented 10 (d1 8); device ctx would be ~300. Not flashed; d1 stays. Backup in `data/d2/`. More data, not a bigger model, is what would help. |
| d3-d6 (2026-11-17) | **d3**: round 2 data (`03_generate_device.py --round 2`, 620 requests, $0.89; Gemini total $20.66) for status/SD/Grove/chip; no better than d1, because a long knowledge card next to the Device line distracted the model. **Fix:** with a Device line the card is left out of the ctx (`chat.c`, `kbtext.build_ctx`, step 4), and how-to questions (pins, code, "how do I") get no reading, only the card (`device.c` + `devtext.py`). **d4**: stated 140/144. Calculator: hex like `0x20` is no longer read as `0 x 20` (`calc.c` + `kbtext.py`). Step 4 now cuts device replies that skip the reading or claim a brightness change the Device line does not show. **d5**: 143/144 but fact answers got worse (fact conversations were cut too). **d6**: the strict rules only for device conversations: **stated 143/144, fact answers good**. Temperature lowered 0.7 -> **0.5** (`chat.h` + `config.py`): cleaner facts, readings 142/144. Backups `data/d3`..`data/d6`. **On the device 2026-11-17: new firmware + d6 (copied from the SD card at boot; flash read back = d6).** |
| Card scripts (d7-d9, 2026-11-17) | Script language + interpreter `firmware/src/script.c` (twin `pipeline/lib/scripttext.py`, 2,515 fuzz cases equal), firmware: Script replies are not spoken, Enter runs, any key stops, `/do /save /run /scripts`. Matcher flags script requests (`SCRIPT_CUES`) -> no instant action; ctx `Mode: script.` + firmware number hints (`dev_script_hints`: `3 s = 3000 ms. 0x20 = 32.`). Data: `03_generate_device.py --round 3` (450 requests, $0.57; Gemini total $21.26); step 4 keeps only valid scripts whose numbers match the request (canonical form), no refusals. d7 (no script mode): 4/26 right; d8 (script mode): 13/26; **d9 (hints): 16/26 right, 26/26 valid, readings 143/144**. Backups `data/d7`..`data/d9`. **On the device 2026-11-18 (script firmware + d9 on SD); checked by hand: model scripts, /do, /save, /run, /scripts, readings and actions.** |
| d10 round 4 (2026-11-18) | `03_generate_device.py --round 4`: 240 requests on d9's weak scripts (hex IR, waits over a minute, colour sequences, fades, fractions of a second), $0.29, Gemini total $21.55. Step 4 now accepts `wait 60000` x N for minutes and 0.5 s -> 500. Scripts 2,033 conversations. **d10: scripts right 17/26 but valid 24/26 (d9 26/26); readings 143/144 but invented a number 18/144 (d9 13).** Long waits now loop `wait 60000` past the limit; fades overrun. Not better overall: **d9 stays on the device**; d10 kept in `data/d10`, `data/sd_card/espllm` restored to d9. Next idea (free): hint `2 min = 120000 ms = repeat 2 { wait 60000 }` (C + Python twin, reflash). |
| d11 long-wait hint (2026-11-18) | `dev_script_hints` / `script_hints`: minutes over 60 s give `2 min = 120000 ms = repeat 2 { wait 60000 }.` (hint buffers 256). Step 4 folds runs of `wait 60000` into `repeat N { wait 60000 }`. Same data, no spend. **d11: scripts valid 26/26, right 23/26 (d9 16); readings 144/144, invented a number 19/144 (d9 13; mostly the extra sentence after mic / IR readings).** Remaining: hex IR order swapped, `ram < 300`, over-the-limit requests get a short script (user still confirms). Backup `data/d11`; `data/sd_card/espllm` = d11. Needs the firmware with the new hints. |
| d12 / d13 SD fix (2026-11-18) | Device showed "14.8 GB, 20.8GB used": `/ctx` showed `2 MB used`, so the model mis-copied small MB values (it borrowed 2.8 from the model size). Step 4 `small_sd_copies`: copies SD replies with 1-999 MB used (reply number rewritten). New `pipeline/eval_sd.py` (30 cases, 22 under 1 GB): d11 17/30. **d12: SD 30/30, readings 144/144, invented 9, scripts 19/26.** d13 = d12 data + `SCRIPT_REPEAT = 2` (scripts twice in train.jsonl): **d13: SD 30/30, scripts 23/26 valid 26/26, readings 142/144 (grove: 2 replies gave the I2C card instead of the scan), invented 15.** Chosen: **d13**, on the device 2026-11-18 (user confirmed SD reply correct); backups `data/d12`, `data/d13`; `data/sd_card/espllm` = d13. No firmware change needed. |
| Phase 2: RLCD board (2026-11-19 to 11-25) | Card runs in the RLCD Eyes firmware (fifth screen, Wi-Fi chat page, d13 unchanged, ctx 512, model in PSRAM, ~4 tokens/s per reply). TF card: model/kb copied from `/espllm/` at boot, scripts saved there. Matcher board `rlcd` (step 2 of the retrain plan): room temperature and humidity (SHTC3), clock (RTC), radar (LD2451), phone (Chronos BLE), I2C bus scan, named sounds, eyes emotion; "what is i2c" goes to the knowledge cards; LED / brightness / IR / Grove get "this board has no ..." Device lines. Cardputer matcher unchanged (0 of 7,819 training messages differ). On the board all new Device lines are right; d13 garbles them (expected; retrain next: RLCD cards, generator board mode, Gemini data). |
| RLCD knowledge cards (2026-11-25, step 3) | `pipeline/lib/rlcd_cards.py`: 51 board cards (Waveshare docs + example code + firmware), 6 ESP32-S3 cards, 20 general electronics cards (I2C, pull-ups, SPI, UART, PWM, ADC, dividers, I2S, Ohm's law, LED resistors, debouncing, decoupling, logic levels, Li-ion, baud, interrupts, FAT32, RTC, MEMS mics). RLCD-only extra stopwords. `CARDMIND_BOARD=rlcd python pipeline/09_build_kb.py` -> `data_rlcd/sd_card/espllm/kb.bin` (77 passages, 0.07 MB). `eval_kb_rlcd.py`: right card 54/55; 3/10 off-topic questions still get a card (maths numbers, "change"). C == Python kb search on 68 queries. |
| RLCD generator (2026-11-25, step 4) | `CARDMIND_BOARD=rlcd python pipeline/03_generate_rlcd.py show / submit` (2,342 requests: 1,330 device incl. room, clock, radar, phone, I2C, sound, face and the missing-hardware lines, 462 card, 300 persona, 250 scripts). Every planned example message is asserted to parse as its intent. Script language: `sound NAME`, `face NAME`, readings `room`, `humid` (C + Python, `pipeline/tools/fuzz_scripts.py`: 2,500/2,500 equal); RLCD firmware runs them and keeps the eyes animating during waits. Step 4 `key_value` knows the RLCD Device lines. The Gemini cap now counts every data folder (`data/` + `data_rlcd/`): $21.55 spent of $30. |
| RLCD r1 (2026-11-25, steps 5-6) | Full Gemini run: 2,342 requests, 9,326 conversations, $2.99 (total $24.54; `BUDGET_USD` lowered to 28). Step 4 (`CARDMIND_BOARD=rlcd`) also reuses d13 Cardputer device + script conversations (`cardputer_convs`, dropped if they mention Cardputer-only hardware; replayed through the RLCD matcher) and cuts replies naming absent hardware (`RLCD_ABSENT`: voice on/off, screen %). Dataset 13,243 conversations (3,841 from d13). Trained from scratch, 6,000 iters, best val 0.655. **r1: readings 162/162, invented 5/162; scripts valid 23/23, right 19/23 (`eval_scripts.py` RLCD_CASES).** `eval_device.py` / `eval_scripts.py` have RLCD question sets; `host_chat` line buffer 2048 (RLCD /status is longer than 512). Backup `data_rlcd/r1`; `data_rlcd/sd_card/espllm` = r1. |
| Known weaknesses (Card) | Long Device lines (status, SD, memory) are where numbers get garbled. "what is the sound level" is not matched (no reading). Card questions with no matching card can wander. |

### Next actions

1. Done 2026-11-18: script firmware + d9 on the device. The boot text now says "CardMind" (takes effect at the next reflash).
2. Long-wait-hint firmware flashed 2026-11-18; copy d11 (`data/sd_card/espllm/`) to the SD card and restart. Done; user confirmed it works.
   Firmware since then: `/ctx` command (shows the last ctx), boot logo (`firmware/src/logo.h` from `pipeline/tools/make_logo.py`, 39 KB flash). SD "20.8GB used" bug: fixed in d13, confirmed on the device.
3. Add your own notes to `data/sources/notes/` (they go into the knowledge base; `KB_SOURCE_KINDS`).
4. Phase 2: port CardMind to the Waveshare ESP32-S3-RLCD-4.2 (user has the board; N16R8 = 16 MB flash, 8 MB PSRAM, no keyboard). Plan: split firmware into shared core + `boards/cardputer/`, `boards/rlcd42/`; chat over the board's own Wi-Fi hotspot web page; new readings (SHTC3 room temp/humidity, PCF85063 clock); new cards + retrain. Check the schematic first (LED, IR, speaker, battery ADC).

---

## A. Environment check

```bash
cd CardMind   # the repo root
python -c "import torch,sentencepiece,anthropic,numpy;print('torch',torch.__version__,'cuda',torch.cuda.is_available())"
gcc --version | head -1
ls ~/.platformio/penv/Scripts/pio.exe
```

- Install missing packages with `pip install -r requirements.txt`. With an NVIDIA GPU, install the CUDA torch build from pytorch.org.
- For API steps, set `ANTHROPIC_API_KEY` (or run `ant auth login`).
- On Windows, always `export PYTHONIOENCODING=utf-8`.

## B. Pipeline

### B1. Demo plumbing test (free, about 5 minutes)

```bash
export ESPLLM_DATA=data_demo ESPLLM_DEMO=1 PYTHONIOENCODING=utf-8
python pipeline/00_demo_data.py && python pipeline/01_ingest_sources.py && \
python pipeline/04_build_dataset.py && python pipeline/05_train_tokenizer.py && \
python pipeline/06_pretokenize.py && python pipeline/07_train.py && \
python pipeline/08_export.py && python pipeline/09_build_kb.py
sh firmware/host/build_host.sh && python pipeline/verify.py
```

Pass: `verify.py` reports that the tokenizer, calculator, search and logits all match.

### B2. Real run (costs money)

```bash
unset ESPLLM_DATA ESPLLM_DEMO
export PYTHONIOENCODING=utf-8
python pipeline/01_ingest_sources.py                 # notes and manuals become passages
python pipeline/02_plan_curriculum.py submit         # prints a cost estimate only
python pipeline/02_plan_curriculum.py submit --yes   # after you approve the estimate
python pipeline/02_plan_curriculum.py status         # repeat until the batch has ended
python pipeline/02_plan_curriculum.py collect
python pipeline/03_generate_conversations.py submit  # then --yes, status and collect, as for step 2
python pipeline/04_build_dataset.py
python pipeline/05_train_tokenizer.py
python pipeline/06_pretokenize.py
python pipeline/07_train.py                          # minutes on a GPU, hours on a CPU
python pipeline/08_export.py                         # writes data/sd_card/espllm/model.bin
python pipeline/09_build_kb.py                       # writes data/sd_card/espllm/kb.bin
sh firmware/host/build_host.sh && python pipeline/verify.py
python pipeline/chat.py --show-ctx                   # spot-check the answers yourself
```

- API keys are read from the repo-root `.env` (`ANTHROPIC_API_KEY=sk-ant-api03-...`, one `=`). It needs a **Console API key** from platform.claude.com → API Keys. If the key isn't scoped to a workspace, also add `ANTHROPIC_WORKSPACE_ID=wrkspc_...`, which the pipeline sends as the `anthropic-workspace-id` header.
- When running from inside Claude Code, prefix commands with `env -u ANTHROPIC_BASE_URL -u ANTHROPIC_CUSTOM_HEADERS`. Otherwise requests go to Claude Code's local proxy (`127.0.0.1:8787`).
- **Gemini provider** (`PROVIDER = "gemini"`). Requests run directly on 16 threads, not as a batch job, so `submit --yes` blocks until done. It is resumable: rerun `submit --yes` and finished requests are skipped. `status` and `collect` work as before. `BUDGET_USD` is a hard cap on total spend, based on the token counts Gemini reports. Raw output goes to `data/batches/<job>_raw.jsonl`.
- Gemini prices in `config.py` must match ai.google.dev/pricing, because the cap depends on them. gemini-2.5-flash-lite is retired for new users. gemini-3.5-flash-lite costs $0.30 / $2.50 per 1M and comes to about $0.0015 per step 3 request.
- Gemini 3 models take `thinkingLevel` and 2.5 models take `thinkingBudget`. `pipeline/lib/gemini.py` maps effort to whichever applies.
- Batches usually finish within an hour (24 hours at most). If a terminal closes, rerun `status` and then `collect`. The batch IDs are saved under `data/batches/`.
- To make step 3 about 40× cheaper, set `GENERATOR_MODEL = "claude-haiku-5-5"` in `config.py`. Answer quality drops somewhat.
- PDF and DOCX sources are converted with `markitdown`. Scanned PDFs have no embedded text, so run them through `renderpdf` and transcribe, or OCR them first.

## C. Flash the firmware

> This replaces whatever firmware is on the Cardputer. M5Burner can restore the factory firmware.

1. Find the port. The Cardputer appears as `USB Serial Device`, `VID_303A&PID_1001`:
   ```powershell
   Get-CimInstance Win32_PnPEntity | ? Name -match 'COM\d+' | select Name, DeviceID
   ```
   If two devices list the same COMn, see troubleshooting T1.
2. Build and upload:
   ```bash
   cd firmware
   ~/.platformio/penv/Scripts/pio.exe run -t upload --upload-port COM3
   ```
3. Watch the serial log: `~/.platformio/penv/Scripts/pio.exe device monitor -p COM3 -b 115200`

## D. Load a model

**Normal route (SD card):** copy `data/sd_card/espllm/` (or `data_demo/...`) to the SD card root, so the card has
`/espllm/model.bin` and `/espllm/kb.bin`. On boot the firmware copies `model.bin` into the `model` flash partition
if it has changed (about 10 seconds, shown as "Copying model to flash..."). Retraining only needs new files on the SD card.

**No SD card (demo only):** write the model straight into the partition at 0x310000:
```bash
esptool.py --chip esp32s3 --port COM3 write_flash 0x310000 data_demo/sd_card/espllm/model.bin
```
Search is disabled without `kb.bin` on the SD card.

## E. Smoke test on the device

1. The boot screen shows `model X.X MB, ctx N, free RAM N KB`. Note the ctx and free RAM figures.
2. Type `what is 23 x 4` and press Enter. The calculator gives an exact result, and the voice speaks after the first sentence.
3. Try `/help`, `/mute`, `/talk`, `/vol 128`, `/speed 72` and `/new`.
4. The serial log shows `[N tokens in M ms] ctx: ...`. Work out tokens per second, then decide whether `MAX_SEQ_LEN` or the model size in `config.py` should change.

## F. Change behaviour safely

| Change | Where | Then |
|---|---|---|
| Character, topics, volume | `config.py`, `pipeline/lib/curriculum.py` | rerun from step 2 or 3 |
| Model size | `DIM`/`N_LAYERS`/... in `config.py` | rerun steps 7 to 9, check that it fits in the 0x4F0000 partition and in RAM |
| Text, calculator or BM25 rules | `pipeline/lib/kbtext.py` **and** `firmware/src/{tokenizer,calc,kb}.c` | rerun B1's verify, then reflash |
| Spoken words | `DICT` in `firmware/src/tts_text.c` | `host_chat.exe --say "..."`, then reflash |
| Voice character | `VOICE_PITCH/MOUTH/THROAT` in `firmware/src/tts.cpp` | reflash |
| Device generation settings | `firmware/src/chat.h` | reflash |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| **T1.** Upload fails with "could not connect" / "port busy" | Another driver (`VSP\VCOM`) has claimed the same COM number. In Device Manager, open Ports, then *USB Serial Device*, then Properties, Port Settings, Advanced, and set it to an unused port (for example COM30). Replug the Cardputer. If it still fails, hold **G0** while plugging in to force download mode. Close any open serial monitor. |
| Screen is sideways (portrait) | M5GFX ≥ 0.3 already sets the Cardputer up as 240×135 landscape, so an extra `setRotation(1)` turns it. `main.cpp` now rotates only if width < height. |
| No voice on boot | Expected while testing: `-DVOICE_DEFAULT_ON=0` in `platformio.ini`. Use `/talk`, or set it to 1 and reflash. |
| Build error mentioning `MAX_INPUT` | It's a system macro. Use a different name (`INPUT_MAX_CHARS`). |
| `no model in flash` on boot | Put `espllm/model.bin` on the SD card, or use procedure D (no SD card). |
| `model.bin too big for partition` | Shrink the model in `config.py`, or enlarge `model` in `partitions.csv` (the total must stay within 8 MB). |
| `not enough RAM for the model` / `engine init failed` | The heap is too small for ctx ≥ 192. Reduce `DIM`, `N_LAYERS` or the vocabulary, or remove static buffers. |
| `SD model.bin invalid` | The header doesn't match. Re-export with step 8 and recopy. Check that the card is FAT32. |
| `verify.py` mismatch | The C code and its Python twin have drifted apart. Diff the two implementations of the stage that failed. |
| Garbled Unicode output on Windows | `export PYTHONIOENCODING=utf-8`. |
| Claude Code shows `API Error: Connection refused` | `.claude/settings.local.json` routes Claude Code through `ANTHROPIC_BASE_URL=http://127.0.0.1:8787`. Start that local proxy, or remove the override. |
