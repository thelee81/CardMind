"""Tiny Llama-style transformer (RMSNorm, rotary, multi-query attention, SwiGLU, tied embeddings).

The math here must match firmware/src/engine.c and lib/npref.py:
  * RoPE rotates interleaved pairs (x[2i], x[2i+1]) with freq theta^(-2i/head_dim)
  * RMSNorm eps 1e-5, weights multiply after normalising
  * output logits use the token embedding matrix (tied)
"""
import math
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class ModelArgs:
    dim: int = 192
    n_layers: int = 6
    n_heads: int = 6
    n_kv_heads: int = 1
    hidden_dim: int = 512
    vocab_size: int = 2048
    max_seq_len: int = 512
    rope_theta: float = 10000.0
    dropout: float = 0.0


class RMSNorm(nn.Module):
    def __init__(self, dim, eps=1e-5):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps) * self.weight


def rope_tables(head_dim, seq_len, theta):
    freqs = 1.0 / (theta ** (torch.arange(0, head_dim, 2).float() / head_dim))
    t = torch.arange(seq_len).float()
    ang = torch.outer(t, freqs)  # (T, hd/2)
    return torch.cos(ang), torch.sin(ang)


def apply_rope(x, cos, sin):
    # x: (B, T, H, hd) -> rotate pairs (even, odd)
    xr = x.float().reshape(*x.shape[:-1], -1, 2)
    x0, x1 = xr[..., 0], xr[..., 1]
    c = cos[None, :, None, :]
    s = sin[None, :, None, :]
    out = torch.stack((x0 * c - x1 * s, x0 * s + x1 * c), dim=-1)
    return out.flatten(-2).type_as(x)


class Attention(nn.Module):
    def __init__(self, a: ModelArgs):
        super().__init__()
        self.h, self.kvh, self.hd = a.n_heads, a.n_kv_heads, a.dim // a.n_heads
        self.wq = nn.Linear(a.dim, self.h * self.hd, bias=False)
        self.wk = nn.Linear(a.dim, self.kvh * self.hd, bias=False)
        self.wv = nn.Linear(a.dim, self.kvh * self.hd, bias=False)
        self.wo = nn.Linear(self.h * self.hd, a.dim, bias=False)
        self.drop = a.dropout

    def forward(self, x, cos, sin):
        B, T, _ = x.shape
        q = self.wq(x).view(B, T, self.h, self.hd)
        k = self.wk(x).view(B, T, self.kvh, self.hd)
        v = self.wv(x).view(B, T, self.kvh, self.hd)
        q, k = apply_rope(q, cos, sin), apply_rope(k, cos, sin)
        rep = self.h // self.kvh
        k = k.repeat_interleave(rep, dim=2)
        v = v.repeat_interleave(rep, dim=2)
        q, k, v = (t.transpose(1, 2) for t in (q, k, v))
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True,
                                           dropout_p=self.drop if self.training else 0.0)
        return self.wo(y.transpose(1, 2).reshape(B, T, -1))


class FeedForward(nn.Module):
    def __init__(self, a: ModelArgs):
        super().__init__()
        self.w1 = nn.Linear(a.dim, a.hidden_dim, bias=False)
        self.w2 = nn.Linear(a.hidden_dim, a.dim, bias=False)
        self.w3 = nn.Linear(a.dim, a.hidden_dim, bias=False)

    def forward(self, x):
        return self.w2(F.silu(self.w1(x)) * self.w3(x))


class Block(nn.Module):
    def __init__(self, a: ModelArgs):
        super().__init__()
        self.attention_norm = RMSNorm(a.dim)
        self.attention = Attention(a)
        self.ffn_norm = RMSNorm(a.dim)
        self.feed_forward = FeedForward(a)
        self.drop = nn.Dropout(a.dropout)

    def forward(self, x, cos, sin):
        x = x + self.drop(self.attention(self.attention_norm(x), cos, sin))
        return x + self.drop(self.feed_forward(self.ffn_norm(x)))


class Transformer(nn.Module):
    def __init__(self, a: ModelArgs):
        super().__init__()
        self.args = a
        self.tok_embeddings = nn.Embedding(a.vocab_size, a.dim)
        self.drop = nn.Dropout(a.dropout)
        self.layers = nn.ModuleList(Block(a) for _ in range(a.n_layers))
        self.norm = RMSNorm(a.dim)
        cos, sin = rope_tables(a.dim // a.n_heads, a.max_seq_len, a.rope_theta)
        self.register_buffer("cos", cos, persistent=False)
        self.register_buffer("sin", sin, persistent=False)
        self.apply(self._init)
        for n, p in self.named_parameters():
            if n.endswith("wo.weight") or n.endswith("w2.weight"):
                nn.init.normal_(p, 0.0, 0.02 / math.sqrt(2 * a.n_layers))

    @staticmethod
    def _init(m):
        if isinstance(m, (nn.Linear, nn.Embedding)):
            nn.init.normal_(m.weight, 0.0, 0.02)

    def forward(self, idx, targets=None):
        T = idx.shape[1]
        h = self.drop(self.tok_embeddings(idx))
        for layer in self.layers:
            h = layer(h, self.cos[:T], self.sin[:T])
        logits = F.linear(self.norm(h), self.tok_embeddings.weight)
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))
        return logits, loss

    def n_params(self):
        return sum(p.numel() for p in self.parameters())
