"""
Tests for the solve_equation tool.
"""

import pytest
from app.tools.tool_code.solve_equation.main import solve_equation


@pytest.mark.asyncio
async def test_solve_linear_equation_concise():
    """Test solving a simple linear equation with concise output (default)."""
    equation = "2x + 5 = 13"
    result = await solve_equation(equation, concise=True)

    # Check that we got a response
    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0

    expected_solution = "x = 4"
    print("\n[CONCISE MODE]")
    print(f"Equation: {equation}")
    print(f"Expected: {expected_solution}")
    print(f"Tool Result:\n{result}")


@pytest.mark.asyncio
async def test_solve_linear_equation_detailed():
    """Test solving a simple linear equation with detailed explanations."""
    equation = "2x + 5 = 13"
    result = await solve_equation(equation, concise=False)

    # Check that we got a response
    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0

    expected_solution = "x = 4"
    print("\n[DETAILED MODE]")
    print(f"Equation: {equation}")
    print(f"Expected: {expected_solution}")
    print(f"Tool Result:\n{result}")


@pytest.mark.asyncio
async def test_solve_quadratic_equation_concise():
    """Test solving a quadratic equation with concise output."""
    equation = "x^2 - 5x + 6 = 0"
    result = await solve_equation(equation, concise=True)

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0

    expected_solution = "x = 2 or x = 3"
    print("\n[CONCISE MODE]")
    print(f"Equation: {equation}")
    print(f"Expected: {expected_solution}")
    print(f"Tool Result:\n{result}")


@pytest.mark.asyncio
async def test_solve_quadratic_equation_detailed():
    """Test solving a quadratic equation with detailed explanations."""
    equation = "x^2 - 5x + 6 = 0"
    result = await solve_equation(equation, concise=False)

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0

    expected_solution = "x = 2 or x = 3"
    print("\n[DETAILED MODE]")
    print(f"Equation: {equation}")
    print(f"Expected: {expected_solution}")
    print(f"Tool Result:\n{result}")


@pytest.mark.asyncio
async def test_solve_equation_with_latex_concise():
    """Test solving equation with LaTeX formatting (concise)."""
    equation = r"\frac{1}{2}x + 3 = 7"
    result = await solve_equation(equation, concise=True)

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0

    expected_solution = "x = 8"
    print("\n[CONCISE MODE]")
    print(f"Equation: {equation}")
    print(f"Expected: {expected_solution}")
    print(f"Tool Result:\n{result}")


@pytest.mark.asyncio
async def test_solve_invalid_equation():
    """Test error handling for invalid equation."""
    equation = "not a valid equation"

    try:
        result = await solve_equation(equation)
        # LLM might explain why it's invalid rather than error
        assert result is not None
        print(f"\nInvalid equation response:\n{result}")
    except Exception as e:
        # Or it might raise an exception
        print(f"\nExpected error for invalid equation: {e}")
        assert "Failed to solve" in str(e)


if __name__ == "__main__":
    # Run tests manually for quick testing
    import asyncio

    async def run_tests():
        print("=" * 60)
        print("Testing solve_equation tool")
        print("=" * 60)

        await test_solve_linear_equation_concise()
        await test_solve_linear_equation_detailed()
        await test_solve_quadratic_equation_concise()
        await test_solve_quadratic_equation_detailed()
        await test_solve_equation_with_latex_concise()
        await test_solve_invalid_equation()

        print("\n" + "=" * 60)
        print("All tests completed!")
        print("=" * 60)

    asyncio.run(run_tests())
