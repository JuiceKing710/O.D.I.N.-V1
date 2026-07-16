"""QLoRA fine-tuning for diagnostic models."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict:
    """Load training configuration from YAML."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_training_data(data_path: str) -> list[dict]:
    """Load JSONL training data."""
    data = []
    with open(data_path) as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
    return data


def format_prompt(example: dict) -> str:
    """Format a training example into a prompt."""
    instruction = example.get("instruction", "")
    input_text = example.get("input", "")
    output = example.get("output", "")

    if input_text:
        prompt = f"### Instruction:\n{instruction}\n\n### Input:\n{input_text}\n\n### Output:\n{output}"
    else:
        prompt = f"### Instruction:\n{instruction}\n\n### Output:\n{output}"

    return prompt


def train_lora_adapter(config_path: str = "training/config.yaml") -> None:
    """Train a LoRA adapter using the configured settings.

    This is a skeleton implementation. In production, this would:
    1. Load a base model from Ollama (requires GGUF conversion to PyTorch)
    2. Wrap it with PEFT QLoRA
    3. Fine-tune on the training data
    4. Save the adapter weights
    """
    config = load_config(config_path)
    data = load_training_data(config["data_path"])

    logger.info(f"Loaded {len(data)} training examples")
    logger.info(f"Base model: {config['model_id']}")
    logger.info(f"LoRA rank: {config['lora_r']}, alpha: {config['lora_alpha']}")
    logger.info(f"Output directory: {config['output_dir']}")

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from peft import LoraConfig, get_peft_model
        from datasets import Dataset
    except ImportError as e:
        logger.error(f"Required dependencies not installed: {e}")
        logger.info("Install with: pip install torch transformers peft datasets bitsandbytes")
        sys.exit(1)

    logger.info("Loading model and tokenizer...")
    model_id = config["model_id"].replace(":", "/")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=config["use_4bit_quantization"],
        bnb_4bit_compute_dtype=torch.float16 if config["bnb_4bit_compute_dtype"] == "float16" else torch.float32,
        bnb_4bit_quant_type=config["bnb_4bit_quant_type"],
    )

    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token

    logger.info("Setting up LoRA...")
    lora_config = LoraConfig(
        r=config["lora_r"],
        lora_alpha=config["lora_alpha"],
        lora_dropout=config["lora_dropout"],
        bias=config["lora_bias"],
        task_type="CAUSAL_LM",
        target_modules=config["target_modules"],
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    logger.info("Preparing dataset...")
    formatted_data = [{"text": format_prompt(ex)} for ex in data]
    dataset = Dataset.from_dict({"text": [ex["text"] for ex in formatted_data]})

    def preprocess(examples):
        return tokenizer(examples["text"], truncation=True, max_length=512)

    dataset = dataset.map(preprocess, batched=True)

    from transformers import Trainer, TrainingArguments

    training_args = TrainingArguments(
        output_dir=config["output_dir"],
        overwrite_output_dir=False,
        num_train_epochs=config["num_epochs"],
        per_device_train_batch_size=config["per_device_train_batch_size"],
        per_device_eval_batch_size=config["per_device_eval_batch_size"],
        gradient_accumulation_steps=config["gradient_accumulation_steps"],
        warmup_steps=config["warmup_steps"],
        weight_decay=config["weight_decay"],
        logging_steps=config["logging_steps"],
        learning_rate=config["learning_rate"],
        save_steps=config["save_steps"],
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=lambda x: {
            "input_ids": torch.stack([ex["input_ids"] for ex in x]),
            "labels": torch.stack([ex["input_ids"] for ex in x]),
        },
    )

    logger.info("Starting training...")
    trainer.train()

    logger.info(f"Training complete. Adapter saved to {config['output_dir']}")
    adapter_config = {
        "base_model": config["model_id"],
        "lora_r": config["lora_r"],
        "lora_alpha": config["lora_alpha"],
        "target_modules": config["target_modules"],
    }
    config_path_out = Path(config["output_dir"]) / "adapter_config.json"
    config_path_out.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path_out, "w") as f:
        json.dump(adapter_config, f, indent=2)


if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else "training/config.yaml"
    train_lora_adapter(config_file)
