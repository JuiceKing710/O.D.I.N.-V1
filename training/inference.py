"""Inference with fine-tuned adapters.

This module shows how to use trained LoRA adapters with the O.D.I.N. system.
Adapters can be selected in Settings and will be loaded automatically.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AdapterLoader:
    """Loads and manages LoRA adapters for models."""

    def __init__(self, adapter_dir: Path | str = "training/adapters") -> None:
        self.adapter_dir = Path(adapter_dir)
        self.adapter_dir.mkdir(parents=True, exist_ok=True)
        self._loaded_adapter: dict[str, Any] | None = None

    def list_adapters(self) -> list[str]:
        """List available adapters."""
        adapters = []
        for item in self.adapter_dir.iterdir():
            if item.is_dir() and (item / "adapter_config.json").exists():
                adapters.append(item.name)
        return sorted(adapters)

    def get_adapter_info(self, adapter_name: str) -> dict[str, Any] | None:
        """Get metadata for an adapter."""
        config_path = self.adapter_dir / adapter_name / "adapter_config.json"
        if not config_path.exists():
            return None
        try:
            with open(config_path) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load adapter config: {e}")
            return None

    def load_adapter(self, adapter_name: str) -> bool:
        """Load an adapter. Returns True if successful."""
        try:
            adapter_info = self.get_adapter_info(adapter_name)
            if adapter_info is None:
                logger.error(f"Adapter not found: {adapter_name}")
                return False

            self._loaded_adapter = {
                "name": adapter_name,
                "path": str(self.adapter_dir / adapter_name),
                "config": adapter_info,
            }
            logger.info(f"Loaded adapter: {adapter_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to load adapter: {e}")
            return False

    def get_loaded_adapter(self) -> dict[str, Any] | None:
        """Get currently loaded adapter info."""
        return self._loaded_adapter


class OllamaAdapterBridge:
    """Bridge to use LoRA adapters with Ollama models.

    Ollama doesn't natively support LoRA, so this demonstrates how to:
    1. Convert Ollama GGUF to PyTorch
    2. Load LoRA adapter
    3. Merge or run with adapter
    4. Convert back if needed
    """

    def __init__(self, base_model: str = "qwen:14b") -> None:
        self.base_model = base_model
        self.loader = AdapterLoader()

    def prepare_for_inference(
        self, adapter_name: str, merge: bool = False
    ) -> bool:
        """Prepare model + adapter for inference.

        Args:
            adapter_name: Name of adapter to load
            merge: If True, merge adapter into base model weights
                   If False, apply adapter at inference time (lower VRAM)
        """
        if not self.loader.load_adapter(adapter_name):
            return False

        adapter_info = self.loader.get_loaded_adapter()
        if adapter_info is None:
            return False

        logger.info(
            f"Using adapter: {adapter_name} (LoRA rank: {adapter_info['config'].get('lora_r')})"
        )
        return True

    async def generate_with_adapter(
        self, prompt: str, adapter_name: str
    ) -> str | None:
        """Generate text using base model + adapter.

        In a real implementation, this would:
        1. Load base model
        2. Apply adapter
        3. Run inference
        4. Return results
        """
        if not self.prepare_for_inference(adapter_name):
            return None

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from peft import PeftModel
        except ImportError:
            logger.error("Required dependencies not installed")
            return None

        adapter_info = self.loader.get_loaded_adapter()
        if adapter_info is None:
            return None

        model_id = self.base_model.replace(":", "/")
        logger.info(f"Loading model: {model_id}")

        model = AutoModelForCausalLM.from_pretrained(
            model_id, device_map="auto", trust_remote_code=True
        )
        tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)

        logger.info(f"Loading adapter: {adapter_info['path']}")
        model = PeftModel.from_pretrained(model, adapter_info["path"])

        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            outputs = model.generate(**inputs, max_length=200, temperature=0.7)

        response = tokenizer.decode(outputs[0], skip_special_tokens=True)
        return response


# Example usage
if __name__ == "__main__":
    loader = AdapterLoader()

    print("Available adapters:")
    for adapter in loader.list_adapters():
        info = loader.get_adapter_info(adapter)
        print(f"  - {adapter}")
        if info:
            print(f"    Base model: {info.get('base_model')}")
            print(f"    LoRA rank: {info.get('lora_r')}")

    if loader.list_adapters():
        adapter_name = loader.list_adapters()[0]
        bridge = OllamaAdapterBridge()

        import asyncio

        prompt = "### Instruction:\nAnalyze system health\n\n### Input:\nCPU: 50%, Memory: 60%\n\n### Output:\n"

        async def demo():
            result = await bridge.generate_with_adapter(prompt, adapter_name)
            if result:
                print(f"\nGenerated response:\n{result}")

        asyncio.run(demo())
