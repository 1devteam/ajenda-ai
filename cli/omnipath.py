#!/usr/bin/env python3
"""
Omnipath CLI - Command-line interface for Omnipath v5.0
Beautiful, intuitive terminal interface for managing agents, missions, and economy
"""
import typer
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box
import httpx
import json
from pathlib import Path
import os

# Initialize
app = typer.Typer(
    name="omnipath",
    help="🚀 Omnipath v5.0 - Multi-Agent AI Orchestration Platform",
    add_completion=False
)
console = Console()

# Configuration
CONFIG_DIR = Path.home() / ".omnipath"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_API_URL = "http://localhost:8000"


# ============================================================================
# Configuration Management
# ============================================================================

def load_config() -> dict:
    """Load CLI configuration"""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {"api_url": DEFAULT_API_URL, "token": None}


def save_config(config: dict):
    """Save CLI configuration"""
    CONFIG_DIR.mkdir(exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_api_url() -> str:
    """Get configured API URL"""
    return load_config().get("api_url", DEFAULT_API_URL)


def get_client() -> httpx.Client:
    """Get HTTP client with configuration"""
    config = load_config()
    headers = {}
    if config.get("token"):
        headers["Authorization"] = f"Bearer {config['token']}"
    return httpx.Client(base_url=config.get("api_url", DEFAULT_API_URL), headers=headers, timeout=30.0)


# ============================================================================
# Main Commands
# ============================================================================

@app.command()
def status():
    """Check Omnipath system status"""
    try:
        with get_client() as client:
            response = client.get("/health")
            response.raise_for_status()
            data = response.json()
            
            console.print(Panel(
                f"[green]✅ Omnipath is running[/green]\n\n"
                f"[cyan]Service:[/cyan] {data.get('service', 'Unknown')}\n"
                f"[cyan]Version:[/cyan] {data.get('version', 'Unknown')}\n"
                f"[cyan]Environment:[/cyan] {data.get('environment', 'Unknown')}\n"
                f"[cyan]API URL:[/cyan] {get_api_url()}",
                title="🚀 System Status",
                border_style="green"
            ))
    except httpx.ConnectError:
        console.print(f"[red]❌ Omnipath is not reachable at {get_api_url()}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command()
def config(
    api_url: Optional[str] = typer.Option(None, "--api-url", help="Set API URL"),
    show: bool = typer.Option(False, "--show", help="Show current configuration")
):
    """Configure CLI settings"""
    if show:
        cfg = load_config()
        console.print(Panel(
            f"[cyan]API URL:[/cyan] {cfg.get('api_url', DEFAULT_API_URL)}\n"
            f"[cyan]Token:[/cyan] {'Set' if cfg.get('token') else 'Not set'}",
            title="⚙️  Configuration",
            border_style="cyan"
        ))
        return
    
    if api_url:
        cfg = load_config()
        cfg["api_url"] = api_url
        save_config(cfg)
        console.print(f"[green]✅ API URL set to: {api_url}[/green]")


# ============================================================================
# Agent Commands
# ============================================================================

agent_app = typer.Typer(help="👤 Manage agents")
app.add_typer(agent_app, name="agent")


@agent_app.command("list")
def agent_list(
    limit: int = typer.Option(20, "--limit", "-l", help="Number of agents to show"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status")
):
    """List all agents"""
    try:
        with get_client() as client:
            params = {"limit": limit}
            if status:
                params["status"] = status
            
            response = client.get("/api/v1/agents", params=params)
            response.raise_for_status()
            data = response.json()
            
            if not data.get("agents"):
                console.print("[yellow]No agents found[/yellow]")
                return
            
            table = Table(title="👤 Agents", box=box.ROUNDED)
            table.add_column("ID", style="cyan")
            table.add_column("Name", style="green")
            table.add_column("Model", style="magenta")
            table.add_column("Status", style="yellow")
            table.add_column("Balance", style="blue", justify="right")
            
            for agent in data["agents"]:
                table.add_row(
                    agent.get("id", "")[:8],
                    agent.get("name", ""),
                    agent.get("model", ""),
                    agent.get("status", ""),
                    f"{agent.get('credit_balance', 0):.2f}"
                )
            
            console.print(table)
            console.print(f"\n[dim]Total: {data.get('total', 0)} agents[/dim]")
            
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


@agent_app.command("show")
def agent_show(agent_id: str):
    """Show detailed agent information"""
    try:
        with get_client() as client:
            response = client.get(f"/api/v1/agents/{agent_id}")
            response.raise_for_status()
            agent = response.json()
            
            console.print(Panel(
                f"[cyan]ID:[/cyan] {agent.get('id', '')}\n"
                f"[cyan]Name:[/cyan] {agent.get('name', '')}\n"
                f"[cyan]Model:[/cyan] {agent.get('model', '')}\n"
                f"[cyan]Status:[/cyan] {agent.get('status', '')}\n"
                f"[cyan]Balance:[/cyan] {agent.get('credit_balance', 0):.2f} credits\n"
                f"[cyan]Created:[/cyan] {agent.get('created_at', '')}",
                title=f"👤 Agent: {agent.get('name', '')}",
                border_style="cyan"
            ))
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            console.print(f"[red]❌ Agent not found: {agent_id}[/red]")
        else:
            console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


@agent_app.command("performance")
def agent_performance(agent_id: str):
    """Show agent performance metrics"""
    try:
        with get_client() as client:
            response = client.get(f"/api/v1/meta-learning/performance/{agent_id}")
            response.raise_for_status()
            perf = response.json()
            
            console.print(Panel(
                f"[cyan]Total Missions:[/cyan] {perf.get('total_missions', 0)}\n"
                f"[green]✅ Successful:[/green] {perf.get('successful_missions', 0)}\n"
                f"[red]❌ Failed:[/red] {perf.get('failed_missions', 0)}\n"
                f"[cyan]Success Rate:[/cyan] {perf.get('success_rate', 0)*100:.1f}%\n\n"
                f"[cyan]Avg Cost:[/cyan] {perf.get('avg_cost_per_mission', 0):.2f} credits\n"
                f"[cyan]Avg Duration:[/cyan] {perf.get('avg_duration_per_mission', 0):.2f}s\n"
                f"[cyan]Avg Quality:[/cyan] {perf.get('average_quality', 0)*100:.1f}%\n\n"
                f"[cyan]Trend:[/cyan] {perf.get('recent_trend', 'stable')}",
                title=f"📊 Performance: {agent_id[:8]}",
                border_style="cyan"
            ))
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            console.print(f"[red]❌ No performance data for agent: {agent_id}[/red]")
        else:
            console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


# ============================================================================
# Mission Commands
# ============================================================================

mission_app = typer.Typer(help="🎯 Manage missions")
app.add_typer(mission_app, name="mission")


@mission_app.command("list")
def mission_list(
    limit: int = typer.Option(20, "--limit", "-l", help="Number of missions to show"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status")
):
    """List missions"""
    try:
        with get_client() as client:
            params = {"limit": limit}
            if status:
                params["status"] = status
            
            response = client.get("/api/v1/missions", params=params)
            response.raise_for_status()
            data = response.json()
            
            if not data.get("missions"):
                console.print("[yellow]No missions found[/yellow]")
                return
            
            table = Table(title="🎯 Missions", box=box.ROUNDED)
            table.add_column("ID", style="cyan")
            table.add_column("Agent", style="green")
            table.add_column("Status", style="yellow")
            table.add_column("Complexity", style="magenta")
            table.add_column("Created", style="dim")
            
            for mission in data["missions"]:
                table.add_row(
                    mission.get("id", "")[:8],
                    mission.get("agent_id", "")[:8],
                    mission.get("status", ""),
                    mission.get("complexity", ""),
                    mission.get("created_at", "")[:19]
                )
            
            console.print(table)
            console.print(f"\n[dim]Total: {data.get('total', 0)} missions[/dim]")
            
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


# ============================================================================
# Economy Commands
# ============================================================================

economy_app = typer.Typer(help="💰 Manage economy")
app.add_typer(economy_app, name="economy")


@economy_app.command("balance")
def economy_balance(agent_id: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent ID")):
    """Check credit balance"""
    try:
        with get_client() as client:
            if agent_id:
                response = client.get(f"/api/v1/economy/balance/{agent_id}")
                response.raise_for_status()
                data = response.json()
                
                console.print(Panel(
                    f"[cyan]Agent:[/cyan] {agent_id[:8]}\n"
                    f"[green]Balance:[/green] {data.get('balance', 0):.2f} credits",
                    title="💰 Credit Balance",
                    border_style="green"
                ))
            else:
                console.print("[yellow]Please specify an agent ID with --agent[/yellow]")
                
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


@economy_app.command("transactions")
def economy_transactions(
    agent_id: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent ID"),
    limit: int = typer.Option(10, "--limit", "-l", help="Number of transactions to show")
):
    """List recent transactions"""
    try:
        with get_client() as client:
            params = {"limit": limit}
            if agent_id:
                params["agent_id"] = agent_id
            
            response = client.get("/api/v1/economy/transactions", params=params)
            response.raise_for_status()
            data = response.json()
            
            if not data.get("transactions"):
                console.print("[yellow]No transactions found[/yellow]")
                return
            
            table = Table(title="💰 Transactions", box=box.ROUNDED)
            table.add_column("ID", style="cyan")
            table.add_column("Agent", style="green")
            table.add_column("Type", style="yellow")
            table.add_column("Amount", style="blue", justify="right")
            table.add_column("Date", style="dim")
            
            for tx in data["transactions"]:
                amount_color = "green" if tx.get("type") == "credit" else "red"
                table.add_row(
                    tx.get("id", "")[:8],
                    tx.get("agent_id", "")[:8],
                    tx.get("type", ""),
                    f"[{amount_color}]{tx.get('amount', 0):.2f}[/{amount_color}]",
                    tx.get("created_at", "")[:19]
                )
            
            console.print(table)
            
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


# ============================================================================
# Learning Commands
# ============================================================================

learning_app = typer.Typer(help="🧠 Meta-learning insights")
app.add_typer(learning_app, name="learning")


@learning_app.command("leaderboard")
def learning_leaderboard(
    metric: str = typer.Option("success_rate", "--metric", "-m", help="Metric to rank by"),
    limit: int = typer.Option(10, "--limit", "-l", help="Number of agents to show")
):
    """Show agent leaderboard"""
    try:
        with get_client() as client:
            response = client.get(f"/api/v1/meta-learning/leaderboard", params={"metric": metric, "limit": limit})
            response.raise_for_status()
            data = response.json()
            
            if not data.get("leaderboard"):
                console.print("[yellow]No data available[/yellow]")
                return
            
            table = Table(title=f"🏆 Leaderboard: {metric}", box=box.ROUNDED)
            table.add_column("Rank", style="yellow", justify="center")
            table.add_column("Agent", style="cyan")
            table.add_column("Value", style="green", justify="right")
            table.add_column("Missions", style="dim", justify="right")
            
            for entry in data["leaderboard"]:
                rank_emoji = "🥇" if entry["rank"] == 1 else "🥈" if entry["rank"] == 2 else "🥉" if entry["rank"] == 3 else ""
                table.add_row(
                    f"{rank_emoji} {entry['rank']}",
                    entry["agent_id"][:8],
                    f"{entry['value']:.3f}",
                    str(entry["total_missions"])
                )
            
            console.print(table)
            
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


@learning_app.command("insights")
def learning_insights(agent_id: str):
    """Get learning insights for an agent"""
    try:
        with get_client() as client:
            response = client.get(f"/api/v1/meta-learning/insights/{agent_id}")
            response.raise_for_status()
            insights = response.json()
            
            console.print(Panel(
                f"[cyan]Agent:[/cyan] {agent_id[:8]}\n\n"
                f"[green]Strengths:[/green]\n" + "\n".join(f"  • {s}" for s in insights.get("strengths", [])) + "\n\n"
                f"[yellow]Areas for Improvement:[/yellow]\n" + "\n".join(f"  • {a}" for a in insights.get("areas_for_improvement", [])) + "\n\n"
                f"[cyan]Recommendations:[/cyan]\n" + "\n".join(f"  • {r}" for r in insights.get("recommendations", [])),
                title="🧠 Learning Insights",
                border_style="cyan"
            ))
            
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


@learning_app.command("optimize")
def learning_optimize(agent_id: str):
    """Auto-optimize agent configuration"""
    try:
        with get_client() as client:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Analyzing performance and optimizing...", total=None)
                
                response = client.post(f"/api/v1/meta-learning/optimize/{agent_id}")
                response.raise_for_status()
                config = response.json()
                
                progress.update(task, completed=True)
            
            console.print(Panel(
                f"[green]✅ Optimization complete![/green]\n\n"
                f"[cyan]Preferred Model:[/cyan] {config['configuration'].get('preferred_model', 'N/A')}\n"
                f"[cyan]Optimal Complexity:[/cyan] {config['configuration'].get('optimal_complexity', 'N/A')}\n"
                f"[cyan]Max Cost:[/cyan] {config['configuration'].get('max_cost_per_mission', 'N/A')}\n"
                f"[cyan]Quality Threshold:[/cyan] {config['configuration'].get('quality_threshold', 0)*100:.1f}%",
                title=f"⚙️  Optimized Configuration: {agent_id[:8]}",
                border_style="green"
            ))
            
    except Exception as e:
        console.print(f"[red]❌ Error: {str(e)}[/red]")
        raise typer.Exit(1)


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    app()
