"""Knowledge-card retrieval check for the RLCD board: does each question find the right card?

  CARDMIND_BOARD=rlcd python pipeline/eval_kb_rlcd.py

Each case is (question, a phrase the right card contains). Off-topic questions should score below
KB_MIN_SCORE (no card). Uses the same BM25 as the firmware (kbtext.BM25Index).
"""
import os
import sys

from lib.common import cfg, load_kb_passages
from lib.kbtext import BM25Index

CASES = [
    ("what is i2c?", "two-wire bus"), ("what does a pull-up resistor do", "pull-up resistor connects"),
    ("what is a pull up", "pull-up resistor connects"), ("how does spi work", "four-wire bus"),
    ("what is uart", "TX sends"), ("explain pwm", "pulse width"), ("what is an adc", "analog to digital"),
    ("how do i calculate an led resistor", "series resistor"), ("what is ohms law", "Ohm's law"),
    ("what is debouncing", "bounce"), ("why do i need a decoupling capacitor", "decoupling capacitor"),
    ("can i connect 5v to the esp32", "level shifter"), ("what is a voltage divider", "Vout"),
    ("what is i2s", "digital audio bus"), ("what is baud rate", "signal changes per second"),
    ("what is an interrupt", "interrupt makes"), ("what is fat32", "file system"),
    ("what is psram", "extra RAM outside"), ("what display does this board have", "300 x 400"),
    ("what are the display pins", "ST7305 on SPI"), ("how do i enter download mode", "download mode"),
    ("what do the leds on the board mean", "CHG is the charging"), ("what battery does it take", "18650"),
    ("how long does the battery last", "24 hours"), ("what is the rtc backup battery", "ML1220"),
    ("can i use a cr1220", "ML1220"), ("what are the tf card pins", "SDMMC"),
    ("how do i update the model", "copy a new model.bin"), ("what is on the expansion header", "2 x 8 pin"),
    ("where do i connect an i2c sensor", "no Grove port"), ("how do i wire the radar", "radar TX to pin 12"),
    ("what microphone does it have", "ES7210"), ("what sounds can you play", "woof"),
    ("what emotions can the eyes show", "look happy"), ("what are the screens", "five screens"),
    ("what does the key button do", "KEY is a user button"), ("how do i open the chat page", "rlcd-eyes.local"),
    ("the chat page does not open", "same Wi-Fi network"), ("how do i pair my phone", "Chronos"),
    ("what is humidity", "water vapour"), ("why is the room temperature too high", "subtracts 4 C"),
    ("does it have an rgb led", "no RGB LED"), ("can you speak", "no voice"),
    ("what chip does it use", "WROOM-1-N16R8"), ("how much flash does it have", "16 MB flash"),
    ("what is the flash layout", "0x650000"), ("what commands are there", "/new starts"),
    ("how do scripts work", "Run and Cancel"), ("how fast are you", "tokens per second"),
    ("when does the chime play", "hourly chime"), ("how do i program this board", "Arduino and ESP-IDF"),
    ("what is a real time clock", "keeps the date and time"), ("what is rssi", "dBm"),
    ("what is deep sleep", "deep sleep"), ("what is dbfs", "dBFS"),
]
OFF_TOPIC = ["what is 3/4 of 20", "why do shadows change", "tell me a joke", "who are you", "hello",
             "what is the capital of france", "i am bored", "thanks", "what is 12 x 7", "how do i bake bread"]


def main():
    passages = load_kb_passages()
    idx = BM25Index(passages)
    ok = 0
    for q, want in CASES:
        s, pid = idx.search(q)
        hit = pid >= 0 and s >= cfg.KB_MIN_SCORE and want in passages[pid]
        ok += hit
        if not hit or "-v" in sys.argv:
            print(f"{'ok ' if hit else 'MISS'} {s:5.2f} {q!r} -> {passages[pid][:70] if pid >= 0 else '-'}")
    print(f"right card: {ok}/{len(CASES)} (KB_MIN_SCORE {cfg.KB_MIN_SCORE})")
    shown = 0
    for q in OFF_TOPIC:
        s, pid = idx.search(q)
        if pid >= 0 and s >= cfg.KB_MIN_SCORE:
            shown += 1
            print(f"off-topic shown {s:5.2f} {q!r} -> {passages[pid][:60]}")
    print(f"off-topic questions given a card: {shown}/{len(OFF_TOPIC)}")


if __name__ == "__main__":
    main()
