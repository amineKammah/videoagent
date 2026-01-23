# VideoAgent

A video editing assistant with an AI-powered chat interface.

## Prerequisites

- Python 3.10+
- Node.js 18+
- npm

## Setup

### 1. Clone and configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required environment variables:
- `GEMINI_API_KEY` - Google Gemini API key
- `OPENAI_API_KEY` - OpenAI API key (optional)
- `GOOGLE_CLOUD_PROJECT` - GCP project ID (for Vertex AI)
- `GOOGLE_APPLICATION_CREDENTIALS` - Path to GCP service account JSON

### 2. Backend setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Frontend setup

```bash
cd videoagent-studio
npm install
```

## Running

Start the backend (from `/backend`):
```bash
python scripts/run_api.py
```

Start the frontend (from `/videoagent-studio`):
```bash
npm run dev
```

The app will be available at `http://localhost:3000` with the API running on `http://localhost:8000`.
