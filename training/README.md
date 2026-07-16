# O.D.I.N. Fine-Tuning Training Pipeline

This directory contains scripts and configurations for fine-tuning the Qwen model with custom diagnostic data using QLoRA (Quantized Low-Rank Adaptation).

## Quick Start

### 1. Install Dependencies

```bash
pip install -e ".[finetuning]"
```

This installs:
- `torch` — PyTorch deep learning framework
- `peft` — Parameter-Efficient Fine-Tuning library
- `transformers` — Hugging Face model library
- `datasets` — Dataset utilities
- `bitsandbytes` — Quantization support
- `pyyaml` — Configuration parsing

### 2. Prepare Training Data

Edit `training/data/diagnostics.jsonl` with your training examples. Each line should be a JSON object:

```json
{
  "instruction": "Analyze system health",
  "input": "CPU: 85%, Memory: 78%, Disk: 92%",
  "output": "{\"diagnosis\": \"System under load\", \"severity\": \"medium\", \"recommended_actions\": [\"Monitor memory\"], \"confidence\": 0.87}"
}
```

**Fields:**
- `instruction`: What the model should do
- `input`: Context/data to analyze
- `output`: Expected response (JSON format recommended)

### 3. Configure Training

Edit `training/config.yaml` to adjust:

```yaml
lora_r: 16                  # LoRA rank (higher = more capacity, more VRAM)
lora_alpha: 32              # Scaling factor
num_epochs: 3               # Training passes over data
learning_rate: 5e-4         # Step size
per_device_train_batch_size: 2  # Batch size per GPU/CPU
```

**For low-VRAM systems:**
- Reduce `lora_r` to 8
- Reduce batch sizes to 1–2
- Set `use_4bit_quantization: true`

### 4. Train the Adapter

```bash
python training/train.py training/config.yaml
```

This will:
1. Load the base Qwen model from Ollama
2. Wrap it with PEFT QLoRA
3. Fine-tune on your data
4. Save adapter weights to `training/adapters/`

**Output:**
```
training/adapters/
├── adapter_config.json      # LoRA configuration
├── adapter_model.bin        # LoRA weights
└── training_args.bin        # Training state
```

### 5. Evaluate the Adapter

```bash
python training/evaluate.py training/adapters/qwen-diagnostic-v1
```

Returns metrics like confidence, accuracy, and per-example results.

### 6. Use the Adapter in O.D.I.N.

The adapter can be loaded in the system. In `JarvisCore`, pass the adapter path:

```python
from training.inference import OllamaAdapterBridge

bridge = OllamaAdapterBridge(base_model="qwen:14b")
response = await bridge.generate_with_adapter(prompt, "qwen-diagnostic-v1")
```

Or via the UI:
1. Go to Settings → Models
2. Select "Load LoRA Adapter"
3. Choose the adapter from `training/adapters/`

## Training Data Format

Each example is a **supervised fine-tuning** pair:

```json
{
  "instruction": "Diagnose the system issue",
  "input": "Error: Permission denied on /var/log, Disk usage: 95%",
  "output": "{\"diagnosis\": \"Permission issue + full disk\", \"severity\": \"high\", \"recommended_actions\": [\"Fix permissions\", \"Clean disk\"], \"confidence\": 0.92}"
}
```

### Best Practices

1. **Keep outputs consistent:** If using JSON, always format identically
2. **Diverse instructions:** Vary instruction phrasing to improve generalization
3. **Clear inputs:** Make diagnostic data realistic and specific
4. **Quality > Quantity:** 100 well-crafted examples beat 1000 noisy ones
5. **Balance:** Mix easy, medium, and hard diagnostic scenarios

## Configuration Reference

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `model_id` | `qwen:14b` | Base model to fine-tune |
| `lora_r` | 16 | LoRA rank (2-64 typical) |
| `lora_alpha` | 32 | Scaling (usually 2x rank) |
| `lora_dropout` | 0.05 | Regularization |
| `num_epochs` | 3 | Full passes over data |
| `learning_rate` | 5e-4 | Optimizer step size |
| `per_device_train_batch_size` | 2 | Batch size |
| `max_grad_norm` | 1.0 | Gradient clipping |
| `use_4bit_quantization` | true | Memory efficiency |

## Performance Tips

### Reduce Training Time
- Decrease `num_epochs` to 1–2
- Increase `per_device_train_batch_size` (if VRAM allows)
- Skip validation with `eval_steps: 0`

### Improve Quality
- Increase `num_epochs` to 5+
- Reduce `learning_rate` to 1e-4
- Add more diverse training examples
- Use larger `lora_r` (32–64)

### Low VRAM (<8GB)
```yaml
lora_r: 8
per_device_train_batch_size: 1
gradient_accumulation_steps: 8
use_4bit_quantization: true
bnb_4bit_quant_type: "nf4"
```

### High VRAM (24GB+)
```yaml
lora_r: 64
per_device_train_batch_size: 8
gradient_accumulation_steps: 1
use_4bit_quantization: false
```

## Troubleshooting

### OOM (Out of Memory)
- Reduce batch size or LoRA rank
- Enable 4-bit quantization
- Reduce max sequence length in training script

### Slow Training
- Check GPU is being used: `nvidia-smi` or `torch.cuda.is_available()`
- Increase batch size (if VRAM allows)
- Reduce logging frequency

### Poor Quality Output
- Add more training data (minimum 50–100 examples)
- Check data format consistency
- Try different learning rates
- Train for more epochs

## Advanced: Custom Architectures

To fine-tune a different model:

1. Edit `config.yaml`:
   ```yaml
   model_id: "llama2:13b"  # or any Ollama model
   ```

2. Update target modules in `config.yaml`:
   ```yaml
   target_modules:
     - "q_proj"      # Query projection
     - "v_proj"      # Value projection
     - "k_proj"      # Key projection (optional)
   ```

## Integration with O.D.I.N.

### Auto-Load Adapters on Startup

In `app_factory.py`:

```python
def get_adapter_bridge() -> OllamaAdapterBridge:
    settings = get_settings_store().read()
    adapter_name = settings.get("active_adapter")
    bridge = OllamaAdapterBridge()
    if adapter_name:
        bridge.prepare_for_inference(adapter_name, merge=False)
    return bridge
```

### Custom Diagnostic Endpoint

```python
@app.post("/api/v1/chat/diagnostic")
async def diagnostic_chat(text: str, use_adapter: bool = True):
    if use_adapter:
        response = await bridge.generate_with_adapter(text, "diagnostic-v1")
    else:
        response = await core.lm_provider.generate(text, context=[])
    return {"diagnosis": response}
```

## References

- [PEFT Documentation](https://github.com/huggingface/peft)
- [QLoRA Paper](https://arxiv.org/abs/2305.14314)
- [Ollama Models](https://ollama.ai/library)

## Support

For issues, check:
1. Data format in `diagnostics.jsonl`
2. VRAM availability (`nvidia-smi` or `torch.cuda.is_available()`)
3. Model exists locally (`ollama pull qwen:14b`)
4. Dependencies installed (`pip show torch peft`)
