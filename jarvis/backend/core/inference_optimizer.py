from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InferenceConfig:
    """Configuration for inference optimization."""
    context_window: int = 4096
    batch_size: int = 1
    num_threads: int | None = None  # auto-detect if None
    use_gpu: bool = True
    quantization_preset: str = "q4"  # "q4", "q5", "q8", "fp16"
    top_k: int = 40
    top_p: float = 0.9
    temperature: float = 0.7
    repeat_penalty: float = 1.1


def auto_detect_threads() -> int:
    """Auto-detect optimal thread count from CPU core count."""
    try:
        import multiprocessing
        cores = multiprocessing.cpu_count()
        return max(1, cores - 2)  # Leave 2 cores for system
    except Exception:
        return 4  # fallback


def auto_detect_context_window(model_id: str) -> int:
    """Estimate context window from model name."""
    model_lower = model_id.lower()
    if "32k" in model_lower or "32b" in model_lower:
        return 32000
    elif "16k" in model_lower or "16b" in model_lower:
        return 16000
    elif "8k" in model_lower or "8b" in model_lower:
        return 8000
    return 4096  # default


class KVCacheOptimizer:
    """Optimizes key-value cache and context window usage."""

    @staticmethod
    def prune_context(
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        strategy: str = "recent",
    ) -> list[dict[str, str]]:
        """Prune conversation history to fit within token limit.

        Strategies:
        - 'recent': Keep system message + last N turns
        - 'hybrid': Keep system + top semantic matches + recent
        """
        if not messages:
            return messages

        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]

        if strategy == "recent":
            estimate_tokens = lambda m: len(m.get("content", "").split())
            total = sum(estimate_tokens(m) for m in system_msgs)
            kept = list(system_msgs)

            for msg in reversed(other_msgs):
                msg_tokens = estimate_tokens(msg)
                if total + msg_tokens > max_tokens:
                    break
                kept.insert(len(system_msgs), msg)
                total += msg_tokens

            return kept
        else:
            return messages

    @staticmethod
    def sliding_window_attention(
        messages: list[dict[str, str]], window_size: int = 2048
    ) -> list[dict[str, str]]:
        """Apply sliding-window attention to reduce context memory."""
        if not messages or len(messages) <= 2:
            return messages

        estimate_tokens = lambda m: len(m.get("content", "").split())
        total_tokens = sum(estimate_tokens(m) for m in messages)

        if total_tokens <= window_size:
            return messages

        system_msgs = [m for m in messages if m.get("role") == "system"]
        user_assistant_msgs = [m for m in messages if m.get("role") != "system"]

        kept = list(system_msgs)
        tokens_used = sum(estimate_tokens(m) for m in system_msgs)

        for msg in reversed(user_assistant_msgs):
            msg_tokens = estimate_tokens(msg)
            if tokens_used + msg_tokens > window_size:
                break
            kept.insert(len(system_msgs), msg)
            tokens_used += msg_tokens

        return kept


class TokenCounter:
    """Estimates and enforces token limits."""

    @staticmethod
    def estimate(text: str) -> int:
        """Rough estimate of token count (words ≈ 1.3x tokens for most models)."""
        words = len(text.split())
        return int(words * 1.3)

    @staticmethod
    def estimate_messages(messages: list[dict[str, str]]) -> int:
        """Estimate total tokens for a message list."""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            total += TokenCounter.estimate(content)
            total += 4  # per-message overhead
        return total

    @staticmethod
    def enforce_limit(text: str, limit: int) -> str:
        """Truncate text to fit within token limit."""
        words = text.split()
        estimated_per_word = 1.3
        max_words = int(limit / estimated_per_word)
        if len(words) > max_words:
            return " ".join(words[:max_words]) + "..."
        return text


class PerformanceMonitor:
    """Monitors and logs inference performance."""

    def __init__(self) -> None:
        self.metrics: list[dict[str, Any]] = []

    def log_inference(
        self,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
    ) -> None:
        """Log an inference run."""
        self.metrics.append({
            "model": model_id,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": latency_ms,
            "throughput_tokens_per_sec": completion_tokens / (latency_ms / 1000.0)
            if latency_ms > 0
            else 0,
        })
        if len(self.metrics) > 1000:
            self.metrics.pop(0)

    def recent_stats(self, n: int = 10) -> dict[str, float]:
        """Get stats from recent N inferences."""
        if not self.metrics:
            return {}
        recent = self.metrics[-n:]
        avg_latency = sum(m["latency_ms"] for m in recent) / len(recent)
        avg_throughput = sum(m["throughput_tokens_per_sec"] for m in recent) / len(recent)
        return {
            "avg_latency_ms": avg_latency,
            "avg_throughput_tokens_per_sec": avg_throughput,
            "sample_count": len(recent),
        }

    def suggest_optimizations(self) -> list[str]:
        """Suggest optimizations based on observed metrics."""
        suggestions = []
        stats = self.recent_stats(20)

        if not stats:
            return ["No inference data collected yet"]

        if stats.get("avg_latency_ms", 0) > 5000:
            suggestions.append(
                "High latency detected. Consider reducing context size or enabling GPU."
            )

        if stats.get("avg_throughput_tokens_per_sec", 0) < 10:
            suggestions.append(
                "Low throughput. Check model quantization level and available VRAM."
            )

        return suggestions or ["Performance is good. No optimizations needed."]
