"""
Shared pytest setup.

The app reads required configuration at import time and the AI layer is
mandatory, so provide dummy keys here — before any test module imports the app.
Real OpenAI/Anthropic calls are mocked in the tests.
"""
import os

os.environ["SENSE_API_KEY"] = "test-api-key-12345"
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
