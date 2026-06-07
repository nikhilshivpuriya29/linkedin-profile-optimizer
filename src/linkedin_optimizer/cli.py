"""CLI entry point for the LinkedIn Profile Optimizer.

Provides command-line interface with subcommands for managing the
optimization pipeline: run, schedule, pause, resume, status, review,
history, and config.

Implements Requirements 6.1, 6.2, 6.6, 5.1.
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from linkedin_optimizer.config import PipelineConfig, load_config
from linkedin_optimizer.models import PipelineStatus, RunMetadata, ScheduleInterval
from linkedin_optimizer.orchestrator import PipelineOrchestrator
from linkedin_optimizer.scheduler import PipelineScheduler
from linkedin_optimizer.approval.cli_interface import CLIApprovalInterface

logger = logging.getLogger(__name__)

# Default config path
DEFAULT_CONFIG_PATH = Path("data/config.json")

console = Console()


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse argument parser with all subcommands.

    Returns:
        Configured ArgumentParser with subcommands.
    """
    parser = argparse.ArgumentParser(
        prog="linkedin-optimizer",
        description="LinkedIn Profile Optimizer — AI-powered profile analysis and content generation.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Path to configuration file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging output.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run — trigger on-demand pipeline execution
    subparsers.add_parser(
        "run",
        help="Trigger on-demand pipeline execution.",
    )

    # schedule — configure scheduled interval
    schedule_parser = subparsers.add_parser(
        "schedule",
        help="Configure scheduled execution interval.",
    )
    schedule_parser.add_argument(
        "interval",
        choices=["daily", "weekly", "monthly"],
        help="Schedule interval: daily, weekly, or monthly.",
    )

    # pause — pause scheduled runs
    subparsers.add_parser(
        "pause",
        help="Pause scheduled pipeline runs.",
    )

    # resume — resume scheduled runs
    subparsers.add_parser(
        "resume",
        help="Resume paused scheduled pipeline runs.",
    )

    # status — show current pipeline status
    subparsers.add_parser(
        "status",
        help="Show current pipeline status and last run summary.",
    )

    # review — launch CLI approval interface
    subparsers.add_parser(
        "review",
        help="Launch interactive approval review for pending items.",
    )

    # history — show recent run history
    history_parser = subparsers.add_parser(
        "history",
        help="Show recent run history and engagement reports.",
    )
    history_parser.add_argument(
        "--limit", "-n",
        type=int,
        default=10,
        help="Number of recent runs to display (default: 10).",
    )

    # config — display or update configuration
    config_parser = subparsers.add_parser(
        "config",
        help="Display or update pipeline configuration.",
    )
    config_parser.add_argument(
        "--set",
        type=str,
        dest="set_key",
        metavar="KEY=VALUE",
        help="Set a configuration value (e.g., --set schedule_interval=daily).",
    )

    return parser


def _setup_logging(verbose: bool) -> None:
    """Configure logging based on verbosity level.

    Args:
        verbose: If True, set DEBUG level; otherwise INFO.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _display_run_metadata(metadata: RunMetadata) -> None:
    """Display run metadata using rich formatting.

    Args:
        metadata: The RunMetadata to display.
    """
    status_colors = {
        PipelineStatus.COMPLETED: "green",
        PipelineStatus.FAILED: "red",
        PipelineStatus.RUNNING: "yellow",
        PipelineStatus.IDLE: "dim",
        PipelineStatus.PAUSED: "blue",
    }
    color = status_colors.get(metadata.status, "white")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("Run ID", metadata.run_id)
    table.add_row("Status", f"[{color}]{metadata.status.value}[/{color}]")
    table.add_row("Started", metadata.start_time.strftime("%Y-%m-%d %H:%M:%S"))

    if metadata.end_time:
        table.add_row("Ended", metadata.end_time.strftime("%Y-%m-%d %H:%M:%S"))
        duration = (metadata.end_time - metadata.start_time).total_seconds()
        table.add_row("Duration", f"{duration:.1f}s")

    if metadata.summary:
        table.add_row("Summary", metadata.summary)
    if metadata.error:
        table.add_row("Error", f"[red]{metadata.error}[/red]")

    console.print(Panel(table, title="[bold]Pipeline Run Result[/bold]", border_style=color))


def _load_config_safe(config_path: str) -> Optional[PipelineConfig]:
    """Load configuration with error handling.

    Args:
        config_path: Path to the configuration file.

    Returns:
        PipelineConfig if loaded successfully, None otherwise.
    """
    try:
        config = load_config(config_path)
        return config
    except FileNotFoundError:
        console.print(
            f"[red]Configuration file not found: {config_path}[/red]\n"
            f"Create one at {DEFAULT_CONFIG_PATH} or specify with --config."
        )
        return None
    except (ValueError, json.JSONDecodeError) as e:
        console.print(f"[red]Invalid configuration: {e}[/red]")
        return None


# --- Subcommand Handlers ---


async def _cmd_run(config: PipelineConfig) -> None:
    """Handle the 'run' subcommand — trigger on-demand pipeline execution.

    Args:
        config: The loaded pipeline configuration.
    """
    console.print("[bold]Triggering on-demand pipeline execution...[/bold]\n")

    orchestrator = PipelineOrchestrator(config)
    metadata = await orchestrator.trigger_on_demand()

    _display_run_metadata(metadata)


async def _cmd_schedule(config: PipelineConfig, interval_str: str) -> None:
    """Handle the 'schedule' subcommand — configure scheduled interval.

    Args:
        config: The loaded pipeline configuration.
        interval_str: The schedule interval string (daily/weekly/monthly).
    """
    interval = ScheduleInterval(interval_str)
    orchestrator = PipelineOrchestrator(config)
    scheduler = PipelineScheduler(orchestrator)

    scheduler.schedule(interval)
    scheduler.start()

    console.print(
        f"[green]✓ Pipeline scheduled: [bold]{interval.value}[/bold][/green]\n"
        f"  Next runs will execute at the configured hour.\n"
        f"  Use [bold]pause[/bold] to temporarily stop, [bold]resume[/bold] to restart."
    )

    # Keep the scheduler running until user interrupts
    console.print("\n[dim]Scheduler running. Press Ctrl+C to stop.[/dim]")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        scheduler.stop()
        console.print("\n[yellow]Scheduler stopped.[/yellow]")


async def _cmd_pause(config: PipelineConfig) -> None:
    """Handle the 'pause' subcommand — pause scheduled runs.

    Args:
        config: The loaded pipeline configuration.
    """
    orchestrator = PipelineOrchestrator(config)
    scheduler = PipelineScheduler(orchestrator)

    scheduler.pause()
    console.print("[yellow]⏸ Scheduled pipeline runs paused.[/yellow]")


async def _cmd_resume(config: PipelineConfig) -> None:
    """Handle the 'resume' subcommand — resume paused scheduled runs.

    Args:
        config: The loaded pipeline configuration.
    """
    orchestrator = PipelineOrchestrator(config)
    scheduler = PipelineScheduler(orchestrator)

    scheduler.resume()
    console.print("[green]▶ Scheduled pipeline runs resumed.[/green]")


async def _cmd_status(config: PipelineConfig) -> None:
    """Handle the 'status' subcommand — show current pipeline status.

    Args:
        config: The loaded pipeline configuration.
    """
    from linkedin_optimizer.persistence.data_store import DataStore

    orchestrator = PipelineOrchestrator(config)
    status = orchestrator.get_status()

    status_colors = {
        PipelineStatus.COMPLETED: "green",
        PipelineStatus.FAILED: "red",
        PipelineStatus.RUNNING: "yellow",
        PipelineStatus.IDLE: "dim",
        PipelineStatus.PAUSED: "blue",
    }
    color = status_colors.get(status, "white")

    console.print(
        f"\n[bold]Pipeline Status:[/bold] [{color}]{status.value}[/{color}]\n"
    )

    # Show last run summary
    data_store = DataStore(config.data_dir)
    runs = data_store.get_run_history(limit=1)
    if runs:
        last_run = runs[0]
        console.print("[bold]Last Run:[/bold]")
        _display_run_metadata(last_run)
    else:
        console.print("[dim]No previous runs found.[/dim]")


async def _cmd_review(config: PipelineConfig) -> None:
    """Handle the 'review' subcommand — launch CLI approval interface.

    Args:
        config: The loaded pipeline configuration.
    """
    from linkedin_optimizer.persistence.data_store import DataStore
    from linkedin_optimizer.approval.workflow import ApprovalWorkflow
    from linkedin_optimizer.integrations.hf_client import HuggingFaceClient
    from linkedin_optimizer.config import HFModelConfig
    from linkedin_optimizer.agents.content_creator_agent import ContentCreatorAgent

    data_store = DataStore(config.data_dir)

    # Initialize content creator for revision support
    content_hf_config = HFModelConfig(
        model_id=config.content_model_id,
        fallback_model_id=config.fallback_model_id,
        api_token=config.hf_api_token,
        timeout_seconds=config.hf_timeout_seconds,
        max_retries=config.hf_max_retries,
    )
    content_hf_client = HuggingFaceClient(content_hf_config)
    content_creator = ContentCreatorAgent(
        model_id=config.content_model_id,
        fallback_model_id=config.fallback_model_id,
        hf_client=content_hf_client,
    )

    workflow = ApprovalWorkflow(
        data_store=data_store,
        notification_service=None,
        content_creator_agent=content_creator,
    )

    cli_interface = CLIApprovalInterface(workflow=workflow, console=console)
    await cli_interface.run()


async def _cmd_history(config: PipelineConfig, limit: int) -> None:
    """Handle the 'history' subcommand — show recent run history.

    Args:
        config: The loaded pipeline configuration.
        limit: Maximum number of runs to display.
    """
    from linkedin_optimizer.persistence.data_store import DataStore

    data_store = DataStore(config.data_dir)
    runs = data_store.get_run_history(limit=limit)

    if not runs:
        console.print("[dim]No run history found.[/dim]")
        return

    console.print()
    table = Table(title="Pipeline Run History", show_lines=True)
    table.add_column("Run ID", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Started", style="green")
    table.add_column("Duration", justify="right")
    table.add_column("Summary")

    status_colors = {
        PipelineStatus.COMPLETED: "green",
        PipelineStatus.FAILED: "red",
        PipelineStatus.RUNNING: "yellow",
        PipelineStatus.IDLE: "dim",
        PipelineStatus.PAUSED: "blue",
    }

    for run in runs:
        color = status_colors.get(run.status, "white")
        status_text = f"[{color}]{run.status.value}[/{color}]"
        started = run.start_time.strftime("%Y-%m-%d %H:%M:%S")

        duration = ""
        if run.end_time:
            secs = (run.end_time - run.start_time).total_seconds()
            duration = f"{secs:.1f}s"

        summary = run.summary or run.error or ""
        # Truncate long summaries
        if len(summary) > 60:
            summary = summary[:57] + "..."

        table.add_row(run.run_id, status_text, started, duration, summary)

    console.print(table)
    console.print()


def _cmd_config(config_path: str, set_value: Optional[str]) -> None:
    """Handle the 'config' subcommand — display or update configuration.

    Args:
        config_path: Path to the configuration file.
        set_value: Optional key=value string to update.
    """
    config_file = Path(config_path)

    if set_value:
        # Update a configuration value
        if "=" not in set_value:
            console.print("[red]Invalid format. Use --set KEY=VALUE[/red]")
            return

        key, value = set_value.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not config_file.exists():
            console.print(f"[red]Configuration file not found: {config_path}[/red]")
            return

        try:
            with open(config_file, "r") as f:
                raw_config = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            console.print(f"[red]Failed to read config: {e}[/red]")
            return

        # Support nested keys with dot notation (e.g., models.analyzer_model_id)
        keys = key.split(".")
        target = raw_config
        for k in keys[:-1]:
            if k not in target or not isinstance(target[k], dict):
                target[k] = {}
            target = target[k]

        # Try to parse as JSON value (for bools, numbers, etc.)
        try:
            parsed_value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            parsed_value = value

        target[keys[-1]] = parsed_value

        try:
            with open(config_file, "w") as f:
                json.dump(raw_config, f, indent=2, ensure_ascii=False)
            console.print(f"[green]✓ Updated {key} = {parsed_value}[/green]")
        except OSError as e:
            console.print(f"[red]Failed to write config: {e}[/red]")

    else:
        # Display current configuration
        if not config_file.exists():
            console.print(f"[red]Configuration file not found: {config_path}[/red]")
            return

        try:
            with open(config_file, "r") as f:
                raw_config = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            console.print(f"[red]Failed to read config: {e}[/red]")
            return

        # Mask sensitive values
        display_config = json.loads(json.dumps(raw_config))
        if "huggingface" in display_config and "api_token" in display_config["huggingface"]:
            token = display_config["huggingface"]["api_token"]
            if token and not token.startswith("${"):
                display_config["huggingface"]["api_token"] = token[:8] + "..." if len(token) > 8 else "***"

        console.print()
        console.print(Panel(
            json.dumps(display_config, indent=2),
            title="[bold]Current Configuration[/bold]",
            border_style="blue",
        ))
        console.print(f"\n[dim]Config file: {config_file.resolve()}[/dim]")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Optional list of argument strings. If None, uses sys.argv[1:].

    Returns:
        Parsed argparse.Namespace.
    """
    parser = _build_parser()
    return parser.parse_args(argv)


async def _async_main(args: argparse.Namespace) -> int:
    """Async entry point for dispatching subcommands.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code: 0 for success, 1 for failure.
    """
    if args.command == "config":
        # Config command doesn't need async or full config loading
        _cmd_config(args.config, getattr(args, "set_key", None))
        return 0

    if args.command is None:
        console.print("[yellow]No command specified. Use --help for usage.[/yellow]")
        return 1

    config = _load_config_safe(args.config)
    if config is None:
        return 1

    if args.command == "run":
        await _cmd_run(config)
    elif args.command == "schedule":
        await _cmd_schedule(config, args.interval)
    elif args.command == "pause":
        await _cmd_pause(config)
    elif args.command == "resume":
        await _cmd_resume(config)
    elif args.command == "status":
        await _cmd_status(config)
    elif args.command == "review":
        await _cmd_review(config)
    elif args.command == "history":
        await _cmd_history(config, args.limit)
    else:
        console.print(f"[red]Unknown command: {args.command}[/red]")
        return 1

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """Main CLI entry point.

    Parses arguments, sets up logging, and dispatches to the appropriate
    subcommand handler via asyncio.run().

    Args:
        argv: Optional list of argument strings. If None, uses sys.argv[1:].

    Returns:
        Exit code: 0 for success, 1 for failure.
    """
    args = parse_args(argv)

    _setup_logging(getattr(args, "verbose", False))

    if args.command is None:
        if argv is not None:
            # Called programmatically with no command
            return 1
        _build_parser().print_help()
        return 1

    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
