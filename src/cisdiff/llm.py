"""Small wrapper around the Gemma-3-1B instruction model.

The model loads once and stays in memory. Generation is greedy
(do_sample=False), so the same prompt always gives the same output.
The extractor needs this: the same recommendation in two PDF versions must
get the same element name, or the comparator reports false differences.

Outputs go into a JSON cache on disk, keyed by model ID and prompt text.
A second run on the same PDF does not call the model again.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "google/gemma-3-1b-it"
# Public copy of the same weights. Used only when the Google repo is gated
# for the current user (no accepted license or no HF token).
FALLBACK_MODEL_ID = "unsloth/gemma-3-1b-it"
# Gemma-3-1B in bf16 needs about 2 GiB, plus room for a batch of 16 prompts.
MIN_FREE_GPU_BYTES = 4 * 1024**3


def default_cache_dir() -> Path:
    return Path(os.environ.get("CISDIFF_CACHE", Path.home() / ".cache" / "cisdiff"))


class GemmaLLM:
    """Generates text with Gemma-3-1B. Call `generate()` with a list of prompts."""

    def __init__(
        self,
        model_id: str | None = None,
        max_new_tokens: int = 48,
        batch_size: int = 16,
        cache_dir: Path | None = None,
    ):
        self.requested_model_id = model_id or os.environ.get("GEMMA_MODEL_ID", DEFAULT_MODEL_ID)
        self.model_id = self.requested_model_id
        self.max_new_tokens = max_new_tokens
        self.batch_size = batch_size
        self.cache_path = (cache_dir or default_cache_dir()) / "llm-cache.json"
        self._cache: dict[str, dict] | None = None
        # Model that produced each output of the last generate() call. A cached
        # answer keeps the name of the model that first produced it.
        self.last_models: list[str] = []
        self._model = None
        self._tokenizer = None
        self._device: str | None = None

    # ---------- cache ----------
    def _load_cache(self) -> dict[str, dict]:
        if self._cache is None:
            try:
                self._cache = json.loads(self.cache_path.read_text())
            except (OSError, ValueError):
                self._cache = {}
        return self._cache

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._cache))
        tmp.replace(self.cache_path)

    def _key(self, prompt: str, max_new_tokens: int) -> str:
        # The cache key uses the model family, not the repo name, so the
        # Google repo and its public copy share one cache. It includes the
        # precision: bf16 (GPU) and fp32 (CPU) can give different greedy
        # answers, and one comparison must not mix the two.
        precision = "bf16" if self.device == "cuda" else "fp32"
        h = hashlib.sha256(f"gemma-3-1b-it|{precision}|{max_new_tokens}|{prompt}".encode()).hexdigest()
        return h

    # ---------- device ----------
    @property
    def device(self) -> str:
        if self._device is None:
            self._device = self._pick_device()
        return self._device

    @staticmethod
    def _pick_device() -> str:
        """Use the GPU only if it has enough free memory; else use the CPU.

        Set CISDIFF_DEVICE=cpu or CISDIFF_DEVICE=cuda to choose the device yourself.
        """
        forced = os.environ.get("CISDIFF_DEVICE", "").strip().lower()
        if forced in ("cpu", "cuda"):
            return forced
        import torch

        if not torch.cuda.is_available():
            return "cpu"
        free, _total = torch.cuda.mem_get_info()
        if free < MIN_FREE_GPU_BYTES:
            log.warning(
                "Only %.1f GiB of GPU memory is free (another program is using the GPU). "
                "Using the CPU, which is slower.", free / 1024**3,
            )
            return "cpu"
        return "cuda"

    # ---------- model ----------
    def _load_model(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        try:
            from huggingface_hub.errors import GatedRepoError
        except ImportError:  # older huggingface_hub
            from huggingface_hub.utils import GatedRepoError

        def load(mid: str):
            tok = AutoTokenizer.from_pretrained(mid)
            tok.padding_side = "left"
            dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
            mdl = AutoModelForCausalLM.from_pretrained(mid, dtype=dtype)
            mdl.to(self.device)
            mdl.eval()
            mdl.generation_config.max_length = None  # max_new_tokens controls length
            return tok, mdl

        try:
            self._tokenizer, self._model = load(self.model_id)
        except (GatedRepoError, OSError) as exc:
            if self.model_id != DEFAULT_MODEL_ID or "gated" not in str(exc).lower():
                raise
            log.warning(
                "%s is gated for this user (accept the license and set HF_TOKEN). "
                "Using the public copy %s instead.",
                DEFAULT_MODEL_ID,
                FALLBACK_MODEL_ID,
            )
            self.model_id = FALLBACK_MODEL_ID
            self._tokenizer, self._model = load(self.model_id)
        log.info("Loaded %s on %s", self.model_id, self._model.device)

    def _run_batch(self, prompts: list[str], max_new_tokens: int) -> list[str]:
        import torch

        self._load_model()
        chats = [[{"role": "user", "content": p}] for p in prompts]
        texts = [
            self._tokenizer.apply_chat_template(c, tokenize=False, add_generation_prompt=True)
            for c in chats
        ]
        enc = self._tokenizer(texts, return_tensors="pt", padding=True, add_special_tokens=False)
        enc = enc.to(self._model.device)
        try:
            with torch.inference_mode():
                out = self._model.generate(
                    **enc,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    top_p=None,
                    top_k=None,
                    temperature=None,
                    pad_token_id=self._tokenizer.pad_token_id,
                )
        except torch.OutOfMemoryError as exc:
            raise RuntimeError(
                "The GPU ran out of memory (another program may be using it). "
                "Close that program, or run again with CISDIFF_DEVICE=cpu."
            ) from exc
        new = out[:, enc["input_ids"].shape[1]:]
        return [t.strip() for t in self._tokenizer.batch_decode(new, skip_special_tokens=True)]

    def generate(self, prompts: Iterable[str], max_new_tokens: int | None = None) -> list[str]:
        """Return one output string for each prompt, in the same order."""
        prompts = list(prompts)
        mnt = max_new_tokens or self.max_new_tokens
        cache = self._load_cache()
        keys = [self._key(p, mnt) for p in prompts]
        todo = [i for i, k in enumerate(keys) if k not in cache]
        for start in range(0, len(todo), self.batch_size):
            idx = todo[start:start + self.batch_size]
            outs = self._run_batch([prompts[i] for i in idx], mnt)
            for i, o in zip(idx, outs):
                cache[keys[i]] = {"output": o, "model": self.model_id}
            self._save_cache()
            log.info("LLM: %d/%d prompts done", min(start + self.batch_size, len(todo)), len(todo))
        self.last_models = [cache[k]["model"] for k in keys]
        return [cache[k]["output"] for k in keys]
