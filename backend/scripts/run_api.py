"""
Run the VideoAgent FastAPI server.
"""
import os

import uvicorn


def main() -> None:
    host = os.getenv("UVICORN_HOST", "0.0.0.0")
    port = int(os.getenv("UVICORN_PORT", "8000"))
    reload_enabled = os.getenv("UVICORN_RELOAD", "true").lower() == "true"
    workers = int(os.getenv("UVICORN_WORKERS", "1"))

    if reload_enabled and workers > 1:
        # Uvicorn does not support reload and multi-worker mode simultaneously.
        workers = 1

    uvicorn.run(
        "videoagent.api:app",
        host=host,
        port=port,
        reload=reload_enabled,
        workers=workers,
    )


if __name__ == "__main__":
    main()
