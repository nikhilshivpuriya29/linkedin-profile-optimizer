"""Property-based tests for extraction error handling.

**Validates: Requirements 1.4, 1.6**

These tests use Hypothesis to verify:
- Property 3: No partial data on total failure (invalid URLs → success=False, profile_data=None, error non-empty)
- Property 5: Partial extraction correctly identifies failed sections
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from linkedin_optimizer.scrapers.profile_scraper import ProfileScraper
from linkedin_optimizer.scrapers.linkedin_mcp_client import (
    LinkedInMCPClient,
    MCPConnectionError,
    MCPToolError,
)
from linkedin_optimizer.models import ExtractionResult, ProfileData


# --- Custom Strategies ---

# Strategy for generating invalid URLs (non-LinkedIn domains, malformed, empty, etc.)
invalid_url_strategies = st.one_of(
    # Empty strings
    st.just(""),
    # None-like values (as strings or actual None)
    st.just(None),
    # Non-LinkedIn domains
    st.from_regex(r"https://[a-z]{3,10}\.(com|org|net)/in/[a-z]{3,10}", fullmatch=True),
    # Malformed URLs (missing protocol)
    st.from_regex(r"linkedin\.com/in/[a-z]{3,10}", fullmatch=True),
    # HTTP instead of HTTPS
    st.from_regex(r"http://www\.linkedin\.com/in/[a-z]{3,10}", fullmatch=True),
    # Wrong LinkedIn path (not /in/)
    st.from_regex(r"https://www\.linkedin\.com/company/[a-z]{3,10}", fullmatch=True),
    # Random strings
    st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=1,
        max_size=100,
    ).filter(lambda s: "linkedin.com/in/" not in s),
    # Numeric values cast as non-string
    st.integers(min_value=0, max_value=99999),
    # Boolean values
    st.booleans(),
)


# Strategy for profile section fields that should be strings
valid_str_values = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=0,
    max_size=100,
)

# Strategy for profile section fields that should be lists
valid_list_values = st.lists(
    st.fixed_dictionaries({"key": st.text(min_size=1, max_size=20)}),
    min_size=0,
    max_size=5,
)

# Strategy for values with wrong types (non-list for list fields)
wrong_type_for_list = st.one_of(
    st.text(min_size=1, max_size=50),  # string instead of list
    st.integers(min_value=0, max_value=999),  # int instead of list
    st.booleans(),  # bool instead of list
    st.fixed_dictionaries({"nested": st.just("dict")}),  # dict instead of list
)

# Strategy for values with wrong types (non-str for str fields)
wrong_type_for_str = st.one_of(
    st.lists(st.just("item"), min_size=1, max_size=3),  # list instead of str
    # Note: int and bool are convertible to str via str(), so they won't fail
)

# The list-type sections in profile data
LIST_SECTIONS = ["experience", "skills", "endorsements", "posts", "education", "certifications"]

# The str-type sections in profile data
STR_SECTIONS = ["headline", "about"]


@st.composite
def partial_failure_data(draw):
    """Generate profile response dicts where some list fields have wrong types.

    Returns a tuple of (raw_data_dict, expected_failed_sections).
    """
    # Decide which list sections will fail (at least 1, up to all)
    sections_to_fail = draw(
        st.lists(
            st.sampled_from(LIST_SECTIONS),
            min_size=1,
            max_size=len(LIST_SECTIONS),
            unique=True,
        )
    )

    raw_data = {}

    # Set correct values for sections NOT failing
    for section in LIST_SECTIONS:
        if section in sections_to_fail:
            # Assign wrong type (non-list value)
            raw_data[section] = draw(wrong_type_for_list)
        else:
            # Assign correct type (list)
            raw_data[section] = draw(valid_list_values)

    # Always provide valid str fields so we can check they're preserved
    raw_data["headline"] = draw(valid_str_values)
    raw_data["about"] = draw(valid_str_values)

    return raw_data, sections_to_fail


# =============================================================================
# Property 3: Extraction error handling — no partial data on total failure
# =============================================================================


@pytest.mark.property
class TestProperty3ExtractionErrorHandling:
    """Property 3: Extraction error handling — no partial data on total failure.

    **Validates: Requirements 1.4**

    For invalid URLs, verify:
    - result.success == False
    - result.profile_data is None
    - result.error_message is a non-empty string
    """

    @given(invalid_url=invalid_url_strategies)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_invalid_urls_produce_failure_result(self, invalid_url):
        """Invalid URLs always produce ExtractionResult with success=False, no profile data."""
        # Create a mock MCP client — it should never be called for invalid URLs
        mock_client = AsyncMock(spec=LinkedInMCPClient)

        scraper = ProfileScraper(mock_client, max_retries=3)
        result = await scraper.extract(invalid_url)

        # Core property assertions
        assert result.success is False, (
            f"Expected success=False for invalid URL: {invalid_url!r}"
        )
        assert result.profile_data is None, (
            f"Expected profile_data=None for invalid URL: {invalid_url!r}, "
            f"got: {result.profile_data}"
        )
        assert result.error_message is not None and len(result.error_message) > 0, (
            f"Expected non-empty error_message for invalid URL: {invalid_url!r}"
        )

    @given(invalid_url=invalid_url_strategies)
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_invalid_urls_do_not_call_mcp_client(self, invalid_url):
        """Invalid URLs should be rejected before any MCP call is made."""
        mock_client = AsyncMock(spec=LinkedInMCPClient)

        scraper = ProfileScraper(mock_client, max_retries=3)
        await scraper.extract(invalid_url)

        # MCP client should never be called for obviously invalid URLs
        mock_client.get_person_profile.assert_not_called()

    @given(
        error_msg=st.text(
            alphabet=st.characters(blacklist_categories=("Cs",)),
            min_size=1,
            max_size=100,
        )
    )
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_mcp_connection_error_produces_failure(self, error_msg):
        """MCP connection errors on valid URLs produce proper failure result."""
        mock_client = AsyncMock(spec=LinkedInMCPClient)
        mock_client.get_person_profile.side_effect = MCPConnectionError(error_msg)

        scraper = ProfileScraper(mock_client, max_retries=1)
        result = await scraper.extract("https://www.linkedin.com/in/testuser")

        assert result.success is False
        assert result.profile_data is None
        assert result.error_message is not None and len(result.error_message) > 0

    @given(
        error_msg=st.text(
            alphabet=st.characters(blacklist_categories=("Cs",)),
            min_size=1,
            max_size=100,
        )
    )
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_mcp_tool_error_produces_failure(self, error_msg):
        """MCP tool errors on valid URLs produce proper failure result."""
        mock_client = AsyncMock(spec=LinkedInMCPClient)
        mock_client.get_person_profile.side_effect = MCPToolError(error_msg)

        scraper = ProfileScraper(mock_client, max_retries=1)
        result = await scraper.extract("https://www.linkedin.com/in/testuser")

        assert result.success is False
        assert result.profile_data is None
        assert result.error_message is not None and len(result.error_message) > 0


# =============================================================================
# Property 5: Partial extraction correctly identifies failed sections
# =============================================================================


@pytest.mark.property
class TestProperty5PartialExtractionFailedSections:
    """Property 5: Partial extraction correctly identifies failed sections.

    **Validates: Requirements 1.6**

    Simulate partial failures where some profile fields have wrong types.
    Verify that:
    - failed_sections contains exactly the fields with wrong types
    - Fields with correct types are preserved in the returned ProfileData
    """

    @given(data=partial_failure_data())
    @settings(max_examples=100)
    def test_failed_sections_lists_exactly_wrong_type_fields(self, data):
        """failed_sections contains exactly the sections whose data had wrong types."""
        raw_data, expected_failed = data

        scraper = ProfileScraper(AsyncMock(spec=LinkedInMCPClient), max_retries=3)
        profile_data, failed_sections = scraper._parse_profile_response(raw_data)

        # failed_sections should contain exactly the sections with wrong types
        assert set(failed_sections) == set(expected_failed), (
            f"Expected failed_sections={sorted(expected_failed)}, "
            f"got {sorted(failed_sections)}. "
            f"Raw data types: {[(k, type(raw_data.get(k)).__name__) for k in LIST_SECTIONS]}"
        )

    @given(data=partial_failure_data())
    @settings(max_examples=100)
    def test_correct_type_fields_are_preserved(self, data):
        """Fields with correct types are preserved in the returned ProfileData."""
        raw_data, expected_failed = data

        scraper = ProfileScraper(AsyncMock(spec=LinkedInMCPClient), max_retries=3)
        profile_data, failed_sections = scraper._parse_profile_response(raw_data)

        # Verify that correctly-typed list fields are preserved
        for section in LIST_SECTIONS:
            if section not in expected_failed:
                actual_value = getattr(profile_data, section)
                assert actual_value == raw_data[section], (
                    f"Section '{section}' should be preserved. "
                    f"Expected {raw_data[section]}, got {actual_value}"
                )

    @given(data=partial_failure_data())
    @settings(max_examples=100)
    def test_str_fields_preserved_alongside_list_failures(self, data):
        """String fields (headline, about) are preserved even when list sections fail."""
        raw_data, expected_failed = data

        scraper = ProfileScraper(AsyncMock(spec=LinkedInMCPClient), max_retries=3)
        profile_data, failed_sections = scraper._parse_profile_response(raw_data)

        # String sections should always be preserved correctly
        assert profile_data.headline == raw_data["headline"]
        assert profile_data.about == raw_data["about"]

    @given(data=partial_failure_data())
    @settings(max_examples=100)
    def test_failed_list_fields_default_to_empty_list(self, data):
        """Sections that fail due to wrong types should default to empty list."""
        raw_data, expected_failed = data

        scraper = ProfileScraper(AsyncMock(spec=LinkedInMCPClient), max_retries=3)
        profile_data, failed_sections = scraper._parse_profile_response(raw_data)

        # Fields that failed should have empty list as fallback
        for section in expected_failed:
            actual_value = getattr(profile_data, section)
            assert actual_value == [], (
                f"Failed section '{section}' should default to [], got {actual_value}"
            )

    @given(
        correct_sections=st.lists(
            st.sampled_from(LIST_SECTIONS),
            min_size=1,
            max_size=len(LIST_SECTIONS),
            unique=True,
        )
    )
    @settings(max_examples=50)
    def test_all_correct_types_yield_no_failed_sections(self, correct_sections):
        """When all provided sections have correct types, failed_sections is empty."""
        raw_data = {}
        for section in correct_sections:
            raw_data[section] = []  # Valid empty list

        raw_data["headline"] = "Test headline"
        raw_data["about"] = "Test about"

        scraper = ProfileScraper(AsyncMock(spec=LinkedInMCPClient), max_retries=3)
        profile_data, failed_sections = scraper._parse_profile_response(raw_data)

        assert failed_sections == [], (
            f"Expected no failed sections when all types are correct, "
            f"got {failed_sections}"
        )
