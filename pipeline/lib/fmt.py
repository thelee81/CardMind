"""Conversation -> token ids. Mirrors firmware/src/chat.c.

  <bos> [<ctx> ctx] <usr> user <bot> bot <eot> [<ctx> ctx] <usr> user <bot> bot <eot> ...

Text segments are encoded separately (each gets SentencePiece's leading space);
special tokens are inserted by id so typed text can never forge them.
"""
BOS, EOS, CTX, USR, BOT, EOT = 1, 2, 3, 4, 5, 6


def encode_turn_prompt(enc, ctx, user):
    ids = []
    if ctx:
        ids += [CTX] + enc(ctx)
    ids += [USR] + enc(user) + [BOT]
    return ids


def encode_conversation(enc, conv):
    ids = [BOS]
    for t in conv["turns"]:
        ids += encode_turn_prompt(enc, t["ctx"], t["user"]) + enc(t["bot"]) + [EOT]
    return ids
