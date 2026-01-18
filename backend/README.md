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

## Run API

```sh
python3 backend/scripts/run_api.py
```

Then open `http://localhost:8000/docs` for interactive Swagger docs.

## Run Streamlit UI

```sh
streamlit run backend/streamlit_app.py
```

The UI expects the FastAPI server running at `http://localhost:8000` by default.
It will auto-create a session when the API is reachable.

## Agent SDK (Gemini)

The agent runtime uses the OpenAI Agents SDK with Gemini via LiteLLM.

Required environment variables:

```sh
export GEMINI_API_KEY="your-key"
export AGENT_MODEL="gemini/gemini-3-pro-preview"
```

Endpoints:
- `POST /agent/sessions` to create a session
- `POST /agent/chat` to send a message and receive the updated story segments
- `GET /agent/sessions/{id}/plan` to fetch the current plan
- `POST /agent/sessions/{id}/render` to render the current plan

## Lint

```sh
uv pip install -e "backend[dev]"
python3 -m ruff check backend/src backend/tests backend/scripts
```

## Notes

- ffmpeg/ffprobe must be installed and on PATH.
- LLM/TTS requires Vertex AI access and credentials.
- Small shared test videos live under `assets/test_videos`.
