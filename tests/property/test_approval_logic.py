"""Property-based tests for approval logic (Properties 19, 20, 21).

**Validates: Requirements 5.3, 5.5, 5.6, 5.7**

These tests verify:
- Property 19: Approval item independence — performing an action on one item
  does not change the status of any other item in the session
- Property 20: Approval expiration after 7 days — items with created_at in the
  past (>7 days) are marked EXPIRED by expire_stale_items()
- Property 21: User input validation enforces 500 character limit — strings of
  varying lengths are accepted/rejected at the 500-character boundary
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Optional

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from linkedin_optimizer.approval.workflow import (
    ApprovalWorkflow,
    ContentCreatorAgentProtocol,
    EXPIRATION_DAYS,
    MAX_FEEDBACK_LENGTH,
    NotificationService,
)
from linkedin_optimizer.models import (
    ApprovalItem,
    ApprovalSession,
    ApprovalStatus,
)


# =============================================================================
# In-memory test doubles
# =============================================================================


class InMemoryDataStore:
    """Simple in-memory implementation of DataStore for testing."""

    def __init__(self) -> None:
        self.saved_sessions: dict[str, ApprovalSession] = {}

    def save_approval_session(self, session: ApprovalSession) -> str:
        self.saved_sessions[session.session_id] = session
        return session.session_id


class InMemoryNotificationService:
    """Simple in-memory notification service for testing."""

    def __init__(self) -> None:
        self.notifications: list[str] = []

    def notify(self, message: str) -> None:
        self.notifications.append(message)


class MockContentCreatorAgent:
    """Mock content creator agent that returns simple revisions."""

    async def revise_suggestion(
        self, original: str, feedback: str, section_name: str
    ) -> str:
        return f"[Revised] {original[:50]}... (feedback: {feedback[:20]})"


# =============================================================================
# Custom Strategies
# =============================================================================

SECTION_NAMES = ["headline", "about", "experience", "skills", "banner"]


@st.composite
def approval_item_strategy(draw, status=None, expired=False):
    """Generate a random ApprovalItem."""
    item_id = f"item_{draw(st.sampled_from(SECTION_NAMES))}_{uuid.uuid4().hex[:8]}"
    section_name = draw(st.sampled_from(SECTION_NAMES))
    current_content = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs")),
        min_size=5,
        max_size=100,
    ))
    proposed_content = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs")),
        min_size=5,
        max_size=100,
    ))

    item_status = status or ApprovalStatus.PENDING
    now = datetime.now()

    if expired:
        # Created more than 7 days ago
        days_ago = draw(st.integers(min_value=8, max_value=30))
        created_at = now - timedelta(days=days_ago)
    else:
        # Created recently (within 7 days)
        hours_ago = draw(st.integers(min_value=0, max_value=72))
        created_at = now - timedelta(hours=hours_ago)

    expires_at = created_at + timedelta(days=EXPIRATION_DAYS)

    return ApprovalItem(
        item_id=item_id,
        section_name=section_name,
        current_content=current_content,
        proposed_content=proposed_content,
        status=item_status,
        created_at=created_at,
        expires_at=expires_at,
    )


@st.composite
def approval_session_with_multiple_items(draw, min_items=2, max_items=5):
    """Generate an ApprovalSession with multiple PENDING items."""
    num_items = draw(st.integers(min_value=min_items, max_value=max_items))
    now = datetime.now()
    session_id = f"approval_{uuid.uuid4().hex[:8]}"
    run_id = f"run_{uuid.uuid4().hex[:8]}"

    items = []
    for i in range(num_items):
        section = SECTION_NAMES[i % len(SECTION_NAMES)]
        item = ApprovalItem(
            item_id=f"item_{section}_{uuid.uuid4().hex[:8]}",
            section_name=section,
            current_content=f"Current content for {section}",
            proposed_content=f"Proposed content for {section}",
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(days=EXPIRATION_DAYS),
        )
        items.append(item)

    return ApprovalSession(
        session_id=session_id,
        run_id=run_id,
        items=items,
        created_at=now,
        notification_sent=True,
    )


@st.composite
def expired_session_strategy(draw):
    """Generate an ApprovalSession with items that have expired (>7 days old)."""
    num_items = draw(st.integers(min_value=1, max_value=4))
    now = datetime.now()
    session_id = f"approval_{uuid.uuid4().hex[:8]}"
    run_id = f"run_{uuid.uuid4().hex[:8]}"

    # Created more than 7 days ago
    days_ago = draw(st.integers(min_value=8, max_value=30))
    created_at = now - timedelta(days=days_ago)
    expires_at = created_at + timedelta(days=EXPIRATION_DAYS)

    items = []
    for i in range(num_items):
        section = SECTION_NAMES[i % len(SECTION_NAMES)]
        item = ApprovalItem(
            item_id=f"item_{section}_{uuid.uuid4().hex[:8]}",
            section_name=section,
            current_content=f"Current content for {section}",
            proposed_content=f"Proposed content for {section}",
            status=ApprovalStatus.PENDING,
            created_at=created_at,
            expires_at=expires_at,
        )
        items.append(item)

    return ApprovalSession(
        session_id=session_id,
        run_id=run_id,
        items=items,
        created_at=created_at,
        notification_sent=True,
    )


def _create_workflow() -> tuple[ApprovalWorkflow, InMemoryDataStore, InMemoryNotificationService]:
    """Create an ApprovalWorkflow with in-memory test doubles."""
    data_store = InMemoryDataStore()
    notification_service = InMemoryNotificationService()
    content_creator = MockContentCreatorAgent()
    workflow = ApprovalWorkflow(
        data_store=data_store,
        notification_service=notification_service,
        content_creator_agent=content_creator,
    )
    return workflow, data_store, notification_service


# =============================================================================
# Property 19: Approval item independence
# =============================================================================


@pytest.mark.property
@pytest.mark.asyncio
class TestProperty19ApprovalItemIndependence:
    """Property 19: Approval item independence.

    **Validates: Requirements 5.3**

    For any set of approval items in a session, performing an action
    (approve, reject, modify) on one item should not change the status
    of any other item.
    """

    @given(session=approval_session_with_multiple_items(min_items=2, max_items=5))
    @settings(max_examples=30, deadline=None)
    async def test_approve_one_item_leaves_others_unchanged(
        self, session: ApprovalSession
    ):
        """Approving one item does not modify other items' statuses."""
        workflow, _, _ = _create_workflow()
        workflow._sessions[session.session_id] = session

        # Pick the first item to approve
        target_item = session.items[0]
        other_items = session.items[1:]

        # Record original statuses of other items
        original_statuses = [
            (item.item_id, item.status, item.proposed_content)
            for item in other_items
        ]

        # Approve the target item
        await workflow.approve(target_item.item_id)

        # Verify target was approved
        assert target_item.status == ApprovalStatus.APPROVED

        # Verify all other items are unchanged
        for item_id, orig_status, orig_content in original_statuses:
            item, _ = workflow._find_item(item_id)
            assert item.status == orig_status, (
                f"Item {item_id} status changed from {orig_status} to {item.status} "
                f"after approving a different item"
            )
            assert item.proposed_content == orig_content, (
                f"Item {item_id} content changed after approving a different item"
            )

    @given(
        session=approval_session_with_multiple_items(min_items=2, max_items=5),
        reason=st.text(
            alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs")),
            min_size=1,
            max_size=100,
        ),
    )
    @settings(max_examples=30, deadline=None)
    async def test_reject_one_item_leaves_others_unchanged(
        self, session: ApprovalSession, reason: str
    ):
        """Rejecting one item does not modify other items' statuses."""
        workflow, _, _ = _create_workflow()
        workflow._sessions[session.session_id] = session

        # Pick the first item to reject
        target_item = session.items[0]
        other_items = session.items[1:]

        # Record original statuses of other items
        original_statuses = [
            (item.item_id, item.status, item.proposed_content)
            for item in other_items
        ]

        # Reject the target item
        await workflow.reject(target_item.item_id, reason)

        # Verify target was rejected
        assert target_item.status == ApprovalStatus.REJECTED

        # Verify all other items are unchanged
        for item_id, orig_status, orig_content in original_statuses:
            item, _ = workflow._find_item(item_id)
            assert item.status == orig_status, (
                f"Item {item_id} status changed from {orig_status} to {item.status} "
                f"after rejecting a different item"
            )
            assert item.proposed_content == orig_content, (
                f"Item {item_id} content changed after rejecting a different item"
            )

    @given(
        session=approval_session_with_multiple_items(min_items=2, max_items=5),
        feedback=st.text(
            alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs")),
            min_size=1,
            max_size=100,
        ),
    )
    @settings(max_examples=30, deadline=None)
    async def test_modify_one_item_leaves_others_unchanged(
        self, session: ApprovalSession, feedback: str
    ):
        """Requesting modification on one item does not modify other items."""
        workflow, _, _ = _create_workflow()
        workflow._sessions[session.session_id] = session

        # Pick the first item to modify
        target_item = session.items[0]
        other_items = session.items[1:]

        # Record original statuses and content of other items
        original_states = [
            (item.item_id, item.status, item.proposed_content, item.user_feedback)
            for item in other_items
        ]

        # Request modification on the target item
        await workflow.request_modification(target_item.item_id, feedback)

        # Verify target was modified
        assert target_item.status == ApprovalStatus.MODIFIED

        # Verify all other items are unchanged
        for item_id, orig_status, orig_content, orig_feedback in original_states:
            item, _ = workflow._find_item(item_id)
            assert item.status == orig_status, (
                f"Item {item_id} status changed from {orig_status} to {item.status} "
                f"after modifying a different item"
            )
            assert item.proposed_content == orig_content, (
                f"Item {item_id} content changed after modifying a different item"
            )
            assert item.user_feedback == orig_feedback, (
                f"Item {item_id} feedback changed after modifying a different item"
            )


