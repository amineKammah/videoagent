# VideoAgent Backend

Backend library for personalized video generation using Gemini, ffmpeg, and moviepy.

## Install (editable)

```sh
uv venv -p 3.13 .venv
source .venv/bin/activate
uv pip install -e backend
```

## Run tests

```sh
python3 backend/scripts/run_basic_tests.py
python3 backend/scripts/run_basic_tests.py --run-llm
python3 backend/scripts/run_basic_tests.py --run-e2e
```

## Lint

```sh
uv pip install -e "backend[dev]"
python3 -m ruff check backend/src backend/tests backend/scripts
```

## Notes

- ffmpeg/ffprobe must be installed and on PATH.
- LLM/TTS requires Vertex AI access and credentials.
- Small shared test videos live under `assets/test_videos`.
