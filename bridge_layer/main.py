import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_APP_DIR = _PROJECT_ROOT / "deps" / "repo_vdag"
_CONFIG_PATH = _PROJECT_ROOT / "config.toml"


def _load_config() -> dict:
    if not _CONFIG_PATH.exists():
        return {}
    try:
        import tomllib  # stdlib, Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return {}
    with _CONFIG_PATH.open("rb") as f:
        return tomllib.load(f).get("graphvision", {})


def run(env: str = "dev") -> None:
    cfg = _load_config()

    cmd = [sys.executable, "-m", "reflex", "run"]
    if env == "prod":
        cmd += ["--env", "prod"]
    if "frontend_port" in cfg:
        cmd += ["--frontend-port", str(cfg["frontend_port"])]

    proc_env = os.environ.copy()
    _dotenv = _PROJECT_ROOT / ".env"
    if _dotenv.exists():
        for line in _dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                proc_env.setdefault(k.strip(), v.strip())
    extra_paths = [str(_PROJECT_ROOT), str(_APP_DIR)]
    existing_pythonpath = proc_env.get("PYTHONPATH", "")
    proc_env["PYTHONPATH"] = os.pathsep.join(
        extra_paths + ([existing_pythonpath] if existing_pythonpath else [])
    )
    proc_env["GRAPHVISION_PIPELINE_HOOKS"] = "bridge_layer.hooks_registration"
    proc_env["GRAPHVISION_TITLE"] = cfg.get("title", "")
    proc_env["GRAPHVISION_ACCENT_COLOR"] = cfg.get("accent_color", "green")

    subprocess.run(cmd, cwd=_APP_DIR, env=proc_env, check=True)


if __name__ == "__main__":
    run()
