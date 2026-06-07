"""GitHub profile data extractor using the GitHub REST API."""

import asyncio
import logging
from typing import Optional

import httpx

from linkedin_optimizer.models import (
    GitHubContributions,
    GitHubData,
    GitHubExtractionResult,
    GitHubRepo,
)

logger = logging.getLogger(__name__)

GITHUB_API_BASE_URL = "https://api.github.com"


class GitHubExtractor:
    """Extracts GitHub profile data via REST API.

    Retrieves public repositories, contribution activity, pinned repos,
    and language statistics for a given GitHub username.
    """

    def __init__(self, username: str, timeout: int = 15) -> None:
        """Initialize the GitHub extractor.

        Args:
            username: GitHub username to extract data for.
            timeout: Connection timeout in seconds (default 15).
        """
        self.username = username
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def extract(self) -> GitHubExtractionResult:
        """Extract repos, contributions, and languages within 30 seconds.

        Orchestrates all GitHub data extraction. If some categories fail,
        returns partial results with unavailable_categories populated.

        Returns:
            GitHubExtractionResult with extracted data or error info.
        """
        try:
            async with httpx.AsyncClient(
                base_url=GITHUB_API_BASE_URL,
                timeout=httpx.Timeout(self.timeout, connect=self.timeout),
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "linkedin-optimizer",
                },
            ) as client:
                self._client = client

                # Overall 30-second timeout for all extraction
                try:
                    result = await asyncio.wait_for(
                        self._extract_all(), timeout=30.0
                    )
                    return result
                except asyncio.TimeoutError:
                    logger.warning(
                        "GitHub extraction timed out after 30 seconds for user %s",
                        self.username,
                    )
                    return GitHubExtractionResult(
                        success=False,
                        data=None,
                        error_message="GitHub extraction timed out after 30 seconds",
                    )
        except httpx.ConnectTimeout:
            logger.warning(
                "Connection timeout to GitHub API for user %s", self.username
            )
            return GitHubExtractionResult(
                success=False,
                data=None,
                error_message=f"Connection timeout exceeding {self.timeout} seconds",
            )
        except httpx.HTTPError as e:
            logger.error("HTTP error during GitHub extraction: %s", str(e))
            return GitHubExtractionResult(
                success=False,
                data=None,
                error_message=f"HTTP error: {str(e)}",
            )

    async def _extract_all(self) -> GitHubExtractionResult:
        """Internal method that performs all extraction steps.

        Handles partial failures gracefully - if repos succeed but other
        categories fail, returns partial=True with available data.
        """
        unavailable_categories: list[str] = []
        repos: list[GitHubRepo] = []
        contributions = GitHubContributions()
        pinned_repos: list[GitHubRepo] = []

        # Extract repos
        try:
            repos = await self._get_repos()
        except (httpx.HTTPStatusError, httpx.HTTPError) as e:
            if self._is_private_or_not_found(e):
                return GitHubExtractionResult(
                    success=False,
                    data=None,
                    error_message=f"GitHub profile '{self.username}' is private or does not exist",
                )
            logger.warning("Failed to get repos for %s: %s", self.username, str(e))
            unavailable_categories.append("repos")
        except Exception as e:
            logger.warning("Unexpected error getting repos for %s: %s", self.username, str(e))
            unavailable_categories.append("repos")

        # Extract contributions
        try:
            contributions = await self._get_contributions()
        except (httpx.HTTPStatusError, httpx.HTTPError) as e:
            logger.warning(
                "Failed to get contributions for %s: %s", self.username, str(e)
            )
            unavailable_categories.append("contributions")
        except Exception as e:
            logger.warning(
                "Unexpected error getting contributions for %s: %s", self.username, str(e)
            )
            unavailable_categories.append("contributions")

        # Extract pinned repos
        try:
            pinned_repos = await self._get_pinned_repos()
        except (httpx.HTTPStatusError, httpx.HTTPError) as e:
            logger.warning(
                "Failed to get pinned repos for %s: %s", self.username, str(e)
            )
            unavailable_categories.append("pinned_repos")
        except Exception as e:
            logger.warning(
                "Unexpected error getting pinned repos for %s: %s", self.username, str(e)
            )
            unavailable_categories.append("pinned_repos")

        # Mark pinned repos in the repos list
        pinned_names = {r.name for r in pinned_repos}
        for repo in repos:
            if repo.name in pinned_names:
                repo.is_pinned = True

        # Compute languages from repos
        languages = self._compute_languages(repos)

        # Identify notable repos
        notable_repos = self._identify_notable_repos(repos)

        # If all categories failed, report failure
        if not repos and "repos" in unavailable_categories:
            return GitHubExtractionResult(
                success=False,
                data=None,
                partial=False,
                unavailable_categories=unavailable_categories,
                error_message="Failed to extract any GitHub data",
            )

        data = GitHubData(
            repos=repos,
            contributions=contributions,
            pinned_repos=pinned_repos,
            languages=languages,
            notable_repos=notable_repos,
        )

        partial = len(unavailable_categories) > 0

        return GitHubExtractionResult(
            success=True,
            data=data,
            partial=partial,
            unavailable_categories=unavailable_categories,
        )

    async def _get_repos(self) -> list[GitHubRepo]:
        """Fetch public repositories sorted by stars (descending).

        Calls GET /users/{username}/repos with sort=stars.

        Returns:
            List of GitHubRepo objects.

        Raises:
            httpx.HTTPStatusError: On HTTP error responses (404, 403, etc).
            httpx.HTTPError: On network/connection errors.
        """
        assert self._client is not None

        response = await self._client.get(
            f"/users/{self.username}/repos",
            params={
                "sort": "stars",
                "direction": "desc",
                "per_page": 100,
                "type": "owner",
            },
        )
        response.raise_for_status()

        repos_data = response.json()
        repos: list[GitHubRepo] = []

        for repo_data in repos_data:
            repo = GitHubRepo(
                name=repo_data.get("name", ""),
                description=repo_data.get("description"),
                stars=repo_data.get("stargazers_count", 0),
                primary_language=repo_data.get("language"),
                is_pinned=False,
                url=repo_data.get("html_url", ""),
            )
            repos.append(repo)

        return repos

    async def _get_contributions(self) -> GitHubContributions:
        """Aggregate contribution activity over the most recent 12 months.

        Uses the GitHub Events API and search API to estimate commits,
        PRs, and issues over the past year.

        Returns:
            GitHubContributions with aggregated activity data.

        Raises:
            httpx.HTTPStatusError: On HTTP error responses.
        """
        assert self._client is not None

        total_commits = 0
        total_prs = 0
        total_issues = 0

        # Get commit count via search API (commits authored by user in last year)
        try:
            response = await self._client.get(
                "/search/commits",
                params={
                    "q": f"author:{self.username} committer-date:>2024-01-01",
                    "per_page": 1,
                },
                headers={"Accept": "application/vnd.github.cloak-preview+json"},
            )
            if response.status_code == 200:
                data = response.json()
                total_commits = data.get("total_count", 0)
        except httpx.HTTPError:
            logger.debug("Could not fetch commit count for %s", self.username)

        # Get PR count via search API
        try:
            response = await self._client.get(
                "/search/issues",
                params={
                    "q": f"author:{self.username} type:pr created:>2024-01-01",
                    "per_page": 1,
                },
            )
            if response.status_code == 200:
                data = response.json()
                total_prs = data.get("total_count", 0)
        except httpx.HTTPError:
            logger.debug("Could not fetch PR count for %s", self.username)

        # Get issues count via search API
        try:
            response = await self._client.get(
                "/search/issues",
                params={
                    "q": f"author:{self.username} type:issue created:>2024-01-01",
                    "per_page": 1,
                },
            )
            if response.status_code == 200:
                data = response.json()
                total_issues = data.get("total_count", 0)
        except httpx.HTTPError:
            logger.debug("Could not fetch issue count for %s", self.username)

        # Calculate average commits per week (52 weeks in a year)
        commits_per_week_avg = round(total_commits / 52.0, 2) if total_commits > 0 else 0.0

        return GitHubContributions(
            total_commits_12m=total_commits,
            total_prs_12m=total_prs,
            total_issues_12m=total_issues,
            commits_per_week_avg=commits_per_week_avg,
        )

    async def _get_pinned_repos(self) -> list[GitHubRepo]:
        """Fetch pinned repositories via GitHub GraphQL API.

        Falls back to an empty list if GraphQL is unavailable
        (requires auth token for GraphQL).

        Returns:
            List of pinned GitHubRepo objects.

        Raises:
            httpx.HTTPStatusError: On HTTP error responses.
        """
        assert self._client is not None

        # Try GraphQL API for pinned repos
        query = """
        {
          user(login: "%s") {
            pinnedItems(first: 6, types: REPOSITORY) {
              nodes {
                ... on Repository {
                  name
                  description
                  stargazerCount
                  primaryLanguage {
                    name
                  }
                  url
                }
              }
            }
          }
        }
        """ % self.username

        try:
            response = await self._client.post(
                "https://api.github.com/graphql",
                json={"query": query},
            )

            if response.status_code == 200:
                data = response.json()
                if "data" in data and data["data"].get("user"):
                    pinned_nodes = (
                        data["data"]["user"]
                        .get("pinnedItems", {})
                        .get("nodes", [])
                    )
                    pinned_repos: list[GitHubRepo] = []
                    for node in pinned_nodes:
                        if node:
                            language = None
                            if node.get("primaryLanguage"):
                                language = node["primaryLanguage"].get("name")
                            repo = GitHubRepo(
                                name=node.get("name", ""),
                                description=node.get("description"),
                                stars=node.get("stargazerCount", 0),
                                primary_language=language,
                                is_pinned=True,
                                url=node.get("url", ""),
                            )
                            pinned_repos.append(repo)
                    return pinned_repos
        except httpx.HTTPError:
            logger.debug(
                "GraphQL API unavailable for pinned repos, returning empty list"
            )

        # GraphQL requires auth - return empty if unavailable
        return []

    def _identify_notable_repos(self, repos: list[GitHubRepo]) -> list[GitHubRepo]:
        """Filter repos that are notable: ≥5 stars OR is_pinned=True.

        This is a pure function that filters based on star count and pinned status.

        Args:
            repos: List of repositories to filter.

        Returns:
            List of notable repositories.
        """
        return [
            repo for repo in repos
            if repo.stars >= 5 or repo.is_pinned
        ]

    def _compute_languages(self, repos: list[GitHubRepo]) -> dict[str, int]:
        """Aggregate primary languages across all repos.

        Counts how many repos use each language as their primary language.

        Args:
            repos: List of repositories to aggregate from.

        Returns:
            Dictionary mapping language name to repo count.
        """
        languages: dict[str, int] = {}
        for repo in repos:
            if repo.primary_language:
                languages[repo.primary_language] = (
                    languages.get(repo.primary_language, 0) + 1
                )
        return languages

    def _is_private_or_not_found(self, error: Exception) -> bool:
        """Check if an error indicates a private or non-existent profile.

        Args:
            error: The exception to check.

        Returns:
            True if the error is a 404 or 403 indicating private/missing profile.
        """
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code in (404, 403)
        return False