# =============================================================================
# Property 20: Approval expiration after 7 days
# =============================================================================


@pytest.mark.property
@pytest.mark.asyncio
class TestProperty20ApprovalExpiration:
    """Property 20: Approval expiration after 7 days.

    **Validates: Requirements 5.7**

    For any approval item with status "pending", if the current time exceeds
    created_at + 7 days, the item should transition to "expired" status.
    """

    @given(session=expired_session_strategy())
    @settings(max_examples=30, deadline=None)
    async def test_stale_pending_items_are_expired(self, session: ApprovalSession):
        """Items older than 7 days with PENDING status are marked EXPIRED."""
        workflow, _, _ = _create_workflow()
        workflow._sessions[session.session_id] = session

        # All items should be PENDING initially
        for item in session.items:
            assert item.status == ApprovalStatus.PENDING

        # Run expire_stale_items
        expired_items = await workflow.expire_stale_items()

        # All items should now be EXPIRED since they were created > 7 days ago
        assert len(expired_items) == len(session.items), (
            f"Expected {len(session.items)} expired items, got {len(expired_items)}"
        )

        for item in session.items:
            assert item.status == ApprovalStatus.EXPIRED, (
                f"Item {item.item_id} should be EXPIRED but is {item.status}"
            )

    @given(
        days_past_expiry=st.integers(min_value=1, max_value=60),
        num_items=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=30, deadline=None)
    async def test_expiration_at_various_past_timestamps(
        self, days_past_expiry: int, num_items: int
    ):
        """Items created at various times >7 days ago all get expired."""
        workflow, _, notification_svc = _create_workflow()
        now = datetime.now()

        # Total days past: 7 (expiration) + additional days
        total_days_ago = EXPIRATION_DAYS + days_past_expiry
        created_at = now - timedelta(days=total_days_ago)
        expires_at = created_at + timedelta(days=EXPIRATION_DAYS)

        items = [
            ApprovalItem(
                item_id=f"item_{i}_{uuid.uuid4().hex[:6]}",
                section_name=SECTION_NAMES[i % len(SECTION_NAMES)],
                current_content=f"Current {i}",
                proposed_content=f"Proposed {i}",
                status=ApprovalStatus.PENDING,
                created_at=created_at,
                expires_at=expires_at,
            )
            for i in range(num_items)
        ]

        session = ApprovalSession(
            session_id=f"session_{uuid.uuid4().hex[:8]}",
            run_id=f"run_{uuid.uuid4().hex[:8]}",
            items=items,
            created_at=created_at,
            notification_sent=True,
        )
        workflow._sessions[session.session_id] = session

        expired = await workflow.expire_stale_items()

        assert len(expired) == num_items
        for item in items:
            assert item.status == ApprovalStatus.EXPIRED

        # Verify notification was sent
        assert len(notification_svc.notifications) > 0

    @given(session=approval_session_with_multiple_items(min_items=2, max_items=4))
    @settings(max_examples=30, deadline=None)
    async def test_non_expired_items_remain_pending(self, session: ApprovalSession):
        """Items created within the last 7 days remain PENDING."""
        workflow, _, _ = _create_workflow()
        workflow._sessions[session.session_id] = session

        # All items are freshly created (within 72 hours) so not expired
        expired = await workflow.expire_stale_items()

        assert len(expired) == 0, (
            f"Expected 0 expired items for fresh session, got {len(expired)}"
        )

        for item in session.items:
            assert item.status == ApprovalStatus.PENDING, (
                f"Fresh item {item.item_id} should still be PENDING"
            )

    @given(
        num_expired=st.integers(min_value=1, max_value=3),
        num_fresh=st.integers(min_value=1, max_value=3),
    )
    @settings(max_examples=30, deadline=None)
    async def test_only_stale_items_are_expired_in_mixed_session(
        self, num_expired: int, num_fresh: int
    ):
        """In a session with both stale and fresh items, only stale ones expire."""
        workflow, _, _ = _create_workflow()
        now = datetime.now()

        stale_created = now - timedelta(days=EXPIRATION_DAYS + 2)
        fresh_created = now - timedelta(hours=1)

        items = []
        stale_ids = set()
        fresh_ids = set()

        for i in range(num_expired):
            item_id = f"stale_{i}_{uuid.uuid4().hex[:6]}"
            stale_ids.add(item_id)
            items.append(ApprovalItem(
                item_id=item_id,
                section_name=SECTION_NAMES[i % len(SECTION_NAMES)],
                current_content=f"Stale current {i}",
                proposed_content=f"Stale proposed {i}",
                status=ApprovalStatus.PENDING,
                created_at=stale_created,
                expires_at=stale_created + timedelta(days=EXPIRATION_DAYS),
            ))

        for i in range(num_fresh):
            item_id = f"fresh_{i}_{uuid.uuid4().hex[:6]}"
            fresh_ids.add(item_id)
            items.append(ApprovalItem(
                item_id=item_id,
                section_name=SECTION_NAMES[i % len(SECTION_NAMES)],
                current_content=f"Fresh current {i}",
                proposed_content=f"Fresh proposed {i}",
                status=ApprovalStatus.PENDING,
                created_at=fresh_created,
                expires_at=fresh_created + timedelta(days=EXPIRATION_DAYS),
            ))

        session = ApprovalSession(
            session_id=f"session_{uuid.uuid4().hex[:8]}",
            run_id=f"run_{uuid.uuid4().hex[:8]}",
            items=items,
            created_at=stale_created,
            notification_sent=True,
        )
        workflow._sessions[session.session_id] = session

        expired = await workflow.expire_stale_items()

        # Only stale items should be expired
        assert len(expired) == num_expired, (
            f"Expected {num_expired} expired, got {len(expired)}"
        )

        expired_ids = {item.item_id for item in expired}
        assert expired_ids == stale_ids

        # Fresh items should remain PENDING
        for item in items:
            if item.item_id in fresh_ids:
                assert item.status == ApprovalStatus.PENDING


