# tests/conftest.py
import sys
import os

# Add integration logic and submodules to sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(BASE_DIR, "src"))
sys.path.insert(0, os.path.join(BASE_DIR, "deps", "repo_vdag"))
sys.path.insert(0, os.path.join(BASE_DIR, "deps", "repo_glm"))