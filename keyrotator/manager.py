import json
import os
import datetime
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

def set_settings_path(path: str):
    config = _load_config()
    config["claude_settings_path"] = path
    _save_config(config)

def get_settings_path() -> str | None:
    return _load_config().get("claude_settings_path")

def inject_key_into_settings(settings_path: str) -> str:
    """Finds the best available key and injects it into Claude's settings.json.
    Returns the key name that was injected.
    """
    p = Path(settings_path)
    if not p.exists():
        raise FileNotFoundError(f"settings.json not found at: {settings_path}")

    best = get_available_key()
    if not best:
        raise ValueError("No available keys to inject. All keys are exhausted.")

    with open(p, 'r') as f:
        settings = json.load(f)

    key_value = best["value"]

    # Inject into apiKeyHelper as an echo shell command
    settings["apiKeyHelper"] = f"echo '{key_value}'"

    # Inject into env.ANTHROPIC_API_KEY
    if "env" not in settings:
        settings["env"] = {}
    settings["env"]["ANTHROPIC_API_KEY"] = key_value

    with open(p, 'w') as f:
        json.dump(settings, f, indent=2)

    return best["name"]

def _ensure_file():
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not KEYS_FILE.exists():
        with open(KEYS_FILE, 'w') as f:
            json.dump({}, f)

def load_keys():
    _ensure_file()
    with open(KEYS_FILE, 'r') as f:
        return json.load(f)

def save_keys(keys):
    _ensure_file()
    with open(KEYS_FILE, 'w') as f:
        json.dump(keys, f, indent=4)

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
        
    # Calculate weekly reset string
    next_weekly_str = key_data.get("next_weekly_reset_time")
    if next_weekly_str:
        next_weekly = _parse_time(next_weekly_str)
        time_until_reset = next_weekly - now
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
            "weekly_reset_str": weekly_reset_str
        }
        
    if key_data.get("is_exhausted"):
        return {
            "status": "EXHAUSTED",
            "time_remaining_str": refresh_str,
            "time_remaining_seconds": time_remaining_seconds,
            "weekly_uses_left": weekly_uses_left,
            "can_use": False,
            "weekly_reset_str": weekly_reset_str
        }

    return {
        "status": "AVAILABLE",
        "time_remaining_str": refresh_str,
        "time_remaining_seconds": time_remaining_seconds,
        "weekly_uses_left": weekly_uses_left,
        "can_use": True,
        "weekly_reset_str": weekly_reset_str
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

def exhaust_key(name: str):
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

def get_available_key():
    status_list = get_all_status()
    available_keys = [k for k in status_list if k["can_use"]]
    
    if not available_keys:
        return None
        
    # Prefer the key with the least time until refresh (so it unlocks again sooner if exhausted)
    available_keys.sort(key=lambda x: x.get("time_remaining_seconds", 0))
    return available_keys[0]

