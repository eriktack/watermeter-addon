"""`python -m watermeter [data_dir] [models_dir]`: start the add-on (defaults: /data and /app/models)."""
import asyncio
import sys
from pathlib import Path

from .service import run

if __name__ == "__main__":
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/data")
    models = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/app/models")
    asyncio.run(run(data, models))
