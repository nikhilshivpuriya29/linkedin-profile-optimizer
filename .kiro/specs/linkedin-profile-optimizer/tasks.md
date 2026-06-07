# Implementation Plan: LinkedIn Profile Optimizer

## Overview

This implementation plan breaks down the LinkedIn Profile Optimizer multi-agent pipeline into incremental coding tasks. The system is built bottom-up: data models and persistence first, then external service adapters, then agents, then orchestration and CLI wiring. Each task builds on the previous and ends with integrated, testable code.

## Tasks

- [x] 1. Project scaffolding and core data models
  - [x] 1.1 Set up project structure, dependencies, and configuration
    - Create directory structure: `src/linkedin_optimizer/`, `tests/unit/`, `tests/property/`, `tests/integration/`
    - Create `pyproject.toml` with dependencies: `httpx`, `apscheduler`, `hypothesis`, `pytest`, `pytest-asyncio`, `rich` (CLI formatting), `pydantic` (optional validation)
    - Create `src/linkedin_optimizer/__init__.py`, `src/linkedin_optimizer/models.py`, `src/linkedin_optimizer/config.py`
    - Create `data/config.json` with the configuration schema from the design
    - Set up `pytest.ini` or `pyproject.toml` test configuration with markers: `property`, `integration`, `slow`
    - _Requirements: 6.1, 6.2, 9.1_

  - [x] 1.2 Implement core data models and enums
    - Implement all dataclasses in `models.py`: `ProfileData`, `ExtractionResult`, `GitHubRepo`, `GitHubContributions`, `GitHubData`, `GitHubExtractionResult`, `FactorScore`, `SectionScore`, `Recommendation`, `SectionInsight`, `OptimizationReport`, `HeadlineSuggestion`, `AboutSuggestion`, `ExperienceSuggestion`, `PostIdea`, `BannerSuggestion`, `ContentPackage`, `ApprovalItem`, `ApprovalSession`, `EngagementSnapshot`, `EngagementComparison`, `EngagementReport`, `RunMetadata`
    - Implement enums: `PipelineStatus`, `ScheduleInterval`, `Priority`, `ApprovalStatus`
    - Implement `PipelineConfig` and `HFModelConfig` dataclasses
    - Add JSON serialization/deserialization methods (`to_dict()` / `from_dict()`) on all data models
    - _Requirements: 1.7, 2.1, 3.1, 4.1, 5.1, 8.1_

  - [x] 1.3 Write property tests for data model serialization (Properties 1-2)
    - **Property 1: Profile data parsing preserves all sections** — generate arbitrary ProfileData, verify no fields are lost during parse
    - **Property 2: Profile data serialization round-trip** — serialize to JSON and deserialize back, assert equivalence
    - **Validates: Requirements 1.2, 1.3, 1.7**

- [x] 2. Data persistence layer
  - [x] 2.1 Implement the DataStore class (`persistence/data_store.py`)
    - Implement `DataStore.__init__(data_dir)` that creates the file structure: `profiles/`, `reports/`, `content/`, `approvals/`, `engagement/`, `runs/`
    - Implement `save_profile_snapshot`, `save_optimization_report`, `save_content_package`, `save_approval_session`, `save_run_metadata`, `save_engagement_snapshot`
    - Implement `load_approval_session`, `load_engagement_history`, `load_latest_report`, `get_run_history`
    - Each save method writes a JSON file to the appropriate subdirectory with the naming convention from the design
    - Handle file I/O errors gracefully with logging
    - _Requirements: 1.7, 6.5, 8.1_

  - [x] 2.2 Write unit tests for DataStore
    - Test save/load round-trips for each data type
    - Test file creation in correct directories
    - Test graceful handling of missing files and corrupted JSON
    - _Requirements: 1.7, 6.5_

