"""Unit tests for GitHubExtractor."""

import pytest
import httpx
import respx

from linkedin_optimizer.scrapers.github_extractor import (
    GitHubExtractor,
    GITHUB_API_BASE_URL,
)
from linkedin_optimizer.models import GitHubRepo


@pytest.fixture
def sample_repos_response():
    """Sample GitHub repos API response."""
    return [
        {
            "name": "popular-repo",
            "description": "A popular repository",
            "stargazers_count": 150,
            "language": "Python",
            "html_url": "https://github.com/testuser/popular-repo",
        },
        {
            "name": "small-repo",
            "description": "A small project",
            "stargazers_count": 3,
            "language": "JavaScript",
            "html_url": "https://github.com/testuser/small-repo",
        },
        {
            "name": "medium-repo",
            "description": None,
            "stargazers_count": 7,
            "language": "Python",
            "html_url": "https://github.com/testuser/medium-repo",
        },
        {
            "name": "no-lang-repo",
            "description": "Docs only",
            "stargazers_count": 0,
            "language": None,
            "html_url": "https://github.com/testuser/no-lang-repo",
        },
    ]


@pytest.fixture
def sample_search_commits_response():
    """Sample GitHub search commits response."""
    return {"total_count": 52, "incomplete_results": False, "items": []}


@pytest.fixture
def sample_search_prs_response():
    """Sample GitHub search PRs response."""
    return {"total_count": 10, "incomplete_results": False, "items": []}


@pytest.fixture
def sample_search_issues_response():
    """Sample GitHub search issues response."""
    return {"total_count": 5, "incomplete_results": False, "items": []}


@pytest.mark.asyncio
@respx.mock
async def test_extract_success(
    sample_repos_response,
    sample_search_commits_response,
    sample_search_prs_response,
    sample_search_issues_response,
):
    """Test successful full extraction."""
    respx.get(f"{GITHUB_API_BASE_URL}/users/testuser/repos").mock(
        return_value=httpx.Response(200, json=sample_repos_response)
    )
    respx.get(f"{GITHUB_API_BASE_URL}/search/commits").mock(
        return_value=httpx.Response(200, json=sample_search_commits_response)
    )
    respx.get(f"{GITHUB_API_BASE_URL}/search/issues").mock(
        return_value=httpx.Response(200, json=sample_search_prs_response)
    )
    respx.post(f"{GITHUB_API_BASE_URL}/graphql").mock(
        return_value=httpx.Response(200, json={"data": {"user": {"pinnedItems": {"nodes": []}}}})
    )

    extractor = GitHubExtractor(username="testuser")
    result = await extractor.extract()

    assert result.success is True
    assert result.data is not None
    assert result.error_message is None
    assert len(result.data.repos) == 4


@pytest.mark.asyncio
@respx.mock
async def test_extract_repos_languages_aggregation(sample_repos_response):
    """Test that language aggregation counts primary_language occurrences."""
    respx.get(f"{GITHUB_API_BASE_URL}/users/testuser/repos").mock(
        return_value=httpx.Response(200, json=sample_repos_response)
    )
    respx.get(f"{GITHUB_API_BASE_URL}/search/commits").mock(
        return_value=httpx.Response(200, json={"total_count": 0, "items": []})
    )
    respx.get(f"{GITHUB_API_BASE_URL}/search/issues").mock(
        return_value=httpx.Response(200, json={"total_count": 0, "items": []})
    )
    respx.post(f"{GITHUB_API_BASE_URL}/graphql").mock(
        return_value=httpx.Response(200, json={"data": {"user": {"pinnedItems": {"nodes": []}}}})
    )

    extractor = GitHubExtractor(username="testuser")
    result = await extractor.extract()

    assert result.success is True
    assert result.data is not None
    # Python appears in 2 repos, JavaScript in 1
    assert result.data.languages == {"Python": 2, "JavaScript": 1}


