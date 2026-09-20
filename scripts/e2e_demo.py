"""Disposable demo for browser tests; never writes to the user's .local/demo.db."""

from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from fczhk.api import create_app
from fczhk.cli import demo_settings, seed_demo

if __name__ == "__main__":
    with TemporaryDirectory(prefix="fczhk-e2e-") as directory:
        cfg = demo_settings()
        cfg.database_url = f"sqlite:///{Path(directory) / 'demo.db'}"
        seed_demo(cfg)
        uvicorn.run(create_app(cfg), host="127.0.0.1", port=8001, log_level="warning")