- [x] 3. Hugging Face client with retry and fallback
  - [x] 3.1 Implement HuggingFaceClient (`integrations/hf_client.py`)
    - Implement `HuggingFaceClient.__init__(config: HFModelConfig)` with httpx async client
    - Implement `generate(prompt, system_context, max_tokens, temperature)` with full retry + fallback logic
    - Implement `_call_model(model_id, prompt, ...)` making actual HTTP POST to HF Inference API
    - Implement `_retry_with_backoff(model_id, prompt, ...)` with exponential backoff: 2s, 4s, 8s, max 3 attempts
    - Implement `_should_use_fallback(error)`: return True for non-timeout errors (service down, model not found, API errors); return False for timeouts (cancel without fallback per Req 9.5)
    - Handle 30-second timeout per request: cancel and attempt fallback model for non-timeout errors only
    - Maintain conversation context list for consistent tone across sections within a pipeline run
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [x] 3.2 Write property tests for retry and fallback logic (Property 4, 24)
    - **Property 4: Retry logic respects attempt limits and backoff timing** — simulate N failures, verify retry count ≤ max_retries and delays double from 2s
    - **Property 24: Model fallback on timeout** — simulate timeout, verify request is cancelled and fallback is attempted for non-timeout errors
    - **Validates: Requirements 1.5, 9.3, 9.4, 9.5**

  - [x] 3.3 Write unit tests for HuggingFaceClient
    - Test successful generation with mocked HTTP responses
    - Test retry behavior with transient failures
    - Test fallback model activation on non-timeout errors
    - Test timeout cancellation (no fallback for timeouts per Req 9.5)
    - Test conversation context accumulation
    - _Requirements: 9.1, 9.3, 9.4, 9.5, 9.6_

- [x] 4. Checkpoint - Verify foundation layers
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. LinkedIn MCP client adapter
  - [x] 5.1 Implement LinkedInMCPClient (`scrapers/linkedin_mcp_client.py`)
    - Implement `LinkedInMCPClient.__init__(mcp_server_config)` that configures connection to the `linkedin-mcp-server` (stickerdaniel) via uvx
    - Implement `get_person_profile(profile_url)` calling the MCP tool `get_person_profile`
    - Implement `get_my_profile()` calling the MCP tool `get_my_profile`
    - Implement `get_feed(count)` calling the MCP tool `get_feed` for post data
    - Handle MCP communication errors and transform to standard exceptions
    - _Requirements: 1.1, 1.2_

  - [x] 5.2 Implement ProfileScraper (`scrapers/profile_scraper.py`)
    - Implement `ProfileScraper.__init__(mcp_client, max_retries=3)`
    - Implement `extract(profile_url)` orchestrating full profile extraction
    - Implement `_parse_profile_response(raw_data)` mapping MCP response to `ProfileData` dataclass
    - Implement `_retry_with_backoff(operation, max_attempts=3)` with exponential backoff from 2 seconds
    - Handle partial extraction: if some sections fail after retries, populate `failed_sections` list
    - Handle total failure: return `ExtractionResult(success=False, profile_data=None, error_message=...)`
    - Validate profile URL format before attempting extraction
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [x] 5.3 Write property tests for extraction error handling (Properties 3, 5)
    - **Property 3: Extraction error handling — no partial data on total failure** — for invalid URLs, verify success=False, profile_data=None, error_message non-empty
    - **Property 5: Partial extraction correctly identifies failed sections** — simulate partial failures, verify failed_sections lists exactly the failed ones
    - **Validates: Requirements 1.4, 1.6**

