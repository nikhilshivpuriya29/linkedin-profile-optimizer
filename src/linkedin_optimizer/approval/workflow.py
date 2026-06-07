"""Approval workflow for human-in-the-loop content review.

Manages the lifecycle of content suggestions through approval, rejection,
modification, and expiration. Implements Requirements 5.1-5.9.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, Protocol

from linkedin_optimizer.models import (
    ApprovalItem,
    ApprovalSession,
    ApprovalStatus,
    ContentPackage,
    ProfileData,
)
from linkedin_optimizer.persistence.data_store import DataStore

logger = logging.getLogger(__name__)

# Approval items expire after 7 days (Req 5.7)
EXPIRATION_DAYS = 7

# Maximum feedback/reason length (Req 5.5, 5.6)
MAX_FEEDBACK_LENGTH = 500


class NotificationService(Protocol):
    """Protocol for notification delivery."""

    def notify(self, message: str) -> None:
        """Send a notification message to the user."""
        ...


class ContentCreatorAgentProtocol(Protocol):
    """Protocol for the content creator agent's revision capability."""

    async def revise_suggestion(
        self, original: str, feedback: str, section_name: str
    ) -> str:
        """Revise a suggestion based on user feedback."""
        ...


class ApprovalWorkflow:
    """Manages human-in-the-loop content approval.

    Coordinates the review lifecycle for generated content suggestions,
    allowing users to approve, reject, or request modifications before
    any changes are applied to their profile.

    Implements Requirements 5.1-5.9.
    """

    def __init__(
        self,
        data_store: DataStore,
        notification_service: NotificationService,
        content_creator_agent: ContentCreatorAgentProtocol,
    ) -> None:
        """Initialize the ApprovalWorkflow.

        Args:
            data_store: Persistence layer for saving/loading approval sessions.
            notification_service: Service for sending user notifications.
            content_creator_agent: Agent used for revising suggestions on modification requests.
        """
        self.data_store = data_store
        self.notification_service = notification_service
        self.content_creator_agent = content_creator_agent
        self._sessions: dict[str, ApprovalSession] = {}

    async def submit_for_review(
        self, content_package: ContentPackage, current_profile: ProfileData
    ) -> ApprovalSession:
        """Create an approval session with side-by-side comparisons.

        For each section in the content_package that has generated content,
        creates an ApprovalItem comparing the current profile content against
        the proposed content.

        Req 5.1: Present all proposed changes for review.
        Req 5.2: Side-by-side comparison of current vs proposed.
        Req 5.7: expires_at = created_at + 7 days.
        Req 5.8: Notify user within 5 minutes of generation.

        Args:
            content_package: The generated content suggestions.
            current_profile: The user's current profile data.

        Returns:
            An ApprovalSession containing all approval items.
        """
        now = datetime.now()
        session_id = f"approval_{now.strftime('%Y-%m-%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        run_id = f"run_{now.strftime('%Y-%m-%d_%H%M%S')}"

        items: list[ApprovalItem] = []

        # Create approval items for each section with content
        if content_package.headline is not None:
            items.append(
                ApprovalItem(
                    item_id=f"item_headline_{uuid.uuid4().hex[:8]}",
                    section_name="headline",
                    current_content=current_profile.headline,
                    proposed_content=content_package.headline.text,
                    status=ApprovalStatus.PENDING,
                    created_at=now,
                    expires_at=now + timedelta(days=EXPIRATION_DAYS),
                )
            )

        if content_package.about is not None:
            items.append(
                ApprovalItem(
                    item_id=f"item_about_{uuid.uuid4().hex[:8]}",
                    section_name="about",
                    current_content=current_profile.about,
                    proposed_content=content_package.about.text,
                    status=ApprovalStatus.PENDING,
                    created_at=now,
                    expires_at=now + timedelta(days=EXPIRATION_DAYS),
                )
            )

        if content_package.experience:
            # Combine experience suggestions into a single reviewable item
            current_exp_text = "\n\n".join(
                f"{exp.get('title', 'Role')} at {exp.get('company', 'Company')}:\n"
                + exp.get("description", "")
                for exp in current_profile.experience
            )
            proposed_exp_text = "\n\n".join(
                f"{exp.role_title} at {exp.company}:\n"
                + "\n".join(f"• {b}" for b in exp.bullets)
                for exp in content_package.experience
            )
            items.append(
                ApprovalItem(
                    item_id=f"item_experience_{uuid.uuid4().hex[:8]}",
                    section_name="experience",
                    current_content=current_exp_text,
                    proposed_content=proposed_exp_text,
                    status=ApprovalStatus.PENDING,
                    created_at=now,
                    expires_at=now + timedelta(days=EXPIRATION_DAYS),
                )
            )

        if content_package.banner is not None:
            current_banner = current_profile.banner_url or "(no banner)"
            proposed_banner = (
                f"Dimensions: {content_package.banner.dimensions}\n"
                f"Colors: {', '.join(content_package.banner.color_palette)}\n"
                f"Tagline: {content_package.banner.tagline}"
            )
            items.append(
                ApprovalItem(
                    item_id=f"item_banner_{uuid.uuid4().hex[:8]}",
                    section_name="banner",
                    current_content=current_banner,
                    proposed_content=proposed_banner,
                    status=ApprovalStatus.PENDING,
                    created_at=now,
                    expires_at=now + timedelta(days=EXPIRATION_DAYS),
                )
            )

        session = ApprovalSession(
            session_id=session_id,
            run_id=run_id,
            items=items,
            created_at=now,
            notification_sent=False,
        )

        # Persist the session
        self.data_store.save_approval_session(session)
        self._sessions[session_id] = session

        # Notify user (Req 5.8: within 5 minutes of generation)
        await self.notify_user(session)

        return session

    async def approve(self, item_id: str) -> ApprovalItem:
        """Approve a content suggestion.

        Transitions the item to APPROVED status and triggers application
        within 30 seconds (Req 5.4).

        Args:
            item_id: The unique identifier of the approval item.

        Returns:
            The updated ApprovalItem with APPROVED status.

        Raises:
            ValueError: If item_id is not found.
        """
        item, session = self._find_item(item_id)

        item.status = ApprovalStatus.APPROVED
        item.decided_at = datetime.now()

        # Persist updated session
        self.data_store.save_approval_session(session)

        logger.info(
            "Item %s approved. Changes will be applied within 30 seconds.",
            item_id,
        )

        return item

    async def reject(self, item_id: str, reason: Optional[str] = None) -> ApprovalItem:
        """Reject a content suggestion with optional reason.

        Req 5.6: Record rejection reason (≤500 chars) for future learning.

        Args:
            item_id: The unique identifier of the approval item.
            reason: Optional rejection reason (max 500 characters).

        Returns:
            The updated ApprovalItem with REJECTED status.

        Raises:
            ValueError: If item_id is not found or reason exceeds 500 chars.
        """
        if reason is not None and len(reason) > MAX_FEEDBACK_LENGTH:
            raise ValueError(
                f"Rejection reason must be at most {MAX_FEEDBACK_LENGTH} characters, "
                f"got {len(reason)}."
            )

        item, session = self._find_item(item_id)

        item.status = ApprovalStatus.REJECTED
        item.rejection_reason = reason
        item.decided_at = datetime.now()

        # Persist updated session
        self.data_store.save_approval_session(session)

        logger.info("Item %s rejected. Reason: %s", item_id, reason or "(none)")

        return item

    async def request_modification(
        self, item_id: str, feedback: str
    ) -> ApprovalItem:
        """Request modification of a content suggestion.

        Validates feedback length, triggers content revision via the
        content creator agent, and updates the proposed content.

        Req 5.5: Allow feedback ≤500 chars, generate revised suggestion.

        Args:
            item_id: The unique identifier of the approval item.
            feedback: User feedback for the revision (max 500 characters).

        Returns:
            The updated ApprovalItem with MODIFIED status and revised content.

        Raises:
            ValueError: If item_id is not found or feedback exceeds 500 chars.
        """
        if len(feedback) > MAX_FEEDBACK_LENGTH:
            raise ValueError(
                f"Feedback must be at most {MAX_FEEDBACK_LENGTH} characters, "
                f"got {len(feedback)}."
            )

        item, session = self._find_item(item_id)

        # Call content creator agent to revise the suggestion
        revised_content = await self.content_creator_agent.revise_suggestion(
            original=item.proposed_content,
            feedback=feedback,
            section_name=item.section_name,
        )

        item.proposed_content = revised_content
        item.user_feedback = feedback
        item.status = ApprovalStatus.MODIFIED
        item.decided_at = datetime.now()

        # Persist updated session
        self.data_store.save_approval_session(session)

        logger.info("Item %s modified based on user feedback.", item_id)

        return item

    async def get_pending_items(self) -> list[ApprovalItem]:
        """Get all pending approval items that have not expired.

        Req 5.7: Items are pending if status=PENDING and not past expires_at.

        Returns:
            List of ApprovalItem objects with PENDING status and valid expiration.
        """
        now = datetime.now()
        pending: list[ApprovalItem] = []

        for session in self._sessions.values():
            for item in session.items:
                if (
                    item.status == ApprovalStatus.PENDING
                    and item.expires_at is not None
                    and now < item.expires_at
                ):
                    pending.append(item)

        return pending

    async def expire_stale_items(self) -> list[ApprovalItem]:
        """Expire items older than 7 days and notify the user.

        Req 5.7: Persist pending approvals for 7 days then expire.
        Req 5.9: Notify user when suggestions expire.

        Returns:
            List of ApprovalItem objects that were expired.
        """
        now = datetime.now()
        expired_items: list[ApprovalItem] = []

        for session in self._sessions.values():
            session_modified = False
            for item in session.items:
                if (
                    item.status == ApprovalStatus.PENDING
                    and item.expires_at is not None
                    and now >= item.expires_at
                ):
                    item.status = ApprovalStatus.EXPIRED
                    item.decided_at = now
                    expired_items.append(item)
                    session_modified = True

            if session_modified:
                self.data_store.save_approval_session(session)

        # Notify user about expired items (Req 5.9)
        if expired_items:
            section_names = ", ".join(item.section_name for item in expired_items)
            self.notification_service.notify(
                f"{len(expired_items)} suggestion(s) have expired without action: "
                f"{section_names}. Run the pipeline again to generate fresh suggestions."
            )

        return expired_items

    async def notify_user(self, session: ApprovalSession) -> None:
        """Send notification to user about new content for review.

        Req 5.8: Notify within 5 minutes of generation.

        Args:
            session: The approval session with items ready for review.
        """
        item_count = len(session.items)
        section_names = ", ".join(item.section_name for item in session.items)

        message = (
            f"New content suggestions ready for review! "
            f"{item_count} item(s) pending approval for: {section_names}. "
            f"These will expire in {EXPIRATION_DAYS} days if not reviewed."
        )

        self.notification_service.notify(message)
        session.notification_sent = True

        # Persist the notification_sent flag
        self.data_store.save_approval_session(session)

        logger.info(
            "Notification sent for session %s with %d items.",
            session.session_id,
            item_count,
        )

    def _find_item(self, item_id: str) -> tuple[ApprovalItem, ApprovalSession]:
        """Find an approval item by ID across all sessions.

        Args:
            item_id: The unique identifier of the approval item.

        Returns:
            Tuple of (ApprovalItem, ApprovalSession) containing the item.

        Raises:
            ValueError: If the item_id is not found in any session.
        """
        for session in self._sessions.values():
            for item in session.items:
                if item.item_id == item_id:
                    return item, session

        raise ValueError(f"Approval item '{item_id}' not found.")