@pytest.mark.asyncio
@respx.mock
async def test_extract_notable_repos(sample_repos_response):
    """Test notable repo identification: stars >= 5 or is_pinned."""
    respx.get(f"{GITHUB_API_BASE_URL}/users/testuser/repos").mock(
        return_value=httpx.Response(200, json=sample_repos_response)
    )
    respx.get(f"{GITHUB_API_BASE_URL}/search/commits").mock(
        return_value=httpx.Response(200, json={"total_count": 0, "items": []})
    )
    respx.get(f"{GITHUB_API_BASE_URL}/search/issues").mock(
        return_value=httpx.Response(200, json={"total_count": 0, "items": []})
    )
    respx.post(f"{GITHUB_API_BASE_URL}/graphql").mock(
        return_value=httpx.Response(200, json={"data": {"user": {"pinnedItems": {"nodes": []}}}})
    )

    extractor = GitHubExtractor(username="testuser")
    result = await extractor.extract()

    assert result.success is True
    notable_names = [r.name for r in result.data.notable_repos]
    # popular-repo (150 stars) and medium-repo (7 stars) qualify
    assert "popular-repo" in notable_names
    assert "medium-repo" in notable_names
    # small-repo (3 stars) and no-lang-repo (0 stars) do not
    assert "small-repo" not in notable_names
    assert "no-lang-repo" not in notable_names


@pytest.mark.asyncio
@respx.mock
async def test_extract_404_profile():
    """Test handling of non-existent GitHub profile."""
    respx.get(f"{GITHUB_API_BASE_URL}/users/noone/repos").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    extractor = GitHubExtractor(username="noone")
    result = await extractor.extract()

    assert result.success is False
    assert result.data is None
    assert result.error_message is not None
    assert "private" in result.error_message.lower() or "not" in result.error_message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_extract_partial_failure_contributions(sample_repos_response):
    """Test partial extraction when contributions endpoint fails."""
    respx.get(f"{GITHUB_API_BASE_URL}/users/testuser/repos").mock(
        return_value=httpx.Response(200, json=sample_repos_response)
    )
    # Search APIs return 500
    respx.get(f"{GITHUB_API_BASE_URL}/search/commits").mock(
        return_value=httpx.Response(500, json={"message": "Internal Server Error"})
    )
    respx.get(f"{GITHUB_API_BASE_URL}/search/issues").mock(
        return_value=httpx.Response(500, json={"message": "Internal Server Error"})
    )
    respx.post(f"{GITHUB_API_BASE_URL}/graphql").mock(
        return_value=httpx.Response(200, json={"data": {"user": {"pinnedItems": {"nodes": []}}}})
    )

    extractor = GitHubExtractor(username="testuser")
    result = await extractor.extract()

    # Should still succeed with repos data available
    assert result.success is True
    assert result.data is not None
    assert len(result.data.repos) == 4


@pytest.mark.asyncio
@respx.mock
async def test_extract_repos_fail_returns_failure():
    """Test that failure to fetch repos results in overall failure."""
    respx.get(f"{GITHUB_API_BASE_URL}/users/testuser/repos").mock(
        return_value=httpx.Response(500, json={"message": "Error"})
    )
    respx.get(f"{GITHUB_API_BASE_URL}/search/commits").mock(
        return_value=httpx.Response(200, json={"total_count": 0, "items": []})
    )
    respx.get(f"{GITHUB_API_BASE_URL}/search/issues").mock(
        return_value=httpx.Response(200, json={"total_count": 0, "items": []})
    )
    respx.post(f"{GITHUB_API_BASE_URL}/graphql").mock(
        return_value=httpx.Response(200, json={"data": {"user": {"pinnedItems": {"nodes": []}}}})
    )

    extractor = GitHubExtractor(username="testuser")
    result = await extractor.extract()

    # When repos fail with 500 (not 404/403), it's added to unavailable
    # and since repos is the primary data source, result should indicate failure
    assert result.success is False
    assert result.data is None
    assert "repos" in result.unavailable_categories