# =============================================================================
# Property 21: User input validation enforces 500 character limit
# =============================================================================


@pytest.mark.property
@pytest.mark.asyncio
class TestProperty21UserInputValidation:
    """Property 21: User input validation enforces 500 character limit.

    **Validates: Requirements 5.5, 5.6**

    For any user-provided feedback or rejection reason, the system should
    accept strings of length ≤ 500 characters and reject strings exceeding
    500 characters.
    """

    @given(
        reason=st.text(
            alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs", "Po")),
            min_size=0,
            max_size=MAX_FEEDBACK_LENGTH,
        ),
    )
    @settings(max_examples=50, deadline=None)
    async def test_reject_accepts_reason_within_500_chars(self, reason: str):
        """reject() accepts reasons of length ≤ 500 characters."""
        workflow, _, _ = _create_workflow()

        # Set up a session with a PENDING item
        now = datetime.now()
        item = ApprovalItem(
            item_id=f"item_test_{uuid.uuid4().hex[:8]}",
            section_name="headline",
            current_content="Current headline",
            proposed_content="Proposed headline",
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(days=EXPIRATION_DAYS),
        )
        session = ApprovalSession(
            session_id=f"session_{uuid.uuid4().hex[:8]}",
            run_id=f"run_{uuid.uuid4().hex[:8]}",
            items=[item],
            created_at=now,
            notification_sent=True,
        )
        workflow._sessions[session.session_id] = session

        # Should not raise
        result = await workflow.reject(item.item_id, reason)
        assert result.status == ApprovalStatus.REJECTED
        assert result.rejection_reason == reason

    @given(
        reason=st.text(
            alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs", "Po")),
            min_size=MAX_FEEDBACK_LENGTH + 1,
            max_size=1000,
        ),
    )
    @settings(max_examples=50, deadline=None)
    async def test_reject_raises_for_reason_over_500_chars(self, reason: str):
        """reject() raises ValueError for reasons exceeding 500 characters."""
        workflow, _, _ = _create_workflow()

        now = datetime.now()
        item = ApprovalItem(
            item_id=f"item_test_{uuid.uuid4().hex[:8]}",
            section_name="headline",
            current_content="Current headline",
            proposed_content="Proposed headline",
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(days=EXPIRATION_DAYS),
        )
        session = ApprovalSession(
            session_id=f"session_{uuid.uuid4().hex[:8]}",
            run_id=f"run_{uuid.uuid4().hex[:8]}",
            items=[item],
            created_at=now,
            notification_sent=True,
        )
        workflow._sessions[session.session_id] = session

        with pytest.raises(ValueError):
            await workflow.reject(item.item_id, reason)

    @given(
        feedback=st.text(
            alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs", "Po")),
            min_size=1,
            max_size=MAX_FEEDBACK_LENGTH,
        ),
    )
    @settings(max_examples=50, deadline=None)
    async def test_request_modification_accepts_feedback_within_500_chars(
        self, feedback: str
    ):
        """request_modification() accepts feedback of length ≤ 500 characters."""
        workflow, _, _ = _create_workflow()

        now = datetime.now()
        item = ApprovalItem(
            item_id=f"item_test_{uuid.uuid4().hex[:8]}",
            section_name="about",
            current_content="Current about",
            proposed_content="Proposed about",
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(days=EXPIRATION_DAYS),
        )
        session = ApprovalSession(
            session_id=f"session_{uuid.uuid4().hex[:8]}",
            run_id=f"run_{uuid.uuid4().hex[:8]}",
            items=[item],
            created_at=now,
            notification_sent=True,
        )
        workflow._sessions[session.session_id] = session

        # Should not raise
        result = await workflow.request_modification(item.item_id, feedback)
        assert result.status == ApprovalStatus.MODIFIED
        assert result.user_feedback == feedback

    @given(
        feedback=st.text(
            alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs", "Po")),
            min_size=MAX_FEEDBACK_LENGTH + 1,
            max_size=1000,
        ),
    )
    @settings(max_examples=50, deadline=None)
    async def test_request_modification_raises_for_feedback_over_500_chars(
        self, feedback: str
    ):
        """request_modification() raises ValueError for feedback exceeding 500 characters."""
        workflow, _, _ = _create_workflow()

        now = datetime.now()
        item = ApprovalItem(
            item_id=f"item_test_{uuid.uuid4().hex[:8]}",
            section_name="experience",
            current_content="Current experience",
            proposed_content="Proposed experience",
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(days=EXPIRATION_DAYS),
        )
        session = ApprovalSession(
            session_id=f"session_{uuid.uuid4().hex[:8]}",
            run_id=f"run_{uuid.uuid4().hex[:8]}",
            items=[item],
            created_at=now,
            notification_sent=True,
        )
        workflow._sessions[session.session_id] = session

        with pytest.raises(ValueError):
            await workflow.request_modification(item.item_id, feedback)

    @given(
        length=st.integers(min_value=498, max_value=502),
    )
    @settings(max_examples=20, deadline=None)
    async def test_boundary_validation_at_500_chars(self, length: int):
        """Validate exact boundary behavior at 500 characters for reject()."""
        workflow, _, _ = _create_workflow()

        now = datetime.now()
        item = ApprovalItem(
            item_id=f"item_test_{uuid.uuid4().hex[:8]}",
            section_name="headline",
            current_content="Current",
            proposed_content="Proposed",
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(days=EXPIRATION_DAYS),
        )
        session = ApprovalSession(
            session_id=f"session_{uuid.uuid4().hex[:8]}",
            run_id=f"run_{uuid.uuid4().hex[:8]}",
            items=[item],
            created_at=now,
            notification_sent=True,
        )
        workflow._sessions[session.session_id] = session

        reason = "a" * length

        if length <= MAX_FEEDBACK_LENGTH:
            # Should accept
            result = await workflow.reject(item.item_id, reason)
            assert result.status == ApprovalStatus.REJECTED
        else:
            # Should reject
            with pytest.raises(ValueError):
                await workflow.reject(item.item_id, reason)

    @given(
        length=st.integers(min_value=498, max_value=502),
    )
    @settings(max_examples=20, deadline=None)
    async def test_boundary_validation_at_500_chars_for_modification(self, length: int):
        """Validate exact boundary behavior at 500 characters for request_modification()."""
        workflow, _, _ = _create_workflow()

        now = datetime.now()
        item = ApprovalItem(
            item_id=f"item_test_{uuid.uuid4().hex[:8]}",
            section_name="about",
            current_content="Current",
            proposed_content="Proposed",
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(days=EXPIRATION_DAYS),
        )
        session = ApprovalSession(
            session_id=f"session_{uuid.uuid4().hex[:8]}",
            run_id=f"run_{uuid.uuid4().hex[:8]}",
            items=[item],
            created_at=now,
            notification_sent=True,
        )
        workflow._sessions[session.session_id] = session

        feedback = "b" * length

        if length <= MAX_FEEDBACK_LENGTH:
            # Should accept
            result = await workflow.request_modification(item.item_id, feedback)
            assert result.status == ApprovalStatus.MODIFIED
        else:
            # Should reject
            with pytest.raises(ValueError):
                await workflow.request_modification(item.item_id, feedback)
