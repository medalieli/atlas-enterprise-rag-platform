"""Download the immutable, safe-file reranker snapshot during image build."""

from pathlib import Path

from huggingface_hub import snapshot_download

MODEL_ID = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
MODEL_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
MODEL_LICENSE = "apache-2.0"
MODEL_PATH = Path("/models/reranker")

snapshot_download(
    repo_id=MODEL_ID,
    revision=MODEL_REVISION,
    local_dir=MODEL_PATH,
    allow_patterns=[
        "*.json",
        "*.txt",
        "*.model",
        "README.md",
        "model.safetensors",
    ],
    ignore_patterns=["*.bin", "*.py", "*.h5", "*.msgpack"],
)
if not (MODEL_PATH / "model.safetensors").is_file():
    raise RuntimeError("Pinned reranker safetensors file is missing")
if any(MODEL_PATH.rglob("*.bin")) or any(MODEL_PATH.rglob("*.py")):
    raise RuntimeError("Unsafe or mutable model artifacts were downloaded")
print(
    f"reranker_model={MODEL_ID} revision={MODEL_REVISION} "
    f"license={MODEL_LICENSE} safe_weights=yes"
)
