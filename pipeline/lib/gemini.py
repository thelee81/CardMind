"""Gemini backend with the same submit / status / collect interface as batch.py.

Requests run directly (not through a batch job) on a thread pool, so `submit --yes`
blocks until done. It is resumable: rerun `submit --yes` and finished requests are skipped.
A hard spending cap (cfg.BUDGET_USD) is enforced from the token counts Gemini reports.

  data/batches/<job>_manifest.jsonl   custom_id -> metadata used to build the prompt
  data/batches/<job>_raw.jsonl        one line per finished request (text, finish reason, usage)
  data/batches/<job>_results.jsonl    parsed JSON outputs (after collect)
"""
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from .common import BATCH_DIR, ROOT, cfg, read_jsonl, write_jsonl

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
THINKING_BUDGET = {"low": 0, "medium": 2048, "high": 8192, "xhigh": 16384, "max": 24576}
RETRY_CODES = {429, 500, 502, 503, 504}
THINKING_LEVEL = {"low": "minimal", "medium": "low", "high": "medium", "xhigh": "high", "max": "high"}


def _thinking(model, effort):
    """Gemini 2.5 takes a token budget; Gemini 3+ takes a level."""
    if model.startswith("gemini-2"):
        return {"thinkingBudget": THINKING_BUDGET.get(effort, 0)}
    return {"thinkingLevel": THINKING_LEVEL.get(effort, "low")}


def _key():
    k = os.environ.get("GEMINI_API_KEY")
    if not k:
        raise SystemExit("GEMINI_API_KEY is not set (put it in .env).")
    return k


def _unpack(p):
    """Read the provider-neutral fields out of batch.make_params()."""
    return (p["model"], p["system"], p["messages"][0]["content"],
            p["output_config"]["format"]["schema"], p["output_config"]["effort"])


def _price(model, in_tok, out_tok):
    return (in_tok * cfg.PRICE_INPUT.get(model, 0.0) + out_tok * cfg.PRICE_OUTPUT.get(model, 0.0)) / 1e6


def _call(key, params):
    model, system, user, schema, effort = _unpack(params)
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
            "maxOutputTokens": cfg.MAX_TOKENS,
            "thinkingConfig": _thinking(model, effort),
        },
    }
    req = urllib.request.Request(URL.format(model=model), data=json.dumps(body).encode(),
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    for attempt in range(7):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_CODES or attempt == 6:
                return {"error": f"HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace')}"}
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == 6:
                return {"error": f"network: {e}"}
        time.sleep(min(60, 2 ** attempt + random.random()))


def _record(custom_id, resp):
    if "error" in resp:
        return {"custom_id": custom_id, "finish": "ERROR", "error": resp["error"], "in": 0, "out": 0}
    u = resp.get("usageMetadata", {})
    cand = (resp.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []) if not p.get("thought"))
    return {"custom_id": custom_id, "finish": cand.get("finishReason", "NONE"), "text": text,
            "in": u.get("promptTokenCount", 0),
            "out": u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)}


def _raw_path(job):
    return BATCH_DIR / f"{job}_raw.jsonl"


def _done(job):
    p = _raw_path(job)
    return {r["custom_id"]: r for r in read_jsonl(p)} if p.exists() else {}


def _spent(records, model):
    return sum(_price(model, r["in"], r["out"]) for r in records)


