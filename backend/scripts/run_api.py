"""
Run the VideoAgent FastAPI server.
"""
import uvicorn


def main() -> None:
    uvicorn.run(
        "videoagent.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
