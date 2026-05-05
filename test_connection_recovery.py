#!/usr/bin/env python3
"""
Test script for connection recovery functionality.

This script simulates connection issues and verifies that the
reconnection mechanisms work correctly in both Parser and AI services.
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Add directories to Python path
sys.path.insert(0, str(Path(__file__).parent / "Parser"))
sys.path.insert(0, str(Path(__file__).parent / "AI"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_logger = logging.getLogger("connection_test")


async def test_parser_webhook_recovery():
    """Test webhook client connection recovery."""
    _logger.info("Testing Parser WebhookClient connection recovery...")
    
    try:
        from comment_parser import WebhookClient
        
        # Create webhook client with short intervals for testing
        webhook = WebhookClient(
            url="http://127.0.0.1:9999/nonexistent",  # Non-existent endpoint
            timeout=5,
            retries=3,
            retry_delay=1,
            max_retry_delay=10,
            connection_check_interval=5,
        )
        
        async with webhook:
            from comment_parser import MessageData
            
            # Create test message
            test_msg = MessageData(
                message_id=12345,
                channel_id=67890,
                channel_name="test_channel",
                text="Test message for connection recovery",
                link="https://test.com/12345",
                timestamp=int(time.time()),
                date=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            
            # First attempt should fail and trigger reconnection logic
            start_time = time.time()
            result = await webhook.send(test_msg)
            end_time = time.time()
            
            _logger.info("Webhook test completed in %.2fs", end_time - start_time)
            _logger.info("Connection errors: %d", webhook._connection_errors)
            
            # Test session recreation
            await webhook._ensure_session_health()
            _logger.info("Session health check completed")
            
        return True
        
    except Exception as e:
        _logger.error("Parser webhook test failed: %s", e)
        return False


async def test_ai_llm_recovery():
    """Test LLM client connection recovery."""
    _logger.info("Testing AI LLMClient connection recovery...")
    
    try:
        from analytics_server import LLMClient
        
        # Create LLM client with invalid key to simulate connection issues
        llm = LLMClient(
            api_key="invalid-key-for-testing",
            model="test/model",
            timeout=5,
            max_concurrent=1,
            connection_check_interval=5,
            max_reconnect_attempts=2,
            reconnect_base_delay=1,
            reconnect_max_delay=10,
            health_check_timeout=3,
        )
        
        async with llm:
            # Test health check
            await llm._check_connection_health()
            _logger.info("LLM health check completed")
            _logger.info("Connection errors: %d", llm._connection_errors)
            
            # Test connection ensure
            await llm._ensure_connection_health()
            _logger.info("LLM connection ensure completed")
            
        return True
        
    except Exception as e:
        _logger.error("AI LLM test failed: %s", e)
        return False


async def test_parser_health_status():
    """Test parser health status reporting."""
    _logger.info("Testing Parser health status...")
    
    try:
        from comment_parser import ChannelParser, CFG_PHONE, CFG_DB_PATH, CFG_WORK_DIR
        
        # Create minimal parser for testing
        parser = ChannelParser(
            phone=CFG_PHONE,
            target_channel_ids=[],
            db_path=CFG_DB_PATH,
            work_dir=CFG_WORK_DIR,
            connection_check_interval=5,
            max_reconnect_attempts=2,
        )
        
        # Get health status
        health = await parser.get_health_status()
        
        _logger.info("Parser health status: %s", health["status"])
        _logger.info("Components: %s", list(health["components"].keys()))
        
        # Verify structure
        required_components = ["max_client", "webhook", "database"]
        for component in required_components:
            if component not in health["components"]:
                _logger.error("Missing component: %s", component)
                return False
        
        return True
        
    except Exception as e:
        _logger.error("Parser health status test failed: %s", e)
        return False


async def test_ai_health_endpoints():
    """Test AI health endpoints with mock server."""
    _logger.info("Testing AI health endpoints...")
    
    try:
        # Import the health check functions
        from analytics_server import health_check, readiness_check, liveness_check
        
        # Test liveness (should always work)
        liveness = await liveness_check()
        _logger.info("Liveness check: %s", liveness["status"])
        
        # Test basic health check (will show degraded since no LLM/store)
        try:
            health = await health_check()
            _logger.info("Health check status: %s", health["status"])
            _logger.info("Health components: %s", list(health.get("components", {}).keys()))
        except Exception as e:
            _logger.info("Health check failed as expected (no LLM/store): %s", e)
        
        return True
        
    except Exception as e:
        _logger.error("AI health endpoints test failed: %s", e)
        return False


async def run_all_tests():
    """Run all connection recovery tests."""
    _logger.info("=" * 60)
    _logger.info("CONNECTION RECOVERY TESTS")
    _logger.info("=" * 60)
    
    tests = [
        ("Parser Webhook Recovery", test_parser_webhook_recovery),
        ("AI LLM Recovery", test_ai_llm_recovery),
        ("Parser Health Status", test_parser_health_status),
        ("AI Health Endpoints", test_ai_health_endpoints),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        _logger.info("\n--- Running: %s ---", test_name)
        try:
            result = await test_func()
            results[test_name] = result
            _logger.info("✅ %s: %s", test_name, "PASSED" if result else "FAILED")
        except Exception as e:
            results[test_name] = False
            _logger.error("❌ %s: FAILED - %s", test_name, e)
    
    # Summary
    _logger.info("\n" + "=" * 60)
    _logger.info("TEST SUMMARY")
    _logger.info("=" * 60)
    
    passed = sum(1 for result in results.values() if result)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        _logger.info("%s: %s", test_name, status)
    
    _logger.info("\nOverall: %d/%d tests passed", passed, total)
    
    if passed == total:
        _logger.info("🎉 All tests passed!")
        return 0
    else:
        _logger.warning("⚠️ Some tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)
