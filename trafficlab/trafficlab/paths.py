"""Where things live, in a source checkout, a zipapp, and a frozen single-file executable (PyInstaller)."""
import os
import sys


def frozen():
    return bool(getattr(sys, "frozen", False))


def app_dir():
    """Folder holding tier.json / MANIFEST / default DB: beside the executable when frozen, else above the package."""
    if frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource(*parts):
    from importlib.resources import files
    r = files("trafficlab")
    for p in parts:
        r = r / p
    return r


def read_resource(*parts):
    return resource(*parts).read_bytes()


def has_resource(*parts):
    try:
        return resource(*parts).is_file()
    except Exception:
        return False


def default_db():
    """trafficlab.db beside the app when that folder is writable, else ~/.trafficlab/."""
    d = app_dir()
    if os.access(d, os.W_OK):
        return os.path.join(d, "trafficlab.db")
    h = os.path.join(os.path.expanduser("~"), ".trafficlab")
    os.makedirs(h, exist_ok=True)
    return os.path.join(h, "trafficlab.db")
