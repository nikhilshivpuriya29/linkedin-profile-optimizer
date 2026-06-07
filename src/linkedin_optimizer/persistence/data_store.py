"""JSON file-based persistence layer for the LinkedIn Profile Optimizer."""

import json
import logging
from pathlib import Path
from typing import Optional

from linkedin_optimizer.models import (
    ApprovalSession,
    ContentPackage,
    EngagementSnapshot,
    OptimizationReport,
    ProfileData,
    RunMetadata,
)

logger = logging.getLogger(__name__)


class DataStore:
    """JSON file-based persistence layer.

    Manages saving and loading structured data to/from the file system
    using a predefined directory structure.
    """

    SUBDIRS = ["profiles", "reports", "content", "approvals", "engagement", "runs"]

    def __init__(self, data_dir: str) -> None:
        """Initialize the DataStore and create the directory structure.

        Args:
            data_dir: Root directory path for all persisted data.
        """
        self.data_dir = Path(data_dir)
        self._create_directory_structure()

    def _create_directory_structure(self) -> None:
        """Create the required subdirectories if they don't exist."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            for subdir in self.SUBDIRS:
                (self.data_dir / subdir).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error("Failed to create directory structure: %s", e)

    # --- Save Methods ---

    def save_profile_snapshot(self, profile: ProfileData, run_id: str) -> str:
        """Save extracted profile data.

        Args:
            profile: The extracted profile data.
            run_id: Unique identifier for the pipeline run.

        Returns:
            File path of the saved file, or empty string on failure.
        """
        file_path = self.data_dir / "profiles" / f"{run_id}_profile.json"
        return self._write_json(file_path, profile.to_dict())

    def save_optimization_report(self, report: OptimizationReport, run_id: str) -> str:
        """Save analysis report.

        Args:
            report: The optimization report.
            run_id: Unique identifier for the pipeline run.

        Returns:
            File path of the saved file, or empty string on failure.
        """
        file_path = self.data_dir / "reports" / f"{run_id}_report.json"
        return self._write_json(file_path, report.to_dict())

    def save_content_package(self, package: ContentPackage, run_id: str) -> str:
        """Save generated content.

        Args:
            package: The content package.
            run_id: Unique identifier for the pipeline run.

        Returns:
            File path of the saved file, or empty string on failure.
        """
        file_path = self.data_dir / "content" / f"{run_id}_content.json"
        return self._write_json(file_path, package.to_dict())

    def save_approval_session(self, session: ApprovalSession) -> str:
        """Save/update approval session state.

        Args:
            session: The approval session to save.

        Returns:
            File path of the saved file, or empty string on failure.
        """
        file_path = (
            self.data_dir / "approvals" / f"{session.session_id}_approval.json"
        )
        return self._write_json(file_path, session.to_dict())

    def save_run_metadata(self, metadata: RunMetadata) -> str:
        """Save pipeline run metadata.

        Args:
            metadata: The run metadata.

        Returns:
            File path of the saved file, or empty string on failure.
        """
        file_path = self.data_dir / "runs" / f"{metadata.run_id}_meta.json"
        return self._write_json(file_path, metadata.to_dict())

    def save_engagement_snapshot(
        self, snapshot: EngagementSnapshot, change_id: str
    ) -> str:
        """Save engagement metrics for tracking.

        Saves baseline as `engagement/{change_id}/baseline.json` if no baseline
        exists yet. Otherwise saves periodic snapshots under
        `engagement/{change_id}/snapshots/{timestamp}.json`.

        Args:
            snapshot: The engagement snapshot to save.
            change_id: Identifier for the change being tracked.

        Returns:
            File path of the saved file, or empty string on failure.
        """
        change_dir = self.data_dir / "engagement" / change_id
        baseline_path = change_dir / "baseline.json"

        try:
            change_dir.mkdir(parents=True, exist_ok=True)
            (change_dir / "snapshots").mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(
                "Failed to create engagement directory for change %s: %s",
                change_id,
                e,
            )
            return ""

        if not baseline_path.exists():
            return self._write_json(baseline_path, snapshot.to_dict())
        else:
            timestamp = snapshot.timestamp.strftime("%Y%m%d_%H%M%S")
            snapshot_path = change_dir / "snapshots" / f"{timestamp}.json"
            return self._write_json(snapshot_path, snapshot.to_dict())

    # --- Load Methods ---

    def load_approval_session(self, session_id: str) -> Optional[ApprovalSession]:
        """Load approval session by ID.

        Args:
            session_id: The session identifier.

        Returns:
            The loaded ApprovalSession, or None if not found or on error.
        """
        file_path = self.data_dir / "approvals" / f"{session_id}_approval.json"
        data = self._read_json(file_path)
        if data is None:
            return None
        try:
            return ApprovalSession.from_dict(data)
        except (KeyError, ValueError, TypeError) as e:
            logger.error("Failed to parse approval session %s: %s", session_id, e)
            return None

    def load_engagement_history(self, change_id: str) -> list[EngagementSnapshot]:
        """Load all engagement snapshots for a change.

        Returns the baseline followed by all periodic snapshots in
        chronological order.

        Args:
            change_id: Identifier for the change being tracked.

        Returns:
            List of engagement snapshots, empty list if none found or on error.
        """
        snapshots: list[EngagementSnapshot] = []
        change_dir = self.data_dir / "engagement" / change_id

        if not change_dir.exists():
            return snapshots

        # Load baseline
        baseline_path = change_dir / "baseline.json"
        baseline_data = self._read_json(baseline_path)
        if baseline_data is not None:
            try:
                snapshots.append(EngagementSnapshot.from_dict(baseline_data))
            except (KeyError, ValueError, TypeError) as e:
                logger.error(
                    "Failed to parse baseline for change %s: %s", change_id, e
                )

        # Load periodic snapshots
        snapshots_dir = change_dir / "snapshots"
        if snapshots_dir.exists():
            snapshot_files = sorted(snapshots_dir.glob("*.json"))
            for snapshot_file in snapshot_files:
                data = self._read_json(snapshot_file)
                if data is not None:
                    try:
                        snapshots.append(EngagementSnapshot.from_dict(data))
                    except (KeyError, ValueError, TypeError) as e:
                        logger.error(
                            "Failed to parse snapshot %s: %s", snapshot_file.name, e
                        )

        return snapshots

    def load_latest_report(self) -> Optional[OptimizationReport]:
        """Load most recent optimization report.

        Returns:
            The most recent OptimizationReport, or None if none found.
        """
        reports_dir = self.data_dir / "reports"
        if not reports_dir.exists():
            return None

        report_files = sorted(reports_dir.glob("*_report.json"), reverse=True)
        if not report_files:
            return None

        data = self._read_json(report_files[0])
        if data is None:
            return None
        try:
            return OptimizationReport.from_dict(data)
        except (KeyError, ValueError, TypeError) as e:
            logger.error("Failed to parse latest report: %s", e)
            return None

    def get_run_history(self, limit: int = 10) -> list[RunMetadata]:
        """Get recent pipeline run history.

        Args:
            limit: Maximum number of runs to return.

        Returns:
            List of RunMetadata sorted by most recent first.
        """
        runs_dir = self.data_dir / "runs"
        if not runs_dir.exists():
            return []

        run_files = sorted(runs_dir.glob("*_meta.json"), reverse=True)
        results: list[RunMetadata] = []

        for run_file in run_files[:limit]:
            data = self._read_json(run_file)
            if data is not None:
                try:
                    results.append(RunMetadata.from_dict(data))
                except (KeyError, ValueError, TypeError) as e:
                    logger.error("Failed to parse run metadata %s: %s", run_file.name, e)

        return results

    # --- Private Helpers ---

    def _write_json(self, file_path: Path, data: dict) -> str:
        """Write data to a JSON file.

        Args:
            file_path: The target file path.
            data: Dictionary data to serialize.

        Returns:
            The file path as a string on success, empty string on failure.
        """
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            return str(file_path)
        except (OSError, TypeError, ValueError) as e:
            logger.error("Failed to write JSON to %s: %s", file_path, e)
            return ""

    def _read_json(self, file_path: Path) -> Optional[dict]:
        """Read and parse a JSON file.

        Args:
            file_path: The file path to read.

        Returns:
            Parsed dictionary, or None if file doesn't exist or is corrupted.
        """
        if not file_path.exists():
            logger.warning("File not found: %s", file_path)
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error("Failed to read JSON from %s: %s", file_path, e)
            return None
