"""Tests for provider interfaces.

This test verifies that the provider interfaces can be imported and used
for structural typing. Protocol classes don't require isinstance checks,
but we verify the import works correctly.
"""

import pytest

from omnicast.media.providers.interfaces import (
    IImageProvider,
    IVideoProvider,
    ModelOption,
)


def test_model_option_creation():
    """Test that ModelOption can be instantiated correctly."""
    option = ModelOption(
        id="test-model",
        name="Test Model",
        description="A test model for unit testing"
    )
    assert option.id == "test-model"
    assert option.name == "Test Model"
    assert option.description == "A test model for unit testing"


def test_model_option_default_description():
    """Test that ModelOption description defaults to empty string."""
    option = ModelOption(id="test-model", name="Test Model")
    assert option.description == ""


def test_interfaces_import():
    """Test that provider interfaces can be imported."""
    # Protocols are structural, so we just verify they exist
    assert IImageProvider is not None
    assert IVideoProvider is not None
    assert ModelOption is not None


def test_protocol_structural_typing():
    """Test that protocols work with structural typing."""
    
    class MockImageProvider:
        """Mock implementation for testing structural typing."""
        id = "mock"
        name = "Mock Provider"
        models = [ModelOption(id="mock-model", name="Mock Model")]
        
        async def generate(self, prompt: str, *, negative: str = "", 
                         model: str | None = None, 
                         resolution: tuple[int, int] | None = None,
                         output_path: str) -> str:
            return output_path
    
    # This should work due to structural typing
    provider: IImageProvider = MockImageProvider()
    assert provider.id == "mock"
    assert provider.name == "Mock Provider"
    assert len(provider.models) == 1
