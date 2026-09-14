from pathlib import Path

from fastapi.templating import Jinja2Templates

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
TEMPLATES = Jinja2Templates(directory=str(APP_DIR / "templates"))


def static_v(rel: str) -> str:
    path = STATIC_DIR / rel
    try:
        return str(int(path.stat().st_mtime))
    except OSError:
        return "1"


TEMPLATES.env.globals["static_v"] = static_v
