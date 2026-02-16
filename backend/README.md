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
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="global"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
export VERTEXAI_PROJECT="your-vertex-project-id"
export VERTEXAI_LOCATION="global"
export AGENT_MODEL="vertex_ai/gemini-3-pro-preview"
```

Use `VERTEXAI_PROJECT` for Vertex model calls. Keep `GOOGLE_CLOUD_PROJECT`
for storage/other GCP services if you need them on a different project.

Endpoints:
- `POST /agent/sessions` to create a session
- `POST /agent/chat` to send a message and receive the updated storyboard
- `GET /agent/sessions/{id}/storyboard` to fetch the current storyboard
- `POST /agent/sessions/{id}/render` to render the current storyboard

## Lint

```sh
uv pip install -e "backend[dev]"
python3 -m ruff check backend/src backend/tests backend/scripts
```

## Notes

- ffmpeg/ffprobe must be installed and on PATH.
- LLM/TTS requires Vertex AI access and credentials.
- Small shared test videos live under `assets/test_videos`.
