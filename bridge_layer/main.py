import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run(env: str = "dev") -> None:
    cmd = [sys.executable, "-m", "reflex", "run"]
    if env == "prod":
        cmd += ["--env", "prod"]
    subprocess.run(cmd, cwd=_PROJECT_ROOT, check=True)


if __name__ == "__main__":
    run()
