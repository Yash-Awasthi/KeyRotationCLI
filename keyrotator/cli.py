import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint
from rich.live import Live
from pathlib import Path
import time
import keyrotator.manager as manager

app = typer.Typer(help="Manage and rotate API keys effectively.")
console = Console()

def parse_custom_time_to_hours(val_str: str) -> float:
    """Parses format like '4.45' into 4 hours 45 mins -> 4.75 hours"""
    try:
        parts = val_str.split('.')
        h = float(parts[0])
        m = float(parts[1].ljust(2, '0')[:2]) if len(parts) > 1 else 0.0
        return h + (m / 60.0)
    except:
        return 0.0

def parse_custom_time_to_days(val_str: str) -> float:
    """Parses format like '2.04.30' (dd.hh.mm) or '2.04' into days"""
    try:
        parts = val_str.split('.')
        d = float(parts[0])
        h = float(parts[1]) if len(parts) > 1 else 0.0
        m = float(parts[2].ljust(2, '0')[:2]) if len(parts) > 2 else 0.0
        return d + (h / 24.0) + (m / (24.0 * 60.0))
    except:
        return 7.0

def prompt_for_key_sync(default_uses=7):
    is_exhausted = typer.confirm("Is the key currently exhausted?", default=False)
    
    time_str = typer.prompt("Time until 5hr refresh (Format hh.mm, e.g. 4.45 for 4h45m)", default="0.0")
    refresh_in_hours = parse_custom_time_to_hours(time_str)
        
    reset_str = typer.prompt("Time until weekly reset (Format dd.hh.mm or d.hh, e.g. 2.14 for 2d14h)", default="7.0")
    weekly_reset_in_days = parse_custom_time_to_days(reset_str)
    
    weekly_uses_left = typer.prompt("Weekly uses left", default=default_uses, type=int)
    
    return is_exhausted, refresh_in_hours, weekly_reset_in_days, weekly_uses_left

@app.command()
def add(name: str = typer.Argument(..., help="A memorable name for the key"), 
        key: str = typer.Argument(..., help="The API key string")):
    """Add a new API key and configure its current status."""
    rprint(f"[cyan]Adding key '{name}'. Let's configure it![/cyan]")
    
    is_exhausted, refresh_in_hours, weekly_reset_in_days, weekly_uses_left = prompt_for_key_sync()
    
    try:
        manager.add_key(name, key, is_exhausted, refresh_in_hours, weekly_reset_in_days, weekly_uses_left)
        rprint(f"[green]Successfully added key '{name}' and synced its timers![/green]")
    except ValueError as e:
        rprint(f"[red]Error: {e}[/red]")

@app.command()
def sync():
    """Update the current state of all keys to sync them with reality."""
    status_list = manager.get_all_status()
    if not status_list:
        rprint("[yellow]No keys found to sync.[/yellow]")
        return
        
    for k in status_list:
        name = k["name"]
        rprint(f"\n[cyan]Syncing key '{name}'...[/cyan]")
        is_exhausted, refresh_in_hours, weekly_reset_in_days, weekly_uses_left = prompt_for_key_sync(default_uses=k["weekly_uses_left"])
        
        manager.update_key(name, is_exhausted, refresh_in_hours, weekly_reset_in_days, weekly_uses_left)
    
    rprint("\n[green]All keys successfully synced![/green]")

@app.command()
def remove(name: str = typer.Argument(..., help="Name of the key to remove")):
    """Remove a managed API key."""
    try:
        manager.remove_key(name)
        rprint(f"[green]Successfully removed key '{name}'.[/green]")
    except ValueError as e:
        rprint(f"[red]Error: {e}[/red]")

@app.command()
def edit(name: str = typer.Argument(..., help="Name of the key to edit")):
    """Edit the timers and status of a specific API key."""
    status_list = manager.get_all_status()
    key_data = next((k for k in status_list if k["name"] == name), None)
    
    if not key_data:
        rprint(f"[red]Error: Key '{name}' not found.[/red]")
        return
        
    rprint(f"[cyan]Editing key '{name}'...[/cyan]")
    is_exhausted, refresh_in_hours, weekly_reset_in_days, weekly_uses_left = prompt_for_key_sync(default_uses=key_data["weekly_uses_left"])
    
    try:
        manager.update_key(name, is_exhausted, refresh_in_hours, weekly_reset_in_days, weekly_uses_left)
        rprint(f"[green]Successfully updated key '{name}'![/green]")
    except ValueError as e:
        rprint(f"[red]Error: {e}[/red]")

def wrap_key(key: str) -> str:
    """Splits a long API key into two rows for better display."""
    if not key or len(key) < 40:
        return key
    mid = len(key) // 2
    return f"{key[:mid]}\n{key[mid:]}"