- [x] 6. GitHub extractor
  - [x] 6.1 Implement GitHubExtractor (`scrapers/github_extractor.py`)
    - Implement `GitHubExtractor.__init__(username, timeout=15)` with httpx async client
    - Implement `extract()` orchestrating all GitHub data extraction within 30 seconds
    - Implement `_get_repos()` calling `GET /users/{username}/repos` (sorted by stars)
    - Implement `_get_contributions()` aggregating commit count, PRs, issues over 12 months
    - Implement `_get_pinned_repos()` via GitHub GraphQL API or pinned repos endpoint
    - Implement `_identify_notable_repos(repos)` filtering repos with ≥5 stars OR is_pinned=True
    - Compute `languages` dict by aggregating primary_language across repos
    - Handle timeouts (15s connection timeout), HTTP errors, and private profiles gracefully
    - Return `GitHubExtractionResult` with partial=True and unavailable_categories when some data fails
    - _Requirements: 7.1, 7.2, 7.4, 7.5_

  - [x] 6.2 Write property tests for GitHub filtering (Properties 14, 16)
    - **Property 14: Notable repository identification** — generate lists of repos with varying star counts and pinned status, verify notable_repos contains exactly those with stars≥5 OR is_pinned=True
    - **Property 16: Graceful degradation when GitHub is unavailable** — simulate GitHub failures, verify pipeline can continue with LinkedIn-only data
    - **Validates: Requirements 7.2, 7.4**

- [x] 7. Analyzer Agent
  - [x] 7.1 Implement AnalyzerAgent (`agents/analyzer_agent.py`)
    - Implement `AnalyzerAgent.__init__(model_id, fallback_model_id, hf_client)`
    - Implement `analyze(profile, github)` running full analysis pipeline
    - Implement `score_section(section_name, content)` with section-specific scoring prompts
    - Implement `_build_scoring_prompt(section_name, content)` constructing prompts per the scoring criteria in Req 2.2-2.7
    - Implement `_calculate_weighted_average(factors)` computing weighted average excluding unavailable factors
    - Handle empty/missing sections: assign score=0, set missing=True (Req 2.8)
    - Exclude factors when required data is unavailable (Req 2.9)
    - Implement `generate_insights(scores, profile)` producing strengths, weaknesses, and recommendations
    - Ensure at least 1 strength, 1 weakness, 1 recommendation per section; at least 2 recommendations if score < 70
    - Assign priority (High/Medium/Low) to each recommendation and order by priority descending
    - Include at least 1 LinkedIn optimization guideline reference per recommendation
    - Incorporate GitHub data summary into the report when available
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 7.2 Write property tests for scoring logic (Properties 6, 7, 8)
    - **Property 6: Section scoring produces valid weighted averages** — generate factor scores 0-100, verify result is 0-100 and mathematically correct
    - **Property 7: Empty sections receive zero score with missing flag** — pass empty content, verify score=0 and missing=True
    - **Property 8: Engagement rate calculation correctness** — generate post counts and follower counts, verify engagement rate formula
    - **Validates: Requirements 2.1, 2.6, 2.8, 2.9**

  - [x] 7.3 Write property tests for report structure (Properties 9, 10, 11)
    - **Property 9: Optimization report structural completeness** — verify ≥1 strength, ≥1 weakness, ≥1 recommendation per section; ≥2 recommendations if score < 70
    - **Property 10: Recommendations are ordered by priority** — verify High before Medium before Low
    - **Property 11: Every recommendation cites a guideline** — verify guideline_reference is non-empty for all recommendations
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4**

- [x] 8. Content Creator Agent
  - [x] 8.1 Implement ContentCreatorAgent (`agents/content_creator_agent.py`)
    - Implement `ContentCreatorAgent.__init__(model_id, fallback_model_id, hf_client)`
    - Implement `generate(report, profile, github)` generating content for sections scoring < 70
    - Implement `generate_headline(profile, insights)` — optimized headline ≤220 chars, ≥2 keywords, value proposition
    - Implement `generate_about(profile, insights)` — optimized about ≤2600 chars, ≥3 keywords, narrative hook, CTA
    - Implement `generate_experience(profile, insights, github)` — action verbs, metrics, ≤2000 chars/position; incorporate up to 5 GitHub achievements
    - Implement `generate_post_ideas(profile, insights)` — ≥3 post ideas with topic, format, outline (≥2 sentences each)
    - Implement `generate_banner(profile, insights)` — dimensions, ≤5 colors, tagline ≤10 words
    - Implement `revise_suggestion(original, feedback, section_name)` — revise based on user feedback (max 500 chars)
    - Handle missing metrics in experience: use qualitative impact statements and flag for user to add numbers
    - Base all content on user's existing language and domain
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 7.3_

  - [x] 8.2 Write property tests for content constraints (Properties 12, 13, 15)
    - **Property 12: Content generation targets correct sections** — generate reports with various scores, verify content only for sections < 70
    - **Property 13: Generated content respects character and structural constraints** — verify headline ≤220 chars, about ≤2600 chars, ≥3 post ideas, banner ≤5 colors and tagline ≤10 words
    - **Property 15: GitHub integration limit** — verify at most 5 GitHub achievements in content
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 7.3**

