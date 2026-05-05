#!/usr/bin/env python3
"""
Health check script for Parser service.

This script can be used to monitor the parser's health status
by checking its internal components via the get_health_status method.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Add the current directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent))

from comment_parser import ChannelParser, CFG_PHONE, CFG_CHANNEL_IDS, CFG_DB_PATH, CFG_WORK_DIR
from comment_parser import CFG_POLL_INTERVAL, CFG_FETCH_BACKWARD, CFG_WEBHOOK_URL
from comment_parser import CFG_WEBHOOK_TIMEOUT, CFG_WEBHOOK_RETRIES, CFG_WEBHOOK_RETRY_DELAY
from comment_parser import CFG_WEBHOOK_FAIL_SAFE, CFG_CONNECTION_CHECK_INTERVAL
from comment_parser import CFG_MAX_RECONNECT_ATTEMPTS, CFG_RECONNECT_BASE_DELAY
from comment_parser import CFG_RECONNECT_MAX_DELAY, CFG_HEARTBEAT_TIMEOUT

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
_logger = logging.getLogger("health_check")


async def check_parser_health() -> None:
    """Check parser health without starting the full parsing loop."""
    try:
        # Create parser instance
        parser = ChannelParser(
            phone=CFG_PHONE,
            target_channel_ids=CFG_CHANNEL_IDS,
            db_path=CFG_DB_PATH,
            work_dir=CFG_WORK_DIR,
            poll_interval=CFG_POLL_INTERVAL,
            fetch_backward=CFG_FETCH_BACKWARD,
            webhook_url=CFG_WEBHOOK_URL,
            webhook_timeout=CFG_WEBHOOK_TIMEOUT,
            webhook_retries=CFG_WEBHOOK_RETRIES,
            webhook_retry_delay=CFG_WEBHOOK_RETRY_DELAY,
            webhook_fail_safe=CFG_WEBHOOK_FAIL_SAFE,
            connection_check_interval=CFG_CONNECTION_CHECK_INTERVAL,
            max_reconnect_attempts=CFG_MAX_RECONNECT_ATTEMPTS,
            reconnect_base_delay=CFG_RECONNECT_BASE_DELAY,
            reconnect_max_delay=CFG_RECONNECT_MAX_DELAY,
            heartbeat_timeout=CFG_HEARTBEAT_TIMEOUT,
        )
        
        # Get health status
        health = await parser.get_health_status()
        
        # Output as JSON
        print(json.dumps(health, indent=2, ensure_ascii=False))
        
        # Exit with appropriate code
        if health["status"] == "ok":
            sys.exit(0)
        elif health["status"] == "degraded":
            sys.exit(1)
        else:
            sys.exit(2)
            
    except Exception as e:
        error_info = {
            "status": "error",
            "timestamp": "unknown",
            "service": "health_check_script",
            "error": str(e)
        }
        print(json.dumps(error_info, indent=2, ensure_ascii=False))
        sys.exit(3)


if __name__ == "__main__":
    asyncio.run(check_parser_health())
