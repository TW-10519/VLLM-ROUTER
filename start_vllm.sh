#!/bin/bash
# Start vLLM server on this DGX

MODEL_NAME="${1:-meta-llama/Llama-2-7b-chat-hf}"
PORT="${2:-8000}"
GPU_COUNT="${3:-1}"

echo "=== Starting vLLM Server ==="
echo "Model: $MODEL_NAME"
echo "Port: $PORT"
echo "GPUs: $GPU_COUNT"
echo ""

# Check if vLLM is installed
if ! python3 -c "import vllm" 2>/dev/null; then
    echo "vLLM is not installed. Installing..."
    pip3 install vllm
fi

# Start vLLM with OpenAI-compatible API
echo "Starting vLLM server..."
python3 -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_NAME" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --tensor-parallel-size "$GPU_COUNT" \
    --trust-remote-code \
    --dtype auto \
    --max-model-len 4096

# If you want to run in background, add this line before the python command:
# nohup ... > vllm.log 2>&1 &
