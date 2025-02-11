import pytest
from unittest.mock import Mock, patch


@pytest.fixture(autouse=True)
def mock_initialize_settings():
    
    with patch("app.config.initialize_settings") as mock_init:
        mock_init.return_value = (Mock(), Mock()) 
        yield mock_init
