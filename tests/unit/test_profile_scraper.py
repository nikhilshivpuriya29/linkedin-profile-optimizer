"""Unit tests for ProfileScraper."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from linkedin_optimizer.scrapers.profile_scraper import ProfileScraper
from linkedin_optimizer.scrapers.linkedin_mcp_client import (
    LinkedInMCPClient,
    MCPConnectionError,
    MCPToolError,
)
from linkedin_optimizer.models import ExtractionResult, ProfileData


@pytest.fixture
def mock_mcp_client():
    """Create a mock MCP client."""
    client = AsyncMock(spec=LinkedInMCPClient)
    return client


@pytest.fixture
def scraper(mock_mcp_client):
    """Create a ProfileScraper with a mock client."""
    return ProfileScraper(mock_mcp_client, max_retries=3)


@pytest.fixture
def sample_profile_response():
    """Return a sample complete profile response dict."""
    return {
        "headline": "Software Engineer at Google",
        "about": "Passionate about building scalable systems.",
        "experience": [
            {
                "title": "Software Engineer",
                "company": "Google",
                "duration": "2020 - Present",
            }
        ],
        "skills": [{"name": "Python", "endorsements": 25}],
        "endorsements": [{"skill": "Python", "endorser": "John Doe"}],
        "posts": [{"text": "Great day!", "reactions": 10, "comments": 2}],
        "banner_url": "https://example.com/banner.jpg",
        "photo_url": "https://example.com/photo.jpg",
        "education": [{"school": "MIT", "degree": "BS CS"}],
        "certifications": [{"name": "AWS Solutions Architect"}],
        "follower_count": 5000,
        "connection_count": 500,
        "profile_views": 1200,
    }


class TestProfileScraperInit:
    """Tests for ProfileScraper initialization."""

    def test_default_max_retries(self, mock_mcp_client):
        scraper = ProfileScraper(mock_mcp_client)
        assert scraper._max_retries == 3

    def test_custom_max_retries(self, mock_mcp_client):
        scraper = ProfileScraper(mock_mcp_client, max_retries=5)
        assert scraper._max_retries == 5

    def test_stores_mcp_client(self, mock_mcp_client):
        scraper = ProfileScraper(mock_mcp_client)
        assert scraper._mcp_client is mock_mcp_client


class TestURLValidation:
    """Tests for URL validation logic."""

    def test_valid_url_with_www(self, scraper):
        assert scraper._validate_url("https://www.linkedin.com/in/johndoe") is True

    def test_valid_url_without_www(self, scraper):
        assert scraper._validate_url("https://linkedin.com/in/johndoe") is True

    def test_valid_url_with_trailing_slash(self, scraper):
        assert scraper._validate_url("https://www.linkedin.com/in/johndoe/") is True

    def test_valid_url_with_hyphens(self, scraper):
        assert scraper._validate_url("https://www.linkedin.com/in/john-doe-123") is True

    def test_invalid_url_http(self, scraper):
        assert scraper._validate_url("http://www.linkedin.com/in/johndoe") is False

    def test_invalid_url_wrong_domain(self, scraper):
        assert scraper._validate_url("https://www.facebook.com/in/johndoe") is False

    def test_invalid_url_wrong_path(self, scraper):
        assert scraper._validate_url("https://www.linkedin.com/company/google") is False

    def test_invalid_url_empty(self, scraper):
        assert scraper._validate_url("") is False

    def test_invalid_url_none(self, scraper):
        assert scraper._validate_url(None) is False  # type: ignore

    def test_invalid_url_not_string(self, scraper):
        assert scraper._validate_url(123) is False  # type: ignore

    def test_invalid_url_no_username(self, scraper):
        assert scraper._validate_url("https://www.linkedin.com/in/") is False


class TestExtract:
    """Tests for the extract method."""

    @pytest.mark.asyncio
    async def test_successful_extraction(
        self, scraper, mock_mcp_client, sample_profile_response
    ):
        mock_mcp_client.get_person_profile.return_value = sample_profile_response

        result = await scraper.extract("https://www.linkedin.com/in/johndoe")

        assert result.success is True
        assert result.profile_data is not None
        assert result.profile_data.headline == "Software Engineer at Google"
        assert result.profile_data.about == "Passionate about building scalable systems."
        assert len(result.profile_data.experience) == 1
        assert len(result.profile_data.skills) == 1
        assert result.profile_data.follower_count == 5000
        assert result.failed_sections == []
        assert result.error_message is None

    @pytest.mark.asyncio
    async def test_invalid_url_returns_failure(self, scraper):
        result = await scraper.extract("https://www.facebook.com/johndoe")

        assert result.success is False
        assert result.profile_data is None
        assert "Invalid LinkedIn profile URL" in result.error_message

    @pytest.mark.asyncio
    async def test_connection_error_returns_failure(self, scraper, mock_mcp_client):
        mock_mcp_client.get_person_profile.side_effect = MCPConnectionError(
            "Server not available"
        )

        result = await scraper.extract("https://www.linkedin.com/in/johndoe")

        assert result.success is False
        assert result.profile_data is None
        assert "Connection error" in result.error_message

    @pytest.mark.asyncio
    async def test_tool_error_returns_failure(self, scraper, mock_mcp_client):
        mock_mcp_client.get_person_profile.side_effect = MCPToolError(
            "Profile not found", tool_name="get_person_profile"
        )

        result = await scraper.extract("https://www.linkedin.com/in/johndoe")

        assert result.success is False
        assert result.profile_data is None
        assert "Extraction failed" in result.error_message

    @pytest.mark.asyncio
    async def test_empty_response_returns_failure(self, scraper, mock_mcp_client):
        mock_mcp_client.get_person_profile.return_value = {}

        result = await scraper.extract("https://www.linkedin.com/in/johndoe")

        # Empty dict should still produce a ProfileData with defaults
        # since all sections just default to empty
        assert result.success is True
        assert result.profile_data is not None
        assert result.profile_data.headline == ""

    @pytest.mark.asyncio
    async def test_none_response_returns_failure(self, scraper, mock_mcp_client):
        mock_mcp_client.get_person_profile.return_value = None

        result = await scraper.extract("https://www.linkedin.com/in/johndoe")

        assert result.success is False
        assert result.profile_data is None
        assert "Empty or invalid response" in result.error_message

    @pytest.mark.asyncio
    async def test_partial_extraction_with_failed_sections(
        self, scraper, mock_mcp_client
    ):
        """When some sections have unexpected types, track them as failed."""
        mock_mcp_client.get_person_profile.return_value = {
            "headline": "Software Engineer",
            "about": "Some text",
            "experience": "not a list",  # Wrong type - should be list
            "skills": 12345,  # Wrong type - should be list
            "follower_count": 100,
        }

        result = await scraper.extract("https://www.linkedin.com/in/johndoe")

        assert result.success is True
        assert result.profile_data is not None
        assert result.profile_data.headline == "Software Engineer"
        assert "experience" in result.failed_sections
        assert "skills" in result.failed_sections

    @pytest.mark.asyncio
    async def test_url_without_www(self, scraper, mock_mcp_client, sample_profile_response):
        mock_mcp_client.get_person_profile.return_value = sample_profile_response

        result = await scraper.extract("https://linkedin.com/in/johndoe")

        assert result.success is True
        assert result.profile_data is not None


class TestParseProfileResponse:
    """Tests for _parse_profile_response method."""

    def test_full_response_parsing(self, scraper, sample_profile_response):
        profile_data, failed = scraper._parse_profile_response(sample_profile_response)

        assert profile_data.headline == "Software Engineer at Google"
        assert profile_data.about == "Passionate about building scalable systems."
        assert len(profile_data.experience) == 1
        assert profile_data.experience[0]["company"] == "Google"
        assert profile_data.follower_count == 5000
        assert profile_data.connection_count == 500
        assert profile_data.profile_views == 1200
        assert profile_data.banner_url == "https://example.com/banner.jpg"
        assert failed == []

    def test_missing_fields_default_to_empty(self, scraper):
        profile_data, failed = scraper._parse_profile_response({})

        assert profile_data.headline == ""
        assert profile_data.about == ""
        assert profile_data.experience == []
        assert profile_data.skills == []
        assert profile_data.follower_count == 0
        assert profile_data.banner_url is None
        assert profile_data.profile_views is None
        assert failed == []

    def test_wrong_type_for_list_field(self, scraper):
        profile_data, failed = scraper._parse_profile_response(
            {"experience": "not a list"}
        )

        assert profile_data.experience == []
        assert "experience" in failed

    def test_wrong_type_for_int_field(self, scraper):
        profile_data, failed = scraper._parse_profile_response(
            {"follower_count": [1, 2, 3]}
        )

        assert profile_data.follower_count == 0
        assert "follower_count" in failed

    def test_numeric_string_for_int_field(self, scraper):
        """Numeric strings should be converted to int."""
        profile_data, failed = scraper._parse_profile_response(
            {"follower_count": "5000"}
        )

        assert profile_data.follower_count == 5000
        assert "follower_count" not in failed


class TestRetryWithBackoff:
    """Tests for _retry_with_backoff method."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self, scraper):
        operation = AsyncMock(return_value={"headline": "test"})

        result = await scraper._retry_with_backoff(operation, max_attempts=3)

        assert result == {"headline": "test"}
        assert operation.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self, scraper):
        operation = AsyncMock(
            side_effect=[
                MCPConnectionError("timeout"),
                MCPConnectionError("timeout"),
                {"headline": "test"},
            ]
        )

        with patch("linkedin_optimizer.scrapers.profile_scraper.asyncio.sleep"):
            result = await scraper._retry_with_backoff(operation, max_attempts=3)

        assert result == {"headline": "test"}
        assert operation.call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self, scraper):
        operation = AsyncMock(
            side_effect=MCPConnectionError("persistent failure")
        )

        with patch("linkedin_optimizer.scrapers.profile_scraper.asyncio.sleep"):
            with pytest.raises(MCPConnectionError, match="persistent failure"):
                await scraper._retry_with_backoff(operation, max_attempts=3)

        assert operation.call_count == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self, scraper):
        operation = AsyncMock(
            side_effect=[
                MCPConnectionError("fail"),
                MCPConnectionError("fail"),
                {"headline": "test"},
            ]
        )

        with patch(
            "linkedin_optimizer.scrapers.profile_scraper.asyncio.sleep"
        ) as mock_sleep:
            mock_sleep.return_value = None
            result = await scraper._retry_with_backoff(operation, max_attempts=3)

        # First retry: 2 * 2^0 = 2s
        # Second retry: 2 * 2^1 = 4s
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(2.0)
        mock_sleep.assert_any_call(4.0)

    @pytest.mark.asyncio
    async def test_retries_on_tool_error(self, scraper):
        operation = AsyncMock(
            side_effect=[
                MCPToolError("rate limited"),
                {"headline": "test"},
            ]
        )

        with patch("linkedin_optimizer.scrapers.profile_scraper.asyncio.sleep"):
            result = await scraper._retry_with_backoff(operation, max_attempts=3)

        assert result == {"headline": "test"}
        assert operation.call_count == 2