def _sort_key(k):
    # Level 0: status group (AVAILABLE=0, EXHAUSTED=1, WEEKLY_EXHAUSTED=2)
    level0 = {"AVAILABLE": 0, "EXHAUSTED": 1, "WEEKLY_EXHAUSTED": 2}.get(k["status"], 3)

    # Level 1: weekly reset time remaining (asc / lowest first)
    level1 = k.get("weekly_reset_seconds", 0)

    # Level 2: weekly uses left (desc / highest first)
    level2 = -k.get("weekly_uses_left", 0)

    # Level 3: 5hr refresh time remaining (asc / lowest first)
    level3 = k.get("time_remaining_seconds", 0)

    return (level0, level1, level2, level3)

def _generate_status_table():
    status_list = manager.get_all_status()
    if not status_list:
        return None

    # Identify the key currently injected in Claude's settings.json (if any)
    current_name = None
    settings_path = manager.get_settings_path()
    if settings_path:
        current_name = manager.get_current_key_name(settings_path)

    status_list = sorted(status_list, key=_sort_key)

    title_str = "API Keys Status"
    if current_name:
        title_str += f" | Present Key: [bold cyan]{current_name}[/bold cyan]"
    else:
        title_str += " | Present Key: [red]None[/red]"

    table = Table(title=title_str)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("API Key", style="yellow", no_wrap=True)
    table.add_column("Stat", style="magenta", no_wrap=True)
    table.add_column("Time", justify="right", style="green", no_wrap=True)
    table.add_column("Uses", justify="center", style="blue", no_wrap=True)
    table.add_column("Reset", justify="right", style="yellow", no_wrap=True)

    status_map = {
        "AVAILABLE": "AVAIL",
        "EXHAUSTED": "EX",
        "WEEKLY_EXHAUSTED": "WK_EX"
    }

    for k in status_list:
        short_status = status_map.get(k["status"], k["status"])
        is_current = k["name"] == current_name

        if is_current:
            # Pure white row overrides per-column colors; no inline status color.
            status_text = short_status
            row_style = "bright_white"
        else:
            status_color = "green" if k["status"] == "AVAILABLE" else "red"
            status_text = f"[{status_color}]{short_status}[/{status_color}]"
            row_style = None

        table.add_row(
            k["name"],
            k["value"],
            status_text,
            k["time_remaining_str"],
            str(k["weekly_uses_left"]),
            k.get("weekly_reset_str", "Unknown"),
            style=row_style
        )
    return table

@app.command()
def status(watch: bool = typer.Option(False, "--watch", "-w", help="Dynamically watch the table update in real-time")):
    """Show the current status of all managed API keys."""
    if not watch:
        table = _generate_status_table()
        if table:
            console.print(table)
        else:
            rprint("[yellow]No keys found. Add one with `keyrotator add <name> <key>`[/yellow]")
    else:
        # Initial check
        if not _generate_status_table():
            rprint("[yellow]No keys found. Add one with `keyrotator add <name> <key>`[/yellow]")
            return
            
        try:
            with Live(_generate_status_table(), refresh_per_second=1) as live:
                while True:
                    time.sleep(1)
                    live.update(_generate_status_table())
        except KeyboardInterrupt:
            pass

@app.command()
def get():
    """Get the next available API key (least time until its next refresh)."""
    best_key = manager.get_available_key()
    if not best_key:
        rprint("[red]No keys are currently available. Check `keyrotator status` to see when the next one unlocks.[/red]")
        return
        
    rprint(f"[green]Best available key:[/green] [bold cyan]{best_key['name']}[/bold cyan]")
    rprint(f"Value: [yellow]{best_key['value']}[/yellow]")
    rprint(f"Weekly uses remaining: [blue]{best_key['weekly_uses_left']}[/blue]")

@app.command()
def markex(name: str = typer.Argument(..., help="Name of the key to mark as exhausted")):
    """Mark a key as exhausted for the current 5-hour window (deducts 1 weekly use)."""
    try:
        new_status = manager.mark_key_exhausted(name)
        rprint(f"[green]Key '{name}' has been marked as exhausted (EX).[/green]")
        rprint(f"It will be available again soon. Check `keyrotator status`.")
        rprint(f"Weekly uses remaining: [blue]{new_status['weekly_uses_left']}[/blue]")
    except ValueError as e:
        rprint(f"[red]Error: {e}[/red]")

@app.command()
def markwk(name: str = typer.Argument(..., help="Name of the key to mark as weekly exhausted")):
    """Mark a key as weekly exhausted (WK_EX, weekly uses left set to 0)."""
    try:
        new_status = manager.mark_key_weekly_exhausted(name)
        rprint(f"[green]Key '{name}' has been marked as weekly exhausted (WK_EX).[/green]")
        rprint(f"Weekly uses remaining: [blue]{new_status['weekly_uses_left']}[/blue]")
    except ValueError as e:
        rprint(f"[red]Error: {e}[/red]")

