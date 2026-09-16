"""Development entry point for FileFlow."""

import os

from fileflow import create_app


app = create_app()


if __name__ == "__main__":
    debug = os.getenv("FILEFLOW_DEBUG", "false").lower() == "true"
    app.run(host="127.0.0.1", port=5000, debug=debug, use_reloader=False)

