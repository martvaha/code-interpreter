from pathlib import Path
import os

# Get the current working directory or use environment variable if set
HOST_PATH = Path(os.environ.get("HOST_PATH", os.getcwd()))

# Use relative paths that will be resolved at runtime
UPLOAD_PATH = Path("uploads")
CONFIG_PATH = Path("config")