@pytest.mark.asyncio
@respx.mock
async def test_extract_pinned_repos_from_graphql(sample_repos_response):
    """Test that pinned repos are fetched via GraphQL and marked in repos list."""
    respx.get(f"{GITHUB_API_BASE_URL}/users/testuser/repos").mock(
        return_value=httpx.Response(200, json=sample_repos_response)
    )
    respx.get(f"{GITHUB_API_BASE_URL}/search/commits").mock(
        return_value=httpx.Response(200, json={"total_count": 0, "items": []})
    )
    respx.get(f"{GITHUB_API_BASE_URL}/search/issues").mock(
        return_value=httpx.Response(200, json={"total_count": 0, "items": []})
    )
    # GraphQL returns pinned repos
    graphql_response = {
        "data": {
            "user": {
                "pinnedItems": {
                    "nodes": [
                        {
                            "name": "small-repo",
                            "description": "A pinned project",
                            "stargazerCount": 3,
                            "primaryLanguage": {"name": "JavaScript"},
                            "url": "https://github.com/testuser/small-repo",
                        }
                    ]
                }
            }
        }
    }
    respx.post(f"{GITHUB_API_BASE_URL}/graphql").mock(
        return_value=httpx.Response(200, json=graphql_response)
    )

    extractor = GitHubExtractor(username="testuser")
    result = await extractor.extract()

    assert result.success is True
    assert len(result.data.pinned_repos) == 1
    assert result.data.pinned_repos[0].name == "small-repo"
    assert result.data.pinned_repos[0].is_pinned is True

    # Check that small-repo is marked as pinned in repos list too
    small_repo = next(r for r in result.data.repos if r.name == "small-repo")
    assert small_repo.is_pinned is True

    # Now small-repo (pinned) should appear in notable repos
    notable_names = [r.name for r in result.data.notable_repos]
    assert "small-repo" in notable_names


@pytest.mark.asyncio
@respx.mock
async def test_extract_private_profile_403():
    """Test handling of private (403) GitHub profile."""
    respx.get(f"{GITHUB_API_BASE_URL}/users/private_user/repos").mock(
        return_value=httpx.Response(403, json={"message": "Forbidden"})
    )

    extractor = GitHubExtractor(username="private_user")
    result = await extractor.extract()

    assert result.success is False
    assert result.data is None
    assert result.error_message is not None


def test_identify_notable_repos():
    """Test _identify_notable_repos filtering logic."""
    repos = [
        GitHubRepo(name="high-stars", description=None, stars=10, primary_language="Python"),
        GitHubRepo(name="pinned-low", description=None, stars=2, primary_language="Go", is_pinned=True),
        GitHubRepo(name="exact-five", description=None, stars=5, primary_language="Rust"),
        GitHubRepo(name="below-threshold", description=None, stars=4, primary_language="Java"),
        GitHubRepo(name="zero-stars", description=None, stars=0, primary_language=None),
    ]

    extractor = GitHubExtractor(username="test")
    notable = extractor._identify_notable_repos(repos)

    notable_names = [r.name for r in notable]
    assert "high-stars" in notable_names
    assert "pinned-low" in notable_names  # pinned, even though low stars
    assert "exact-five" in notable_names  # exactly 5 stars
    assert "below-threshold" not in notable_names
    assert "zero-stars" not in notable_names


def test_compute_languages():
    """Test language aggregation across repos."""
    repos = [
        GitHubRepo(name="r1", description=None, stars=0, primary_language="Python"),
        GitHubRepo(name="r2", description=None, stars=0, primary_language="Python"),
        GitHubRepo(name="r3", description=None, stars=0, primary_language="JavaScript"),
        GitHubRepo(name="r4", description=None, stars=0, primary_language=None),
        GitHubRepo(name="r5", description=None, stars=0, primary_language="Rust"),
    ]

    extractor = GitHubExtractor(username="test")
    langs = extractor._compute_languages(repos)

    assert langs == {"Python": 2, "JavaScript": 1, "Rust": 1}


def test_compute_languages_empty():
    """Test language aggregation with no repos."""
    extractor = GitHubExtractor(username="test")
    langs = extractor._compute_languages([])
    assert langs == {}
