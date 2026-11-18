#!/bin/sh
# Build the PC test harness from the same sources the Cardputer uses.
cd "$(dirname "$0")" || exit 1
gcc -O2 -std=c99 -Wall -D__USE_MINGW_ANSI_STDIO=1 -o host_chat \
    host_main.c ../src/engine.c ../src/tokenizer.c ../src/kb.c ../src/calc.c ../src/chat.c ../src/tts_text.c ../src/device.c ../src/script.c -lm
