"""Start the API server: `uv run python -m newslens.serve`.

Settings are checked first; a configuration problem prints a plain explanation and stops.
"""

import logging
import os
import sys

import uvicorn

from newslens.api import create_app
from newslens.settings import ConfigError, load_settings


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings()
    except ConfigError as error:
        print(error, file=sys.stderr)
        sys.exit(2)
    # 127.0.0.1 by default: only this computer can connect. Docker sets API_HOST=0.0.0.0 so the
    # web container can reach it on the private Compose network (no port is published).
    host = os.environ.get("API_HOST", "127.0.0.1")
    uvicorn.run(create_app(settings), host=host, port=int(os.environ.get("API_PORT", "8000")))


if __name__ == "__main__":
    main()
