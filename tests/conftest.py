import os
from dotenv import load_dotenv
import pytest


@pytest.fixture(scope="session", autouse=True)
def load_env():
    """Load environment variables from .env.example for testing."""
    env_path = os.path.join(os.path.dirname(__file__), "../.env.example")
    load_dotenv(env_path, override=True)
