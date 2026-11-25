// Card scripts: a tiny language of the Cardputer's own actions and readings.
// Portable C, no allocation. Mirror of pipeline/lib/scripttext.py (keep the two identical).
//
//   repeat 5 { led red; wait 300; led off; wait 300 }
//   if battery < 20 { beep 1000 500 } else { show battery }
//   if room > 28 { face sad; sound thunder }          (RLCD board: sound, face, room, humid)
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#define SCRIPT_MAX_CHARS 200
#define SCRIPT_MAX_NODES 48
#define SCRIPT_PREFIX "Script:"

// New kinds and readings are appended, so the ids of the older ones stay the same.
enum { SK_LED, SK_BRIGHT, SK_VOL, SK_BEEP, SK_IR, SK_WAIT, SK_SHOW, SK_REPEAT, SK_IF, SK_SOUND, SK_FACE };
enum { SR_BATTERY, SR_TEMP, SR_MIC, SR_RAM, SR_UPTIME, SR_BRIGHT, SR_VOL, SR_ROOM, SR_HUMID, SR_N };
#define SCRIPT_N_SOUNDS 11
#define SCRIPT_N_FACES 10

typedef struct {
    signed char kind;
    long a, b, c;        // arguments (see scripttext.py)
    short body, other;   // first statement of the block / else block, -1 if none
    short next;          // next statement in the same list, -1 at the end
} SNode;

typedef struct {
    SNode n[SCRIPT_MAX_NODES];
    int count;
    short first;
} Script;

typedef struct {
    int (*read)(int reading, void *user);              // current value of a reading
    int (*act)(const SNode *s, void *user);            // do an action (incl. wait); nonzero = stop
    int (*show)(int reading, int value, void *user);   // print a reading; nonzero = stop
    void (*branch)(int reading, int value, int taken, void *user);  // optional (tests)
    void *user;
} ScriptIO;

extern const char *const SCRIPT_READINGS[SR_N];
extern const char *const SCRIPT_COLORS[11];
extern const char *const SCRIPT_SOUNDS[SCRIPT_N_SOUNDS];  // same names as DEV_SOUNDS (device.c)
extern const char *const SCRIPT_FACES[SCRIPT_N_FACES];    // same names as DEV_FACES; "normal" = automatic

// Returns 0 and fills s, or -1 and writes the error message (same text as Python) into err.
int script_parse(const char *text, Script *s, char *err, int errsize);
// Canonical text, e.g. "repeat 5 { led red; wait 300 }".
void script_text(const Script *s, char *out, int outsize);
// Runs the script. Returns 0 when finished, 1 when a callback asked to stop.
int script_run(const Script *s, const ScriptIO *io);
// Trace text of one action ("led red", "beep 2000 200", "wait 300").
void script_describe(const SNode *s, char *out, int outsize);

#ifdef __cplusplus
}
#endif
