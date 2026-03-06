import logging
import logging.handlers
import sys
from pathlib import Path

import uvicorn

from app.config import config

# Setup logging
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "app.log"),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    try:
        logger.info(f"Starting Code Wrapper on {config.HOST}:{config.PORT}")
        config.validate()
        uvicorn.run(
            "app.main:app",
            host=config.HOST,
            port=config.PORT,
            reload=False,
            log_config=None,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down (interrupted)")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        raise
