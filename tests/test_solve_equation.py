"""
Tests for the solve_equation tool.

Note: These tests use mocked responses to avoid calling the LLM during test runs.
For integration testing with the actual LLM, run scripts/test_solve_equation_manual.py
"""

import pytest
from unittest.mock import AsyncMock, patch


# Mock responses for different equations
MOCK_RESPONSES = {
    "2x + 5 = 13": {
        "concise": "x = 4",
        "detailed": "Step 1: Start with 2x + 5 = 13\nStep 2: Subtract 5 from both sides: 2x = 8\nStep 3: Divide by 2: x = 4",
    },
    "x^2 - 5x + 6 = 0": {
        "concise": "x = 2 or x = 3",
        "detailed": "Step 1: Start with x^2 - 5x + 6 = 0\nStep 2: Factor: (x - 2)(x - 3) = 0\nStep 3: Apply zero product property: x = 2 or x = 3",
    },
    r"\frac{1}{2}x + 3 = 7": {
        "concise": "x = 8",
        "detailed": r"Step 1: Start with \frac{1}{2}x + 3 = 7\nStep 2: Subtract 3 from both sides: \frac{1}{2}x = 4\nStep 3: Multiply by 2: x = 8",
    },
    "not a valid equation": {
        "concise": "Error: Could not parse the equation. Please provide a valid mathematical equation.",
        "detailed": "Error: Could not parse the equation. Please provide a valid mathematical equation.",
    },
}


@pytest.mark.asyncio
@patch("app.tools.tool_code.solve_equation.main.async_llm_request")
async def test_solve_linear_equation_concise(mock_llm):
    """Test solving a simple linear equation with concise output (default)."""
    from app.tools.tool_code.solve_equation.main import solve_equation

    equation = "2x + 5 = 13"

    # Mock the LLM response
    mock_response = AsyncMock()
    mock_response.content = MOCK_RESPONSES[equation]["concise"]
    mock_llm.return_value = mock_response

    result = await solve_equation(equation, concise=True)

    # Check that we got a response
    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0
    assert result == MOCK_RESPONSES[equation]["concise"]

    print("\n[CONCISE MODE]")
    print(f"Equation: {equation}")
    print(f"Tool Result:\n{result}")


@pytest.mark.asyncio
@patch("app.tools.tool_code.solve_equation.main.async_llm_request")
async def test_solve_linear_equation_detailed(mock_llm):
    """Test solving a simple linear equation with detailed explanations."""
    from app.tools.tool_code.solve_equation.main import solve_equation

    equation = "2x + 5 = 13"

    # Mock the LLM response
    mock_response = AsyncMock()
    mock_response.content = MOCK_RESPONSES[equation]["detailed"]
    mock_llm.return_value = mock_response

    result = await solve_equation(equation, concise=False)

    # Check that we got a response
    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0
    assert result == MOCK_RESPONSES[equation]["detailed"]

    print("\n[DETAILED MODE]")
    print(f"Equation: {equation}")
    print(f"Tool Result:\n{result}")


@pytest.mark.asyncio
@patch("app.tools.tool_code.solve_equation.main.async_llm_request")
async def test_solve_quadratic_equation_concise(mock_llm):
    """Test solving a quadratic equation with concise output."""
    from app.tools.tool_code.solve_equation.main import solve_equation

    equation = "x^2 - 5x + 6 = 0"

    # Mock the LLM response
    mock_response = AsyncMock()
    mock_response.content = MOCK_RESPONSES[equation]["concise"]
    mock_llm.return_value = mock_response

    result = await solve_equation(equation, concise=True)

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0
    assert result == MOCK_RESPONSES[equation]["concise"]

    print("\n[CONCISE MODE]")
    print(f"Equation: {equation}")
    print(f"Tool Result:\n{result}")


@pytest.mark.asyncio
@patch("app.tools.tool_code.solve_equation.main.async_llm_request")
async def test_solve_quadratic_equation_detailed(mock_llm):
    """Test solving a quadratic equation with detailed explanations."""
    from app.tools.tool_code.solve_equation.main import solve_equation

    equation = "x^2 - 5x + 6 = 0"

    # Mock the LLM response
    mock_response = AsyncMock()
    mock_response.content = MOCK_RESPONSES[equation]["detailed"]
    mock_llm.return_value = mock_response

    result = await solve_equation(equation, concise=False)

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0
    assert result == MOCK_RESPONSES[equation]["detailed"]

    print("\n[DETAILED MODE]")
    print(f"Equation: {equation}")
    print(f"Tool Result:\n{result}")


@pytest.mark.asyncio
@patch("app.tools.tool_code.solve_equation.main.async_llm_request")
async def test_solve_equation_with_latex_concise(mock_llm):
    """Test solving equation with LaTeX formatting (concise)."""
    from app.tools.tool_code.solve_equation.main import solve_equation

    equation = r"\frac{1}{2}x + 3 = 7"

    # Mock the LLM response
    mock_response = AsyncMock()
    mock_response.content = MOCK_RESPONSES[equation]["concise"]
    mock_llm.return_value = mock_response

    result = await solve_equation(equation, concise=True)

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0
    assert result == MOCK_RESPONSES[equation]["concise"]

    print("\n[CONCISE MODE]")
    print(f"Equation: {equation}")
    print(f"Tool Result:\n{result}")


@pytest.mark.asyncio
@patch("app.tools.tool_code.solve_equation.main.async_llm_request")
async def test_solve_invalid_equation(mock_llm):
    """Test error handling for invalid equation."""
    from app.tools.tool_code.solve_equation.main import solve_equation

    equation = "not a valid equation"

    # Mock the LLM response
    mock_response = AsyncMock()
    mock_response.content = MOCK_RESPONSES[equation]["concise"]
    mock_llm.return_value = mock_response

    result = await solve_equation(equation)
    # LLM might explain why it's invalid rather than error
    assert result is not None
    print(f"\nInvalid equation response:\n{result}")


if __name__ == "__main__":
    # Run tests manually for quick testing
    # Note: When running manually, tests still use mocks
    import asyncio

    async def run_tests():
        print("=" * 60)
        print("Testing solve_equation tool (mocked)")
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
