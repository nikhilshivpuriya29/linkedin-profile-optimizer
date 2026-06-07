"""Profile Scraper for extracting LinkedIn profile data with retry logic.

This module orchestrates full profile extraction via the LinkedInMCPClient,
handling URL validation, exponential backoff retries, and partial/total failure modes.
"""

import asyncio
import logging
import re
from typing import Any, Callable, Optional

from linkedin_optimizer.scrapers.linkedin_mcp_client import (
    LinkedInMCPClient,
    MCPConnectionError,
    MCPToolError,
)
from linkedin_optimizer.models import ExtractionResult, ProfileData

logger = logging.getLogger(__name__)

# Regex for valid LinkedIn profile URLs
_LINKEDIN_URL_PATTERN = re.compile(
    r"^https://(www\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+/?$"
)


class ProfileScraper:
    """Extracts LinkedIn profile data with retry logic and partial failure handling.

    Orchestrates full profile extraction from a LinkedIn profile URL via the
    MCP client. Supports exponential backoff retries for transient failures,
    reports partial extractions when some sections fail, and returns clear
    error results for total failures.

    Usage:
        client = LinkedInMCPClient(config)
        scraper = ProfileScraper(client, max_retries=3)
        result = await scraper.extract("https://www.linkedin.com/in/username")
    """

    def __init__(self, mcp_client: LinkedInMCPClient, max_retries: int = 3):
        """Initialize the ProfileScraper.

        Args:
            mcp_client: An instance of LinkedInMCPClient for MCP communication.
            max_retries: Maximum number of retry attempts for failed operations.
                         Defaults to 3.
        """
        self._mcp_client = mcp_client
        self._max_retries = max_retries

    async def extract(self, profile_url: str) -> ExtractionResult:
        """Extract all profile sections from a LinkedIn profile URL.

        Orchestrates the full extraction flow:
        1. Validates the profile URL format.
        2. Calls the MCP client to get profile data with retry logic.
        3. Parses the raw response into a ProfileData dataclass.
        4. Handles partial failures by populating failed_sections.
        5. Handles total failures by returning success=False.

        Args:
            profile_url: The LinkedIn profile URL to extract data from.
                         Must match https://(www.)linkedin.com/in/...

        Returns:
            ExtractionResult with:
                - success=True, profile_data populated on full/partial success
                - success=False, profile_data=None on total failure
        """
        # Step 1: Validate URL format
        if not self._validate_url(profile_url):
            logger.warning("Invalid LinkedIn profile URL: %s", profile_url)
            return ExtractionResult(
                success=False,
                profile_data=None,
                error_message=f"Invalid LinkedIn profile URL: {profile_url}",
            )

        # Step 2: Attempt profile extraction with retries
        try:
            raw_data = await self._retry_with_backoff(
                lambda: self._mcp_client.get_person_profile(profile_url),
                max_attempts=self._max_retries,
            )
        except MCPConnectionError as e:
            logger.error("MCP connection error during extraction: %s", e)
            return ExtractionResult(
                success=False,
                profile_data=None,
                error_message=f"Connection error: {e}",
            )
        except MCPToolError as e:
            logger.error("MCP tool error during extraction: %s", e)
            return ExtractionResult(
                success=False,
                profile_data=None,
                error_message=f"Extraction failed: {e}",
            )

        # Step 2.5: Validate we got a valid response
        if raw_data is None or not isinstance(raw_data, dict):
            logger.error("Empty or invalid response from MCP server")
            return ExtractionResult(
                success=False,
                profile_data=None,
                error_message="Empty or invalid response from LinkedIn MCP server",
            )

        # Step 3: Parse the raw response into ProfileData
        profile_data, failed_sections = self._parse_profile_response(raw_data)

        # Step 4: Return result based on extraction completeness
        if failed_sections:
            logger.info(
                "Partial extraction completed. Failed sections: %s",
                failed_sections,
            )
            return ExtractionResult(
                success=True,
                profile_data=profile_data,
                failed_sections=failed_sections,
                error_message=f"Some sections failed extraction: {', '.join(failed_sections)}",
            )

        logger.info("Full profile extraction completed successfully.")
        return ExtractionResult(
            success=True,
            profile_data=profile_data,
        )

    def _parse_profile_response(self, raw_data: dict) -> tuple[ProfileData, list[str]]:
        """Parse raw MCP response dict into a structured ProfileData object.

        Maps known fields from the MCP response to ProfileData fields.
        Tracks any sections that could not be parsed due to unexpected
        formats or missing data indicators.

        Args:
            raw_data: The raw dictionary response from the MCP get_person_profile tool.

        Returns:
            A tuple of (ProfileData, failed_sections_list).
            failed_sections will be empty if all sections parsed successfully.
        """
        failed_sections: list[str] = []

        # Map raw data fields to ProfileData with safe extraction
        headline = self._safe_get_str(raw_data, "headline", "headline", failed_sections)
        about = self._safe_get_str(raw_data, "about", "about", failed_sections)
        experience = self._safe_get_list(raw_data, "experience", "experience", failed_sections)
        skills = self._safe_get_list(raw_data, "skills", "skills", failed_sections)
        endorsements = self._safe_get_list(raw_data, "endorsements", "endorsements", failed_sections)
        posts = self._safe_get_list(raw_data, "posts", "posts", failed_sections)
        education = self._safe_get_list(raw_data, "education", "education", failed_sections)
        certifications = self._safe_get_list(raw_data, "certifications", "certifications", failed_sections)

        # Optional URL fields - don't fail on these
        banner_url = raw_data.get("banner_url") or raw_data.get("bannerUrl")
        photo_url = raw_data.get("photo_url") or raw_data.get("photoUrl") or raw_data.get("profilePicture")

        # Numeric fields with fallback keys
        follower_count = self._safe_get_int(
            raw_data, "follower_count", "follower_count", failed_sections
        )
        connection_count = self._safe_get_int(
            raw_data, "connection_count", "connection_count", failed_sections
        )
        profile_views = raw_data.get("profile_views") or raw_data.get("profileViews")

        profile_data = ProfileData(
            headline=headline,
            about=about,
            experience=experience,
            skills=skills,
            endorsements=endorsements,
            posts=posts,
            banner_url=banner_url,
            photo_url=photo_url,
            education=education,
            certifications=certifications,
            follower_count=follower_count,
            connection_count=connection_count,
            profile_views=profile_views,
        )

        return profile_data, failed_sections

    async def _retry_with_backoff(
        self, operation: Callable, max_attempts: int = 3
    ) -> Any:
        """Retry an async operation with exponential backoff.

        Starts with a 2-second delay and doubles on each retry attempt.
        Backoff sequence: 2s, 4s, 8s, ...

        Args:
            operation: A callable (async function or lambda returning a coroutine)
                       to retry on failure.
            max_attempts: Maximum number of attempts before raising the last exception.

        Returns:
            The result of the successful operation call.

        Raises:
            MCPConnectionError: If all attempts fail due to connection issues.
            MCPToolError: If all attempts fail due to tool errors.
        """
        last_exception: Optional[Exception] = None
        base_delay = 2.0  # Starting backoff delay in seconds

        for attempt in range(1, max_attempts + 1):
            try:
                result = await operation()
                return result
            except (MCPConnectionError, MCPToolError) as e:
                last_exception = e
                if attempt < max_attempts:
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                        attempt,
                        max_attempts,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "All %d attempts exhausted. Last error: %s",
                        max_attempts,
                        e,
                    )

        # Should not reach here, but raise last exception for safety
        raise last_exception  # type: ignore[misc]

    def _validate_url(self, url: Any) -> bool:
        """Validate that a URL matches the expected LinkedIn profile format.

        Valid formats:
            - https://www.linkedin.com/in/username
            - https://linkedin.com/in/username
            - https://www.linkedin.com/in/user-name/

        Args:
            url: The URL to validate. Must be a non-empty string.

        Returns:
            True if the URL matches a valid LinkedIn profile pattern.
        """
        if not url or not isinstance(url, str):
            return False
        return _LINKEDIN_URL_PATTERN.match(url) is not None

    def _safe_get_str(
        self,
        data: dict,
        primary_key: str,
        section_name: str,
        failed_sections: list[str],
    ) -> str:
        """Safely extract a string field from the raw data.

        If the value exists but is of an unexpected type (not str),
        the section is marked as failed.

        Args:
            data: The raw data dictionary.
            primary_key: The key to look up in the data.
            section_name: The human-readable section name for failure tracking.
            failed_sections: List to append to if extraction fails unexpectedly.

        Returns:
            The extracted string, or empty string if not present.
        """
        value = data.get(primary_key)
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        # Unexpected type - try to convert
        try:
            return str(value)
        except Exception:
            failed_sections.append(section_name)
            return ""

    def _safe_get_list(
        self,
        data: dict,
        primary_key: str,
        section_name: str,
        failed_sections: list[str],
    ) -> list[dict]:
        """Safely extract a list field from the raw data.

        If the value exists but is not a list, the section is marked as failed.

        Args:
            data: The raw data dictionary.
            primary_key: The key to look up in the data.
            section_name: The human-readable section name for failure tracking.
            failed_sections: List to append to if extraction fails unexpectedly.

        Returns:
            The extracted list, or empty list if not present.
        """
        value = data.get(primary_key)
        if value is None:
            return []
        if isinstance(value, list):
            return value
        # Unexpected type
        failed_sections.append(section_name)
        return []

    def _safe_get_int(
        self,
        data: dict,
        primary_key: str,
        section_name: str,
        failed_sections: list[str],
    ) -> int:
        """Safely extract an integer value from raw data.

        Args:
            data: The raw data dictionary.
            primary_key: The key to look up.
            section_name: The human-readable section name for failure tracking.
            failed_sections: List to append to if extraction fails unexpectedly.

        Returns:
            The integer value found, or 0 if not found or not convertible.
        """
        value = data.get(primary_key)
        if value is None:
            return 0
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except (ValueError, TypeError):
            failed_sections.append(section_name)
            return 0
