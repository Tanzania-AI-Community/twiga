"""
Manual test script for the solve_equation function.

This script tests the actual solve_equation function that uses an LLM.
Run this manually to verify the function works correctly, but it should NOT
be run in automated test suites due to cost and external dependencies.

Usage:
    docker-compose -f docker/dev/docker-compose.yml --env-file .env run --rm app bash -c "PYTHONPATH=/app uv run python scripts/tools/test_solve_equation.py"
"""

import asyncio
import sys
import logging
from app.tools.tool_code.solve_equation.main import solve_equation

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_solve_linear_equation():
    logger.info("Testing linear equation: 2x + 5 = 13")
    try:
        result = await solve_equation("2x + 5 = 13", concise=True)
        logger.info(f"Result:\n{result}\n")
        return True
    except Exception as e:
        logger.error(f"Failed: {e}\n")
        return False


async def test_solve_linear_equation_detailed():
    logger.info("Testing linear equation (detailed): 2x + 5 = 13")
    try:
        result = await solve_equation("2x + 5 = 13", concise=False)
        logger.info(f"Result:\n{result}\n")
        return True
    except Exception as e:
        logger.error(f"Failed: {e}\n")
        return False


async def test_solve_quadratic_equation():
    logger.info("Testing quadratic equation: x^2 - 5x + 6 = 0")
    try:
        result = await solve_equation("x^2 - 5x + 6 = 0", concise=True)
        logger.info(f"Result:\n{result}\n")
        return True
    except Exception as e:
        logger.error(f"Failed: {e}\n")
        return False


async def test_solve_quadratic_equation_detailed():
    logger.info("Testing quadratic equation (detailed): x^2 - 5x + 6 = 0")
    try:
        result = await solve_equation("x^2 - 5x + 6 = 0", concise=False)
        logger.info(f"Result:\n{result}\n")
        return True
    except Exception as e:
        logger.error(f"Failed: {e}\n")
        return False


async def test_solve_with_latex():
    logger.info(r"Testing LaTeX equation: \frac{1}{2}x + 3 = 7")
    try:
        result = await solve_equation(r"\frac{1}{2}x + 3 = 7", concise=True)
        logger.info(f"Result:\n{result}\n")
        return True
    except Exception as e:
        logger.error(f"Failed: {e}\n")
        return False


async def test_invalid_equation():
    logger.info("Testing invalid equation: not a valid equation")
    try:
        result = await solve_equation("not a valid equation")
        logger.info(f"Result:\n{result}\n")
        return True
    except Exception as e:
        logger.info(f"Expected error caught: {e}\n")
        return True


async def run_all_tests():
    logger.info("=" * 70)
    logger.info("MANUAL TEST SUITE FOR SOLVE_EQUATION")
    logger.info("Testing actual LLM integration")
    logger.info("=" * 70)
    logger.info("")

    tests = [
        ("Linear equation (concise)", test_solve_linear_equation),
        ("Linear equation (detailed)", test_solve_linear_equation_detailed),
        ("Quadratic equation (concise)", test_solve_quadratic_equation),
        ("Quadratic equation (detailed)", test_solve_quadratic_equation_detailed),
        ("LaTeX equation", test_solve_with_latex),
        ("Invalid equation handling", test_invalid_equation),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            success = await test_func()
            results.append((test_name, success))
        except Exception as e:
            logger.error(f"Unexpected error in {test_name}: {e}")
            results.append((test_name, False))

    logger.info("=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)
    passed = sum(1 for _, success in results if success)
    total = len(results)
    for test_name, success in results:
        status = "✓ PASSED" if success else "✗ FAILED"
        logger.info(f"{status}: {test_name}")

    logger.info(f"\nTotal: {passed}/{total} tests passed")
    logger.info("=" * 70)

    return all(success for _, success in results)


if __name__ == "__main__":
    try:
        success = asyncio.run(run_all_tests())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