- [x] 9. Checkpoint - Verify agents and extractors
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Approval Workflow
  - [x] 10.1 Implement ApprovalWorkflow (`approval/workflow.py`)
    - Implement `ApprovalWorkflow.__init__(data_store, notification_service, content_creator_agent)`
    - Implement `submit_for_review(content_package, current_profile)` creating `ApprovalSession` with side-by-side comparisons
    - Implement `approve(item_id)` — transition to approved status, trigger apply within 30 seconds
    - Implement `reject(item_id, reason)` — transition to rejected, record reason (≤500 chars)
    - Implement `request_modification(item_id, feedback)` — validate feedback ≤500 chars, trigger `revise_suggestion`, return revised content
    - Implement `get_pending_items()` — return items with status=PENDING and not expired
    - Implement `expire_stale_items()` — expire items older than 7 days, notify user
    - Implement `notify_user(session)` — send notification within 5 minutes of generation
    - Set `expires_at` = `created_at` + 7 days for each approval item
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9_

  - [x] 10.2 Implement CLI approval interface (`approval/cli_interface.py`)
    - Implement `CLIApprovalInterface` using `rich` library for terminal formatting
    - Display side-by-side diff of current vs proposed content (colored)
    - Implement interactive menu: [A]pprove, [R]eject, [M]odify, [S]kip, [Q]uit
    - Implement feedback input prompt for modify/reject actions (validate ≤500 chars)
    - Display summary of pending items count and session info
    - List all pending approval sessions with creation dates
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 5.6_

  - [x] 10.3 Write property tests for approval logic (Properties 19, 20, 21)
    - **Property 19: Approval item independence** — perform action on one item, verify other items unchanged
    - **Property 20: Approval expiration after 7 days** — set created_at in past, verify expired status
    - **Property 21: User input validation enforces 500 character limit** — generate strings of varying lengths, verify acceptance/rejection at boundary
    - **Validates: Requirements 5.3, 5.5, 5.6, 5.7**

- [x] 11. Pipeline Orchestrator and scheduler
  - [x] 11.1 Implement PipelineOrchestrator (`orchestrator.py`)
    - Implement `PipelineOrchestrator.__init__(config: PipelineConfig)` initializing all components
    - Implement `execute()` running the full pipeline in strict order: ProfileScraper → AnalyzerAgent → ContentCreatorAgent → ApprovalWorkflow
    - Enforce stage ordering: halt if any stage fails, log error, do not invoke subsequent stages
    - Implement `trigger_on_demand()` — execute immediately if not already running, otherwise queue
    - Implement `enqueue_run()` — queue concurrent triggers, return queue position
    - Implement `get_status()` — return current pipeline status
    - Log `RunMetadata` (start_time, end_time, status, summary) after each run; only mark completed after metadata is logged
    - Handle GitHub unavailability gracefully: continue with LinkedIn-only if GitHub fails
    - _Requirements: 6.1, 6.3, 6.4, 6.5, 6.7, 7.4_

  - [x] 11.2 Implement scheduler (`scheduler.py`)
    - Implement `PipelineScheduler` using APScheduler for cron-based scheduling
    - Support `schedule(interval)` for daily/weekly/monthly intervals
    - Implement `pause()` and `resume()` for scheduled execution control
    - Prevent concurrent execution: if pipeline is running when schedule triggers, queue the run
    - _Requirements: 6.2, 6.6, 6.7_

  - [x] 11.3 Write property tests for pipeline ordering and concurrency (Properties 17, 18)
    - **Property 17: Pipeline stage ordering and error propagation** — verify stages execute in order, failure halts subsequent stages
    - **Property 18: Run queue serialization** — simulate concurrent triggers, verify only one executes at a time
    - **Validates: Requirements 6.3, 6.4, 6.5, 6.7**

