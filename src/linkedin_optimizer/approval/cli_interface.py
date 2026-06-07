"""CLI approval interface using rich for terminal formatting.

Provides a terminal-based interactive interface for reviewing and acting
on content suggestions in the approval workflow.

Implements Requirements 5.1, 5.2, 5.3, 5.5, 5.6.
"""

import logging
from typing import Optional

from rich.console import Console
from rich.columns import Columns
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from linkedin_optimizer.approval.workflow import ApprovalWorkflow
from linkedin_optimizer.models import ApprovalItem, ApprovalSession, ApprovalStatus

logger = logging.getLogger(__name__)

# Maximum feedback/reason length
MAX_FEEDBACK_LENGTH = 500


class CLIApprovalInterface:
    """Terminal-based approval interface using rich library.

    Provides an interactive CLI for reviewing pending approval items,
    displaying side-by-side diffs, and processing user decisions.

    Implements Requirements 5.1, 5.2, 5.3, 5.5, 5.6.
    """

    def __init__(self, workflow: ApprovalWorkflow, console: Optional[Console] = None) -> None:
        """Initialize the CLI approval interface.

        Args:
            workflow: The ApprovalWorkflow instance to interact with.
            console: Optional rich Console instance (uses default if not provided).
        """
        self.workflow = workflow
        self.console = console or Console()

    def display_summary(self, pending_items: list[ApprovalItem]) -> None:
        """Display summary of pending approval items.

        Shows the count of pending items and a table with section names
        and creation dates.

        Req 5.1: Present all proposed changes for review.

        Args:
            pending_items: List of pending ApprovalItem objects.
        """
        self.console.print()
        self.console.rule("[bold blue]Approval Review Session[/bold blue]")
        self.console.print()

        if not pending_items:
            self.console.print(
                "[yellow]No pending items to review.[/yellow]"
            )
            return

        self.console.print(
            f"[bold]{len(pending_items)}[/bold] item(s) pending approval.\n"
        )

        table = Table(title="Pending Approval Items", show_lines=True)
        table.add_column("#", style="dim", width=4)
        table.add_column("Section", style="cyan")
        table.add_column("Created At", style="green")
        table.add_column("Expires At", style="yellow")

        for idx, item in enumerate(pending_items, start=1):
            created = item.created_at.strftime("%Y-%m-%d %H:%M")
            expires = (
                item.expires_at.strftime("%Y-%m-%d %H:%M")
                if item.expires_at
                else "N/A"
            )
            table.add_row(str(idx), item.section_name.title(), created, expires)

        self.console.print(table)
        self.console.print()

    def display_session_list(self, sessions: list[ApprovalSession]) -> None:
        """List all pending approval sessions with creation dates.

        Args:
            sessions: List of ApprovalSession objects.
        """
        self.console.print()
        self.console.rule("[bold blue]Approval Sessions[/bold blue]")
        self.console.print()

        if not sessions:
            self.console.print("[yellow]No approval sessions found.[/yellow]")
            return

        table = Table(title="Approval Sessions", show_lines=True)
        table.add_column("Session ID", style="cyan")
        table.add_column("Run ID", style="magenta")
        table.add_column("Items", style="green", justify="center")
        table.add_column("Pending", style="yellow", justify="center")
        table.add_column("Created At", style="blue")

        for session in sessions:
            pending_count = sum(
                1 for item in session.items
                if item.status == ApprovalStatus.PENDING
            )
            table.add_row(
                session.session_id,
                session.run_id,
                str(len(session.items)),
                str(pending_count),
                session.created_at.strftime("%Y-%m-%d %H:%M"),
            )

        self.console.print(table)
        self.console.print()

    def display_diff(self, item: ApprovalItem) -> None:
        """Display side-by-side diff of current vs proposed content.

        Uses rich Columns with colored panels: red for current, green for proposed.

        Req 5.2: Side-by-side comparison of current vs proposed.

        Args:
            item: The ApprovalItem to display the diff for.
        """
        self.console.print()
        self.console.rule(
            f"[bold]Section: {item.section_name.title()}[/bold]"
        )
        self.console.print()

        # Current content panel (red border)
        current_text = Text(item.current_content or "(empty)")
        current_panel = Panel(
            current_text,
            title="[bold red]Current Content[/bold red]",
            border_style="red",
            expand=True,
        )

        # Proposed content panel (green border)
        proposed_text = Text(item.proposed_content or "(empty)")
        proposed_panel = Panel(
            proposed_text,
            title="[bold green]Proposed Content[/bold green]",
            border_style="green",
            expand=True,
        )

        # Display side-by-side using Columns
        columns = Columns([current_panel, proposed_panel], equal=True, expand=True)
        self.console.print(columns)
        self.console.print()

    def display_menu(self) -> None:
        """Display the interactive action menu."""
        menu_text = Text()
        menu_text.append("[A]", style="bold green")
        menu_text.append("pprove  ")
        menu_text.append("[R]", style="bold red")
        menu_text.append("eject  ")
        menu_text.append("[M]", style="bold yellow")
        menu_text.append("odify  ")
        menu_text.append("[S]", style="bold blue")
        menu_text.append("kip  ")
        menu_text.append("[Q]", style="bold magenta")
        menu_text.append("uit")

        self.console.print(
            Panel(menu_text, title="Actions", border_style="dim")
        )

    def prompt_action(self) -> str:
        """Prompt user for an action choice.

        Returns:
            The user's choice as a lowercase single character: 'a', 'r', 'm', 's', or 'q'.
        """
        while True:
            choice = Prompt.ask(
                "Choose action",
                choices=["a", "r", "m", "s", "q"],
                default="s",
                console=self.console,
            )
            return choice.lower()

    def prompt_feedback(self, action_label: str) -> str:
        """Prompt user for feedback text with validation.

        Validates that feedback is ≤500 characters.

        Req 5.5, 5.6: Allow feedback ≤500 chars.

        Args:
            action_label: Label describing the action (e.g., "modification feedback",
                         "rejection reason").

        Returns:
            The validated feedback string (may be empty for optional feedback).
        """
        while True:
            feedback = Prompt.ask(
                f"Enter {action_label} (max {MAX_FEEDBACK_LENGTH} chars, or press Enter to skip)",
                default="",
                console=self.console,
            )

            if len(feedback) <= MAX_FEEDBACK_LENGTH:
                return feedback

            self.console.print(
                f"[red]Feedback too long ({len(feedback)} chars). "
                f"Maximum is {MAX_FEEDBACK_LENGTH} characters.[/red]"
            )

    async def run(self) -> dict:
        """Run the interactive approval review session.

        Fetches pending items from the workflow and loops through them,
        presenting each for user action.

        Returns:
            A summary dict with counts of actions taken:
            {"approved": int, "rejected": int, "modified": int, "skipped": int}
        """
        pending_items = await self.workflow.get_pending_items()
        return await self.review_items(pending_items)

    async def review_items(self, pending_items: Optional[list[ApprovalItem]] = None) -> dict:
        """Run interactive review session for pending items.

        Iterates through pending items, displaying diffs and processing
        user decisions via the interactive menu.

        Req 5.1: Present all proposed changes for review.
        Req 5.3: Allow approve, reject, or modify independently.

        Args:
            pending_items: Optional list of items to review. If None,
                          fetches pending items from the workflow.

        Returns:
            A summary dict with counts of actions taken:
            {"approved": int, "rejected": int, "modified": int, "skipped": int}
        """
        if pending_items is None:
            pending_items = await self.workflow.get_pending_items()

        # Display session summary
        self.display_summary(pending_items)

        if not pending_items:
            return {"approved": 0, "rejected": 0, "modified": 0, "skipped": 0}

        summary = {"approved": 0, "rejected": 0, "modified": 0, "skipped": 0}

        for idx, item in enumerate(pending_items, start=1):
            self.console.print(
                f"\n[dim]Item {idx} of {len(pending_items)}[/dim]"
            )

            # Show side-by-side diff
            self.display_diff(item)

            # Show menu and get action
            self.display_menu()
            action = self.prompt_action()

            if action == "a":
                # Approve
                await self.workflow.approve(item.item_id)
                self.console.print(
                    f"[green]✓ {item.section_name.title()} approved.[/green]"
                )
                summary["approved"] += 1

            elif action == "r":
                # Reject — prompt for optional reason
                reason = self.prompt_feedback("rejection reason")
                reason_arg = reason if reason else None
                await self.workflow.reject(item.item_id, reason_arg)
                self.console.print(
                    f"[red]✗ {item.section_name.title()} rejected.[/red]"
                )
                summary["rejected"] += 1

            elif action == "m":
                # Modify — prompt for required feedback
                feedback = self._prompt_required_feedback("modification feedback")
                await self.workflow.request_modification(item.item_id, feedback)
                self.console.print(
                    f"[yellow]↻ {item.section_name.title()} sent for modification.[/yellow]"
                )
                summary["modified"] += 1

            elif action == "s":
                # Skip
                self.console.print(
                    f"[blue]→ {item.section_name.title()} skipped.[/blue]"
                )
                summary["skipped"] += 1

            elif action == "q":
                # Quit
                remaining = len(pending_items) - idx
                self.console.print(
                    f"\n[magenta]Exiting review. {remaining} item(s) remaining.[/magenta]"
                )
                summary["skipped"] += remaining
                break

        # Display final summary
        self._display_review_summary(summary)

        return summary

    def _prompt_required_feedback(self, action_label: str) -> str:
        """Prompt for required (non-empty) feedback with ≤500 char validation.

        Args:
            action_label: Label describing the action context.

        Returns:
            A non-empty feedback string within the character limit.
        """
        while True:
            feedback = Prompt.ask(
                f"Enter {action_label} (max {MAX_FEEDBACK_LENGTH} chars, required)",
                console=self.console,
            )

            if not feedback.strip():
                self.console.print(
                    "[red]Feedback is required for modifications. Please try again.[/red]"
                )
                continue

            if len(feedback) > MAX_FEEDBACK_LENGTH:
                self.console.print(
                    f"[red]Feedback too long ({len(feedback)} chars). "
                    f"Maximum is {MAX_FEEDBACK_LENGTH} characters.[/red]"
                )
                continue

            return feedback

    def _display_review_summary(self, summary: dict) -> None:
        """Display final summary of the review session.

        Args:
            summary: Dict with counts of actions taken.
        """
        self.console.print()
        self.console.rule("[bold]Review Session Complete[/bold]")
        self.console.print()

        table = Table(show_header=False, box=None)
        table.add_column("Action", style="bold")
        table.add_column("Count", justify="right")

        table.add_row("[green]Approved[/green]", str(summary["approved"]))
        table.add_row("[red]Rejected[/red]", str(summary["rejected"]))
        table.add_row("[yellow]Modified[/yellow]", str(summary["modified"]))
        table.add_row("[blue]Skipped[/blue]", str(summary["skipped"]))

        self.console.print(table)
        self.console.print()
