# KeyRotator 🔑

A personal CLI tool to manage and rotate multiple Claude API keys — tracking their 5-hour refresh windows and weekly usage limits so you always know which key to use next. It can also automatically rotate the best available key directly into Claude's `settings.json` file.

## Why?

Claude API keys (on free/limited plans) refresh every 5 hours and have a weekly cap of 7 uses. When you have multiple keys, it's a pain to mentally track which one is available, which is cooling down, and how many uses you have left this week.

KeyRotator solves that with a clean terminal dashboard and automated Claude key rotation.

## Features

- 📋 **Live dashboard** — real-time countdown timers per key (`status --watch`)
- 🔑 **Shows full API key** — copy directly from the table (displayed in a single, long row for easy copying)
- ⏱️ **Independent timers** — 5-hour epoch and 7-day weekly cycle tracked per key
- 📊 **Smart sorting** — available keys first, sorted by time until next epoch (least time remaining first)
- ✋ **Manual usage tracking** — you mark a key as exhausted, nothing is assumed
- 🔄 **Auto epoch advance** — when the 5hr window passes, key flips back to `AVAILABLE` automatically
- 🛡️ **Weekly lock** — when weekly uses hit 0, key stays locked until weekly reset
- 🔄 **Automated Claude Integration** — configure the path to Claude's `settings.json` and rotate the best available key with a single command

## Install

Requires Python 3.10+ and [pipx](https://pypa.github.io/pipx/).

```bash
git clone https://github.com/Yash-Awasthi/KeyRotationCLI.git
cd KeyRotationCLI
pipx install .
```

## Commands

| Command | Description |
|---|---|
| `keyrotator add <name> <key>` | Add a new API key with interactive timer setup |
| `keyrotator status` | Show current status of all keys |
| `keyrotator status --watch` | Live updating dashboard (Ctrl+C to exit) |
| `keyrotator mark <name>` | Mark a key as exhausted (deducts 1 weekly use) |
| `keyrotator edit <name>` | Fix/update timers for a specific key |
| `keyrotator sync` | Bulk re-sync all keys (useful on first launch) |
| `keyrotator remove <name>` | Remove a key |
| `keyrotator get` | Print the best available key (least time to refresh) |
| `keyrotator setpath <path>` | Set/save the path to Claude's `settings.json` |
| `keyrotator rotate` | Rotate the best available key into Claude's `settings.json` |

## Time Format

When entering times during `add`, `edit`, or `sync`:

- **Hours** → `hh.mm` — e.g. `4.45` = 4 hours 45 minutes
- **Days** → `d.hh` or `d.hh.mm` — e.g. `2.14` = 2 days 14 hours

## How it works

1. Each key has two independent clocks: a **5-hour epoch** and a **7-day weekly window**
2. When you use a key in Claude Code, run `keyrotator mark <keyname>` (or its alias `keyrotator exhaust <keyname>`) — this decrements weekly uses by 1 and marks it exhausted for the current 5-hour window.
3. When the 5-hour epoch ends, the key automatically flips back to `AVAILABLE`.
4. When 7 days are up, weekly uses reset back to 7.
5. Keys with 0 weekly uses left stay locked (`WEEKLY_EXHAUSTED`) until their weekly reset.
6. With `keyrotator rotate`, the CLI finds the best available key (the `AVAILABLE` key with the least time remaining in its current epoch) and writes it into Claude's `settings.json` under `apiKeyHelper` and `env.ANTHROPIC_API_KEY`.

## Data Storage

Keys are stored locally at `~/.keyrotator/keys.json` and configuration at `~/.keyrotator/config.json`. **Do not commit these files.**

## ⚠️ Security Note

This tool stores your raw API keys in a local JSON file. Do not push `~/.keyrotator/keys.json` to any repository.

## 🤝 Open to Contributions

This project is open to contributions! If you have suggestions, bug fixes, or feature requests, feel free to open an issue or submit a pull request on GitHub. Let's make Claude key rotation seamless for everyone!