- [x] 12. Engagement Tracker
  - [x] 12.1 Implement EngagementTracker (`tracking/engagement_tracker.py`)
    - Implement `EngagementTracker.__init__(mcp_client, data_store)`
    - Implement `record_baseline(change_id, section_name)` — snapshot profile_views, connection_requests, post engagement at time of change application
    - Implement `collect_metrics(change_id)` — collect current engagement metrics
    - Implement `generate_comparison_report(change_id, days_elapsed=7)` — compute absolute and percentage changes; set percentage_change to 0.0 when baseline is zero
    - Implement `get_top_performing_sections()` — rank sections by historical metric improvement descending
    - Implement `retry_collection(change_id, max_retries=3)` — retry over 6 hours if metrics unavailable, log data gaps
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 12.2 Write property tests for engagement calculations (Properties 22, 23)
    - **Property 22: Engagement comparison calculation correctness** — verify absolute_change = current - baseline, percentage_change = ((current - baseline) / baseline × 100) when baseline > 0, percentage_change = 0.0 when baseline = 0
    - **Property 23: Section prioritization by historical performance** — generate engagement reports, verify sections ranked by descending improvement
    - **Validates: Requirements 8.3, 8.4**

- [x] 13. Checkpoint - Full system integration
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. CLI entry point and wiring
  - [x] 14.1 Implement CLI entry point (`cli.py`)
    - Implement `main()` CLI using argparse or click with subcommands: `run`, `schedule`, `pause`, `resume`, `status`, `review`, `history`, `config`
    - `run` — trigger on-demand pipeline execution
    - `schedule` — configure scheduled interval (daily/weekly/monthly)
    - `pause` / `resume` — pause/resume scheduled runs
    - `status` — show current pipeline status and last run summary
    - `review` — launch CLI approval interface for pending items
    - `history` — show recent run history and engagement reports
    - `config` — display or update configuration
    - Wire all components together: load config, initialize clients, orchestrator, scheduler
    - Add `__main__.py` for `python -m linkedin_optimizer` invocation
    - _Requirements: 6.1, 6.2, 6.6, 5.1_

  - [x] 14.2 Write integration tests for full pipeline
    - Test full pipeline execution with mocked MCP, GitHub API, and HF responses
    - Test scheduler start/pause/resume lifecycle
    - Test CLI command parsing and dispatch
    - Test data persistence across pipeline runs
    - Test approval workflow end-to-end with mocked user input
    - _Requirements: 6.1, 6.2, 6.3, 6.5, 5.1_

- [x] 15. Final checkpoint - All tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the 24 universal correctness properties from the design
- Unit tests validate specific examples and edge cases
- All external services (LinkedIn MCP, GitHub API, HuggingFace) are accessed through adapter classes for testability
- The project uses `pytest` + `hypothesis` for testing, `httpx` for async HTTP, `rich` for CLI formatting, and `apscheduler` for scheduling

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "2.1"] },
    { "id": 3, "tasks": ["2.2", "3.1"] },
    { "id": 4, "tasks": ["3.2", "3.3", "5.1"] },
    { "id": 5, "tasks": ["5.2", "6.1"] },
    { "id": 6, "tasks": ["5.3", "6.2", "7.1"] },
    { "id": 7, "tasks": ["7.2", "7.3", "8.1"] },
    { "id": 8, "tasks": ["8.2", "10.1"] },
    { "id": 9, "tasks": ["10.2", "10.3", "11.1"] },
    { "id": 10, "tasks": ["11.2", "12.1"] },
    { "id": 11, "tasks": ["11.3", "12.2"] },
    { "id": 12, "tasks": ["14.1"] },
    { "id": 13, "tasks": ["14.2"] }
  ]
}
```
