"""Message Batches API helpers: submit / status / collect, with state on disk.

Each job (e.g. "curriculum", "conversations") keeps:
  data/batches/<job>.json             batch ids
  data/batches/<job>_manifest.jsonl   custom_id -> metadata used to build the prompt
  data/batches/<job>_results.jsonl    parsed JSON outputs (after collect)
"""
import json
import os
import time

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from . import gemini
from .common import BATCH_DIR, cfg, read_jsonl, write_jsonl

MAX_PER_BATCH = 10_000  # API limit is 100k / 256 MB; smaller batches finish and fail independently


def _client():
    """Anthropic client. Keys that aren't scoped to a workspace need ANTHROPIC_WORKSPACE_ID (in .env)."""
    ws = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    return anthropic.Anthropic(default_headers={"anthropic-workspace-id": ws} if ws else None)


def make_params(model, effort, system, user, schema):
    return MessageCreateParamsNonStreaming(
        model=model,
        max_tokens=cfg.MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
        # Opus 5.5 always thinks; effort is the cost/quality dial.
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    )


def estimate_cost(model, items, est_output_tokens):
    """Rough cost of a batch run in USD (batch = 50% of list price)."""
    in_tok = sum(len(p["system"]) + len(p["messages"][0]["content"]) for _, p, _ in items) / 3.8
    out_tok = est_output_tokens * len(items)
    pin = cfg.PRICE_INPUT.get(model, 0.0)
    pout = cfg.PRICE_OUTPUT.get(model, 0.0)
    return in_tok, out_tok, 0.5 * (in_tok * pin + out_tok * pout) / 1e6


def submit(job, items, model, est_output_tokens, yes=False):
    """items: list of (custom_id, params, meta)."""
    if cfg.PROVIDER == "gemini":
        return gemini.submit(job, items, model, est_output_tokens, yes)
    state_path = BATCH_DIR / f"{job}.json"
    if state_path.exists():
        raise SystemExit(f"{state_path} exists - job already submitted. Use 'status'/'collect', "
                         f"or delete it to start over.")
    in_tok, out_tok, usd = estimate_cost(model, items, est_output_tokens)
    print(f"{job}: {len(items)} requests to {model}")
    print(f"  est. input  {in_tok / 1e6:.2f}M tokens")
    print(f"  est. output {out_tok / 1e6:.2f}M tokens (incl. thinking)")
    print(f"  est. cost   ~${usd:,.0f} at batch prices (rough; actual usage is billed)")
    if not yes:
        raise SystemExit("Dry run only. Re-run with --yes to submit.")
    client = _client()
    write_jsonl(BATCH_DIR / f"{job}_manifest.jsonl", [{"custom_id": c, **m} for c, _, m in items])
    ids = []
    for i in range(0, len(items), MAX_PER_BATCH):
        chunk = items[i:i + MAX_PER_BATCH]
        b = client.messages.batches.create(
            requests=[Request(custom_id=c, params=p) for c, p, _ in chunk])
        ids.append(b.id)
        print(f"  submitted {b.id} ({len(chunk)} requests)")
    state_path.write_text(json.dumps({"batch_ids": ids, "submitted_at": time.time()}, indent=1))


def _ids(job):
    state_path = BATCH_DIR / f"{job}.json"
    if not state_path.exists():
        raise SystemExit(f"No submitted job '{job}'. Run 'submit' first.")
    return json.loads(state_path.read_text())["batch_ids"]


def status(job):
    if cfg.PROVIDER == "gemini":
        return gemini.status(job)
    client = _client()
    done = True
    for bid in _ids(job):
        b = client.messages.batches.retrieve(bid)
        rc = b.request_counts
        print(f"{bid}: {b.processing_status}  processing={rc.processing} succeeded={rc.succeeded} "
              f"errored={rc.errored} canceled={rc.canceled} expired={rc.expired}")
        done = done and b.processing_status == "ended"
    return done


def collect(job, wait=False):
    """Download results. Returns {custom_id: parsed_json} for successful requests."""
    if cfg.PROVIDER == "gemini":
        return gemini.collect(job, wait)
    client = _client()
    while not status(job):
        if not wait:
            raise SystemExit("Not finished yet. Try again later, or pass --wait.")
        time.sleep(60)
    manifest = {r["custom_id"]: r for r in read_jsonl(BATCH_DIR / f"{job}_manifest.jsonl")}
    out, counts = [], {}
    for bid in _ids(job):
        for res in client.messages.batches.results(bid):
            kind = res.result.type
            if kind == "succeeded":
                msg = res.result.message
                if msg.stop_reason != "end_turn":
                    kind = f"stop_{msg.stop_reason}"  # refusal / max_tokens: skip
                else:
                    text = next((b.text for b in msg.content if b.type == "text"), None)
                    try:
                        out.append({"custom_id": res.custom_id, "meta": manifest.get(res.custom_id, {}),
                                    "data": json.loads(text)})
                    except (TypeError, json.JSONDecodeError):
                        kind = "bad_json"
            counts[kind] = counts.get(kind, 0) + 1
    print("results:", counts)
    write_jsonl(BATCH_DIR / f"{job}_results.jsonl", out)
    return out
