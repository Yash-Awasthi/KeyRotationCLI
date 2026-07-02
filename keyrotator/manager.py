import json
import os
import datetime
import tempfile
from pathlib import Path

# Constants
KEYS_FILE = Path.home() / ".keyrotator" / "keys.json"
CONFIG_FILE = Path.home() / ".keyrotator" / "config.json"
DEFAULT_REFRESH_HOURS = 5.0
DEFAULT_MAX_WEEKLY_USES = 7

def _load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def _save_config(config: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)


def _atomic_write(path: Path, data: str):
    """Write data atomically — other readers never see partial file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(data)
        os.replace(tmp, str(path))
    except Exception:
        os.unlink(tmp)
        raise


def _escape_single_quotes(val: str) -> str:
    """Escape a string for single-quoted shell: foo'bar → 'foo'\\''bar'"""
    return val.replace("'", "'\\''")


def set_settings_path(path: str):
    config = _load_config()
    config["claude_settings_path"] = path
    _save_config(config)

def get_settings_path() -> str | None:
    return _load_config().get("claude_settings_path")

def get_current_key_name(settings_path: str) -> str | None:
    """Read the current key from settings.json and return its name if it exists."""
    p = Path(settings_path)
    if not p.exists():
        return None

    try:
        with open(p, 'r') as f:
            settings = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    existing_key_val = None
    if "env" in settings and isinstance(settings["env"], dict) and "ANTHROPIC_API_KEY" in settings["env"]:
        existing_key_val = settings["env"]["ANTHROPIC_API_KEY"]
    elif "apiKeyHelper" in settings:
        helper_str = settings["apiKeyHelper"]
        if helper_str.startswith("echo '") and helper_str.endswith("'"):
            existing_key_val = helper_str[6:-1]
        else:
            existing_key_val = helper_str

    if existing_key_val:
        keys = load_keys()
        for name, data in keys.items():
            if data.get("value") == existing_key_val:
                return name
    return None

def inject_key_into_settings(settings_path: str) -> tuple[str | None, str]:
    """Finds the best available key and injects it into Claude's settings.json.
    Also finds the current key in settings.json, and if it matches a managed key,
    marks it as exhausted.
    Returns (old_key_name, new_key_name).
    """
    p = Path(settings_path)
    if not p.exists():
        raise FileNotFoundError(f"settings.json not found at: {settings_path}")

    # Read existing settings
    with open(p, 'r') as f:
        settings = json.load(f)

    # 1. Identify the existing key value in the settings file and exhaust it
    old_key_name = get_current_key_name(settings_path)
    if old_key_name:
        try:
            exhaust_key(old_key_name)
        except ValueError:
            # If already exhausted or weekly limit reached, proceed anyway
            pass

    # 3. Find the best available key to inject
    best = get_available_key()
    if not best:
        raise ValueError("No available keys to inject. All keys are exhausted.")

    key_value = best["value"]

    # Inject into apiKeyHelper as an echo shell command (escape single quotes)
    settings["apiKeyHelper"] = f"echo '{_escape_single_quotes(key_value)}'"

    # Inject into env.ANTHROPIC_API_KEY
    if "env" not in settings or not isinstance(settings["env"], dict):
        settings["env"] = {}
    settings["env"]["ANTHROPIC_API_KEY"] = key_value

    _atomic_write(p, json.dumps(settings, indent=2) + "\n")

    return old_key_name, best["name"]


def inject_specific_key_into_settings(settings_path: str, key_name: str):
    """Inject a specific key (identified by its user-set name) into Claude's settings.json.
    Does NOT auto-select, does NOT mark the previous key as exhausted.
    Raises ValueError if key_name is not found.
    """
    p = Path(settings_path)
    if not p.exists():
        raise FileNotFoundError(f"settings.json not found at: {settings_path}")

    keys = load_keys()
    if key_name not in keys:
        raise ValueError(f"Key '{key_name}' not found. Run `kr status` to see available names.")

    key_value = keys[key_name]["value"]

    with open(p, 'r') as f:
        settings = json.load(f)

    settings["apiKeyHelper"] = f"echo '{_escape_single_quotes(key_value)}'"

    if "env" not in settings or not isinstance(settings["env"], dict):
        settings["env"] = {}
    settings["env"]["ANTHROPIC_API_KEY"] = key_value

    _atomic_write(p, json.dumps(settings, indent=2) + "\n")

def _ensure_file():
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not KEYS_FILE.exists():
        with open(KEYS_FILE, 'w') as f:
            json.dump({}, f)

def load_keys():
    _ensure_file()
    try:
        with open(KEYS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        # Corrupt or unreadable — back up and start fresh
        backup = KEYS_FILE.with_suffix(".json.bak")
        import shutil
        shutil.copy2(KEYS_FILE, backup)
        print(f"Warning: {KEYS_FILE} was corrupt. Backed up to {backup}. Starting fresh.",
              file=__import__('sys').stderr)
        save_keys({})
        return {}

def save_keys(keys):
    _ensure_file()
    _atomic_write(KEYS_FILE, json.dumps(keys, indent=4) + "\n")

def _get_current_time():
    return datetime.datetime.now(datetime.timezone.utc)

def _parse_time(time_str):
    if not time_str:
        return None
    return datetime.datetime.fromisoformat(time_str)

def _sync_epochs(key_data: dict):
    """Advances epochs if time has passed and resets exhaustion/weekly usages."""
    now = _get_current_time()
    
    refresh_hours = key_data.get("refresh_hours", DEFAULT_REFRESH_HOURS)
    
    next_refresh_str = key_data.get("next_refresh_time")
    if next_refresh_str:
        next_refresh = _parse_time(next_refresh_str)
        if now >= next_refresh:
            # How many epochs passed?
            time_passed = now - next_refresh
            epochs_passed = int(time_passed.total_seconds() // (refresh_hours * 3600)) + 1
            next_refresh += datetime.timedelta(hours=refresh_hours * epochs_passed)
            key_data["next_refresh_time"] = next_refresh.isoformat()
            key_data["is_exhausted"] = False

    next_weekly_str = key_data.get("next_weekly_reset_time")
    if next_weekly_str:
        next_weekly = _parse_time(next_weekly_str)
        if now >= next_weekly:
            time_passed = now - next_weekly
            weeks_passed = int(time_passed.total_seconds() // (7 * 24 * 3600)) + 1
            next_weekly += datetime.timedelta(days=7 * weeks_passed)
            key_data["next_weekly_reset_time"] = next_weekly.isoformat()
            key_data["weekly_usage_count"] = 0

def add_key(name: str, key_value: str, is_exhausted: bool, refresh_in_hours: float, weekly_reset_in_days: float, weekly_uses_left: int):
    keys = load_keys()
    if name in keys:
        raise ValueError(f"Key '{name}' already exists.")
    
    now = _get_current_time()
    
    weekly_usage_count = max(0, DEFAULT_MAX_WEEKLY_USES - weekly_uses_left)
    
    next_refresh_time = now + datetime.timedelta(hours=refresh_in_hours)
    next_weekly_reset_time = now + datetime.timedelta(days=weekly_reset_in_days)
    
    keys[name] = {
        "value": key_value,
        "refresh_hours": DEFAULT_REFRESH_HOURS,
        "max_weekly_uses": DEFAULT_MAX_WEEKLY_USES,
        "next_refresh_time": next_refresh_time.isoformat(),
        "next_weekly_reset_time": next_weekly_reset_time.isoformat(),
        "is_exhausted": is_exhausted,
        "weekly_usage_count": weekly_usage_count
    }
    save_keys(keys)

def update_key(name: str, is_exhausted: bool, refresh_in_hours: float, weekly_reset_in_days: float, weekly_uses_left: int):
    keys = load_keys()
    if name not in keys:
        raise ValueError(f"Key '{name}' not found.")
        
    now = _get_current_time()
    
    weekly_usage_count = max(0, DEFAULT_MAX_WEEKLY_USES - weekly_uses_left)
    next_refresh_time = now + datetime.timedelta(hours=refresh_in_hours)
    next_weekly_reset_time = now + datetime.timedelta(days=weekly_reset_in_days)
    
    keys[name]["is_exhausted"] = is_exhausted
    keys[name]["next_refresh_time"] = next_refresh_time.isoformat()
    keys[name]["next_weekly_reset_time"] = next_weekly_reset_time.isoformat()
    keys[name]["weekly_usage_count"] = weekly_usage_count
    
    save_keys(keys)

def remove_key(name: str):
    keys = load_keys()
    if name in keys:
        del keys[name]
        save_keys(keys)
    else:
        raise ValueError(f"Key '{name}' not found.")

def get_key_status(name: str, key_data: dict):
    """Calculates status, remaining time, and weekly uses."""
    _sync_epochs(key_data)
    
    now = _get_current_time()
    
    max_weekly_uses = key_data.get("max_weekly_uses", DEFAULT_MAX_WEEKLY_USES)
    weekly_uses_left = max_weekly_uses - key_data.get("weekly_usage_count", 0)
    
    # Calculate refresh string
    next_refresh_str = key_data.get("next_refresh_time")
    time_remaining_seconds = 0
    if next_refresh_str:
        next_refresh = _parse_time(next_refresh_str)
        time_until_refresh = next_refresh - now
        time_remaining_seconds = max(0, time_until_refresh.total_seconds())
        hours_left, remainder = divmod(int(time_remaining_seconds), 3600)
        minutes_left, seconds_left = divmod(remainder, 60)
        refresh_str = f"{hours_left}h {minutes_left}m {seconds_left}s"
    else:
        refresh_str = "Unknown"
        
    # Calculate weekly reset string + seconds
    next_weekly_str = key_data.get("next_weekly_reset_time")
    weekly_reset_seconds = 0
    if next_weekly_str:
        next_weekly = _parse_time(next_weekly_str)
        time_until_reset = next_weekly - now
        weekly_reset_seconds = max(0, time_until_reset.total_seconds())
        days_left = time_until_reset.days
        hours_left, remainder = divmod(time_until_reset.seconds, 3600)
        minutes_left, _ = divmod(remainder, 60)

        if days_left > 0:
            weekly_reset_str = f"{days_left}d {hours_left}h"
        else:
            weekly_reset_str = f"{hours_left}h {minutes_left}m"
    else:
        weekly_reset_str = "Unknown"

    if weekly_uses_left <= 0:
        return {
            "status": "WEEKLY_EXHAUSTED",
            "time_remaining_str": refresh_str,
            "time_remaining_seconds": time_remaining_seconds,
            "weekly_uses_left": 0,
            "can_use": False,
            "weekly_reset_str": weekly_reset_str,
            "weekly_reset_seconds": weekly_reset_seconds,
        }
        
    if key_data.get("is_exhausted"):
        return {
            "status": "EXHAUSTED",
            "time_remaining_str": refresh_str,
            "time_remaining_seconds": time_remaining_seconds,
            "weekly_uses_left": weekly_uses_left,
            "can_use": False,
            "weekly_reset_str": weekly_reset_str,
            "weekly_reset_seconds": weekly_reset_seconds,
        }

    return {
        "status": "AVAILABLE",
        "time_remaining_str": refresh_str,
        "time_remaining_seconds": time_remaining_seconds,
        "weekly_uses_left": weekly_uses_left,
        "can_use": True,
        "weekly_reset_str": weekly_reset_str,
        "weekly_reset_seconds": weekly_reset_seconds,
    }

def get_all_status():
    keys = load_keys()
    status_list = []
    # Save keys in case epochs got advanced during read
    keys_modified = False
    for name, data in keys.items():
        st = get_key_status(name, data)
        st["name"] = name
        st["value"] = data.get("value", "")
        status_list.append(st)
        keys_modified = True
        
    if keys_modified:
        save_keys(keys)
        
    return status_list

def mark_key_exhausted(name: str):
    keys = load_keys()
    if name not in keys:
        raise ValueError(f"Key '{name}' not found.")
        
    data = keys[name]
    _sync_epochs(data)
    
    max_weekly_uses = data.get("max_weekly_uses", DEFAULT_MAX_WEEKLY_USES)
    
    if data.get("weekly_usage_count", 0) >= max_weekly_uses:
        raise ValueError(f"Key '{name}' has reached its weekly limit of {max_weekly_uses} uses.")
        
    if data.get("is_exhausted"):
        raise ValueError(f"Key '{name}' is already exhausted for this 5-hour window.")
        
    data["is_exhausted"] = True
    data["weekly_usage_count"] = data.get("weekly_usage_count", 0) + 1
    
    save_keys(keys)
    return get_key_status(name, data)

# Maintain backwards compatibility alias
exhaust_key = mark_key_exhausted

def mark_key_weekly_exhausted(name: str):
    keys = load_keys()
    if name not in keys:
        raise ValueError(f"Key '{name}' not found.")
        
    data = keys[name]
    _sync_epochs(data)
    
    max_weekly_uses = data.get("max_weekly_uses", DEFAULT_MAX_WEEKLY_USES)
    data["weekly_usage_count"] = max_weekly_uses
    
    save_keys(keys)
    return get_key_status(name, data)

def mark_key_available(name: str):
    keys = load_keys()
    if name not in keys:
        raise ValueError(f"Key '{name}' not found.")
        
    data = keys[name]
    data["is_exhausted"] = False
    data["weekly_usage_count"] = 0
    now = _get_current_time()
    data["next_refresh_time"] = now.isoformat()
    
    save_keys(keys)
    return get_key_status(name, data)

def get_available_key():
    status_list = get_all_status()
    available_keys = [k for k in status_list if k["can_use"]]
    
    if not available_keys:
        return None
        
    # Sort available keys to follow the table order (Level 1: weekly_reset_seconds asc, Level 2: weekly_uses_left desc, Level 3: time_remaining_seconds asc)
    available_keys.sort(key=lambda k: (
        k.get("weekly_reset_seconds", 0),
        -k.get("weekly_uses_left", 0),
        k.get("time_remaining_seconds", 0)
    ))
    return available_keys[0]

