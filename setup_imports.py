import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Add submodule paths to sys.path
sys.path.insert(0, os.path.join(BASE_DIR, "deps", "repo_vdag"))
sys.path.insert(0, os.path.join(BASE_DIR, "deps", "repo_glm"))
sys.path.insert(0, os.path.join(BASE_DIR, "src"))