@app.command()
def markav(name: str = typer.Argument(..., help="Name of the key to mark as available")):
    """Mark a key as available (AVAIL, clears 5-hour cool-down flag only)."""
    try:
        new_status = manager.mark_key_available(name)
        rprint(f"[green]Key '{name}' has been marked as available (AVAIL).[/green]")
        rprint(f"Weekly uses remaining: [blue]{new_status['weekly_uses_left']}[/blue]")
    except ValueError as e:
        rprint(f"[red]Error: {e}[/red]")


@app.command()
def setpath(path: str = typer.Argument(None, help="Path to Claude's settings.json")):
    """Save the path to Claude's settings.json for use with the inject command."""
    if not path:
        default = str(Path.home() / ".claude" / "settings.json")
        path = typer.prompt("Path to Claude's settings.json", default=default)

    p = Path(path)
    if not p.exists():
        rprint(f"[red]Warning: No file found at '{path}'. Path saved anyway, but injection will fail until the file exists.[/red]")
    else:
        rprint(f"[green]✓ File found.[/green]")

    manager.set_settings_path(path)
    rprint(f"[green]Settings path saved:[/green] [cyan]{path}[/cyan]")
    rprint("Run [bold]keyrotator rotate[/bold] to inject the best available key.")

@app.command()
def rotate():
    """Inject the best available API key into Claude's settings.json."""
    stored_path = manager.get_settings_path()

    if stored_path:
        confirmed = typer.confirm(f"Inject into: {stored_path}?", default=True)
        if not confirmed:
            stored_path = typer.prompt("Enter the path to Claude's settings.json")
    else:
        rprint("[yellow]No path saved yet.[/yellow]")
        stored_path = typer.prompt(
            "Path to Claude's settings.json",
            default=str(Path.home() / ".claude" / "settings.json")
        )
        save_it = typer.confirm(f"Save this path for future use?", default=True)
        if save_it:
            manager.set_settings_path(stored_path)
            rprint(f"[green]Path saved.[/green]")

    try:
        old_name, new_name = manager.inject_key_into_settings(stored_path)
        if old_name:
            rprint(f"[yellow]Marked old key '{old_name}' as exhausted.[/yellow]")
        rprint(f"\n[green]✓ Injected key '[bold]{new_name}[/bold]' into:[/green]")
        rprint(f"  [cyan]apiKeyHelper[/cyan]")
        rprint(f"  [cyan]env.ANTHROPIC_API_KEY[/cyan]")
        rprint(f"\n[dim]{stored_path}[/dim]")
    except FileNotFoundError as e:
        rprint(f"[red]Error: {e}[/red]")
    except ValueError as e:
        rprint(f"[red]Error: {e}[/red]")
        rprint("[yellow]Run `keyrotator status` to see key availability.[/yellow]")

@app.command()
def inject(name: str = typer.Argument(..., help="Name of the key to inject (as set by you, not the key value)")):
    """Manually inject a specific key by name into Claude's settings.json.

    Unlike rotate, this does NOT auto-select or mark the previous key as exhausted.
    Use this when you want to force a specific key into Claude's config.
    """
    # Verify the key name exists
    status_list = manager.get_all_status()
    key_data = next((k for k in status_list if k["name"] == name), None)

    if not key_data:
        rprint(f"[red]Error: No key named '{name}' found. Run `kr status` to see available names.[/red]")
        raise typer.Exit(code=1)

    # Get the settings path
    stored_path = manager.get_settings_path()
    if stored_path:
        confirmed = typer.confirm(f"Inject '{name}' into: {stored_path}?", default=True)
        if not confirmed:
            stored_path = typer.prompt("Enter the path to Claude's settings.json")
    else:
        rprint("[yellow]No path saved yet.[/yellow]")
        stored_path = typer.prompt(
            "Path to Claude's settings.json",
            default=str(Path.home() / ".claude" / "settings.json")
        )
        save_it = typer.confirm("Save this path for future use?", default=True)
        if save_it:
            manager.set_settings_path(stored_path)
            rprint("[green]Path saved.[/green]")

    # Inject the specified key directly — no auto-selection, no exhausting old key
    try:
        manager.inject_specific_key_into_settings(stored_path, name)
        stat_color = "green" if key_data["status"] == "AVAILABLE" else "yellow"
        rprint(f"\n[green]✓ Injected key '[bold]{name}[/bold]' into:[/green]")
        rprint(f"  [cyan]apiKeyHelper[/cyan]")
        rprint(f"  [cyan]env.ANTHROPIC_API_KEY[/cyan]")
        rprint(f"  Status: [{stat_color}]{key_data['status']}[/{stat_color}] | Uses left: [blue]{key_data['weekly_uses_left']}[/blue]")
        rprint(f"\n[dim]{stored_path}[/dim]")
    except FileNotFoundError as e:
        rprint(f"[red]Error: {e}[/red]")
    except ValueError as e:
        rprint(f"[red]Error: {e}[/red]")

if __name__ == "__main__":
    app()
