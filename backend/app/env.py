"""极轻 .env 加载：backend/.env → os.environ（不覆盖已存在的变量）。

无 python-dotenv 依赖；在 app 包导入时执行一次。仅设置缺失键，避免覆盖 shell/真实环境。
"""
import os
from pathlib import Path

_loaded = False


def load_backend_env() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    env_path = Path(__file__).resolve().parent.parent / ".env"  # backend/.env
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_backend_env()
