import os

from . import create_app

app = create_app()
host = os.environ.get("FIZZY_HOST", "127.0.0.1")
port = int(os.environ.get("FIZZY_PORT", "47621"))
app.run(host=host, port=port, debug=False)
