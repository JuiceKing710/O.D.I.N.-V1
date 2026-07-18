"""Evaluate fine-tuned diagnostic models."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def evaluate_adapter(
    adapter_path: str,
    test_data_path: str = "training/data/diagnostics.jsonl",
) -> dict:
    """Evaluate a trained LoRA adapter.

    This is a skeleton. In production, this would:
    1. Load base model + adapter
    2. Run test data through the model
    3. Compare outputs against expected results
    4. Compute metrics (BLEU, perplexity, exact match, etc.)
    """
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel
    except ImportError as e:
        logger.error(f"Required dependencies not installed: {e}")
        return {"error": str(e)}

    adapter_config_path = Path(adapter_path) / "adapter_config.json"
    if not adapter_config_path.exists():
        return {"error": f"Adapter config not found at {adapter_config_path}"}

    with open(adapter_config_path) as f:
        adapter_config = json.load(f)

    base_model = adapter_config.get("base_model", "qwen:14b")
    model_id = base_model.replace(":", "/")

    logger.info(f"Loading base model: {base_model}")
    model = AutoModelForCausalLM.from_pretrained(
        model_id, device_map="auto", trust_remote_code=True
    )
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)

    logger.info(f"Loading adapter: {adapter_path}")
    model = PeftModel.from_pretrained(model, adapter_path)

    logger.info("Adapter loaded. Running evaluation...")
    test_examples = []
    with open(test_data_path) as f:
        for line in f:
            if line.strip():
                test_examples.append(json.loads(line))

    metrics = {
        "total_examples": len(test_examples),
        "evaluated": 0,
        "avg_confidence": 0.0,
        "errors": [],
    }

    total_confidence = 0.0
    for i, example in enumerate(test_examples[:5]):
        try:
            instruction = example.get("instruction", "")
            input_text = example.get("input", "")
            expected = example.get("output", "")

            prompt = f"### Instruction:\n{instruction}\n\n### Input:\n{input_text}\n\n### Output:\n"

            inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
            with torch.no_grad():
                outputs = model.generate(**inputs, max_length=200, temperature=0.7)
            tokenizer.decode(outputs[0], skip_special_tokens=True)

            try:
                expected_obj = json.loads(expected)
                metrics["evaluated"] += 1
                total_confidence += expected_obj.get("confidence", 0.0)
            except json.JSONDecodeError:
                metrics["errors"].append(f"Example {i}: Invalid expected JSON")

        except Exception as e:
            metrics["errors"].append(f"Example {i}: {str(e)}")

    if metrics["evaluated"] > 0:
        metrics["avg_confidence"] = total_confidence / metrics["evaluated"]

    logger.info(f"Evaluation results: {metrics}")
    return metrics


if __name__ == "__main__":
    adapter = sys.argv[1] if len(sys.argv) > 1 else "training/adapters/qwen-diagnostic-v1"
    results = evaluate_adapter(adapter)
    print(json.dumps(results, indent=2))
