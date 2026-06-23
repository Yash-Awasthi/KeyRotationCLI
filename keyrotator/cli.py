import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint
from rich.live import Live
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
    # Group: AVAILABLE = 0, everything else = 1
    group = 0 if k["status"] == "AVAILABLE" else 1
    # Within group, sort ascending by seconds remaining
    return (group, k.get("time_remaining_seconds", 0))

def _generate_status_table():
    status_list = manager.get_all_status()
    if not status_list:
        return None

    status_list = sorted(status_list, key=_sort_key)

    table = Table(title="API Keys Status")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("API Key", style="yellow")
    table.add_column("Status", style="magenta")
    table.add_column("Time Remaining", justify="right", style="green")
    table.add_column("Weekly Uses Left", justify="center", style="blue")
    table.add_column("Weekly Reset In", justify="right", style="yellow")

    for k in status_list:
        status_color = "green" if k["status"] == "AVAILABLE" else "red"
        status_text = f"[{status_color}]{k['status']}[/{status_color}]"
        table.add_row(
            k["name"],
            k["value"],
            status_text,
            k["time_remaining_str"],
            str(k["weekly_uses_left"]),
            k.get("weekly_reset_str", "Unknown")
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
    """Get the next available API key with the most weekly uses remaining."""
    best_key = manager.get_available_key()
    if not best_key:
        rprint("[red]No keys are currently available. Check `keyrotator status` to see when the next one unlocks.[/red]")
        return
        
    rprint(f"[green]Best available key:[/green] [bold cyan]{best_key['name']}[/bold cyan]")
    rprint(f"Value: [yellow]{best_key['value']}[/yellow]")
    rprint(f"Weekly uses remaining: [blue]{best_key['weekly_uses_left']}[/blue]")

def _exhaust_key(name: str):
    try:
        new_status = manager.exhaust_key(name)
        rprint(f"[green]Key '{name}' has been marked as exhausted.[/green]")
        rprint(f"It will be available again soon. Check `keyrotator status`.")
        rprint(f"Weekly uses remaining: [blue]{new_status['weekly_uses_left']}[/blue]")
    except ValueError as e:
        rprint(f"[red]Error: {e}[/red]")

@app.command()
def exhaust(name: str = typer.Argument(..., help="Name of the key to exhaust")):
    """Mark a key as exhausted for the current 5-hour window."""
    _exhaust_key(name)

@app.command()
def mark(name: str = typer.Argument(..., help="Name of the key to exhaust")):
    """Alias for exhaust. Mark a key as exhausted for the current 5-hour window."""
    _exhaust_key(name)

if __name__ == "__main__":
    app()

