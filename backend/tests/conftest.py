"""
Shared pytest configuration and fixtures for violation system bugfix tests.
"""
import sys
import os

# Đảm bảo backend/app có trong PYTHONPATH khi chạy pytest từ backend/tests/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