def submit(job, items, model, est_output_tokens, yes=False):
    in_tok = sum(len(p["system"]) + len(p["messages"][0]["content"]) for _, p, _ in items) / 3.8
    out_tok = est_output_tokens * len(items)
    done = _done(job)
    spent_before = _spent([r for r in done.values()], model)
    todo = [it for it in items if it[0] not in done or done[it[0]]["finish"] == "ERROR"]
    print(f"{job}: {len(items)} requests to {model} (Gemini, standard prices)")
    print(f"  est. input  {in_tok / 1e6:.2f}M tokens")
    print(f"  est. output {out_tok / 1e6:.2f}M tokens (incl. thinking)")
    print(f"  est. cost   ~${_price(model, in_tok, out_tok):,.2f} (rough; actual usage is billed)")
    print(f"  already done {len(items) - len(todo)}, spent on this job ~${spent_before:.2f}, on Gemini in total "
          f"~${_spent_all():.2f}; hard cap BUDGET_USD = ${cfg.BUDGET_USD:.2f} (all jobs, all data folders)")
    if not yes:
        raise SystemExit("Dry run only. Re-run with --yes to run it.")
    write_jsonl(BATCH_DIR / f"{job}_manifest.jsonl", [{"custom_id": c, **m} for c, _, m in items])
    # retried ERROR lines are superseded by later lines with the same custom_id
    key, lock = _key(), threading.Lock()
    state = {"spent": _spent_all(), "n": 0, "stopped": False}
    t0 = time.time()

    def work(cid, params):
        if state["stopped"]:
            return
        rec = _record(cid, _call(key, params))
        with lock:
            with open(_raw_path(job), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            state["spent"] += _price(model, rec["in"], rec["out"])
            state["n"] += 1
            if state["spent"] >= cfg.BUDGET_USD and not state["stopped"]:
                state["stopped"] = True
                print(f"  !! spending cap ${cfg.BUDGET_USD:.2f} reached - stopping")
            if state["n"] % 25 == 0 or state["n"] == len(todo):
                print(f"  {state['n']}/{len(todo)} done, ~${state['spent']:.2f} spent in total, "
                      f"{time.time() - t0:.0f}s", flush=True)

    with ThreadPoolExecutor(cfg.GEMINI_CONCURRENCY) as ex:
        for f in as_completed([ex.submit(work, c, p) for c, p, _ in todo]):
            f.result()
    status(job)


def _spent_all():
    """Spend across every Gemini job recorded on disk, in every data folder (data/, data_rlcd/, ...;
    not the demo folder): the cap is global, whichever board is being generated."""
    total = 0.0
    folders = {BATCH_DIR} | {d / "batches" for d in ROOT.glob("data*") if d.is_dir() and d.name != "data_demo"}
    for folder in folders:
        for p in folder.glob("*_raw.jsonl"):
            job = p.name[:-len("_raw.jsonl")]
            model = cfg.PLANNER_MODEL if job == "curriculum" else cfg.GENERATOR_MODEL
            total += _spent({r["custom_id"]: r for r in read_jsonl(p)}.values(), model)
    return total


def status(job):
    man = BATCH_DIR / f"{job}_manifest.jsonl"
    if not man.exists():
        raise SystemExit(f"No submitted job '{job}'. Run 'submit --yes' first.")
    total = sum(1 for _ in read_jsonl(man))
    done = _done(job)
    counts = {}
    for r in done.values():
        counts[r["finish"]] = counts.get(r["finish"], 0) + 1
    print(f"{job}: {len(done)}/{total} finished {counts}  (~${_spent_all():.2f} spent on Gemini in total)")
    return len(done) >= total


def collect(job, wait=False):
    if not status(job) and not wait:
        print("  (not all requests finished; collecting what there is. Rerun submit --yes to finish.)")
    manifest = {r["custom_id"]: r for r in read_jsonl(BATCH_DIR / f"{job}_manifest.jsonl")}
    out, counts = [], {}
    for cid, r in _done(job).items():
        kind = r["finish"]
        if kind == "STOP":
            try:
                out.append({"custom_id": cid, "meta": manifest.get(cid, {}), "data": json.loads(r["text"])})
                kind = "succeeded"
            except (TypeError, json.JSONDecodeError):
                kind = "bad_json"
        counts[kind] = counts.get(kind, 0) + 1
    print("results:", counts)
    write_jsonl(BATCH_DIR / f"{job}_results.jsonl", out)
    return out
