"""Run the LinkedIn Profile Optimizer using resume PDF as input.

Bypasses LinkedIn OAuth by extracting profile data from the resume PDF.
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from linkedin_optimizer.models import (
    ProfileData,
    PipelineStatus,
    OptimizationReport,
    ContentPackage,
)
from linkedin_optimizer.config import HFModelConfig, load_config
from linkedin_optimizer.integrations.hf_client import HuggingFaceClient
from linkedin_optimizer.agents.analyzer_agent import AnalyzerAgent
from linkedin_optimizer.agents.content_creator_agent import ContentCreatorAgent
from linkedin_optimizer.persistence.data_store import DataStore
from linkedin_optimizer.scrapers.github_extractor import GitHubExtractor

console = Console()


def build_profile_from_resume() -> ProfileData:
    """Build a ProfileData object from the parsed resume content."""
    return ProfileData(
        headline="Salesforce Developer & DevOps Engineer at Gentrack Global",
        about=(
            "Salesforce Developer and DevOps Engineer with 4+ years of total experience, "
            "including nearly 3 years of hands-on Salesforce development across enterprise "
            "and product environments. Strong expertise in Apex (Triggers, Batch, Queueable), "
            "Lightning Web Components (LWC), Flows, and SOQL optimization. Proven experience "
            "supporting high-usage production orgs, building bulkified backend logic, and "
            "implementing secure REST-based integrations. Skilled in troubleshooting complex "
            "automation failures, optimizing performance bottlenecks, and delivering reliable "
            "deployments using SFDX and Git-based workflows."
        ),
        experience=[
            {
                "title": "Salesforce DevOps Engineer",
                "company": "Gentrack Global",
                "duration": "July 2025 – Present",
                "location": "Pune, India",
                "description": (
                    "• Managed Salesforce deployments across multiple environments using Gearset and SFDX\n"
                    "• Automated 100+ manual deployment and validation steps, reducing post-deployment effort by 70%\n"
                    "• Supported high-usage production org by troubleshooting Apex failures, Flow errors\n"
                    "• Performed metadata comparisons, dependency validation, and rollback management\n"
                    "• Collaborated with developers and QA teams for bulk-safe deployments"
                ),
            },
            {
                "title": "Salesforce Developer",
                "company": "Cloud SynApps Inc.",
                "duration": "July 2023 – July 2025",
                "location": "Pune, India (Hybrid)",
                "description": (
                    "• Designed and developed scalable Salesforce solutions using Apex, LWC, and Flows\n"
                    "• Built and optimized bulkified Apex classes handling large datasets\n"
                    "• Developed REST-based integrations with external systems using OAuth2.0\n"
                    "• Authored Apex test classes achieving 90%+ coverage\n"
                    "• Diagnosed and resolved production issues including automation failures\n"
                    "• Designed custom objects, relationships, validation rules"
                ),
            },
            {
                "title": "MEVN Stack Specialist",
                "company": "Fynd Academy",
                "duration": "Jan 2023 – Jul 2023",
                "location": "Remote",
                "description": (
                    "• Developed full-stack applications using Vue.js and Node.js, improving API response times by 60%\n"
                    "• Designed RESTful microservices handling 10,000+ daily requests with 99.9% uptime"
                ),
            },
            {
                "title": "Java Full Stack Intern",
                "company": "Global Quest Technologies",
                "duration": "Jul 2022 – Jan 2023",
                "location": "Remote",
                "description": (
                    "• Built modular Java-based applications and automated ETL workflows\n"
                    "• Reduced manual processing time by 50%"
                ),
            },
        ],
        skills=[
            {"name": "Apex", "endorsements": 0},
            {"name": "Lightning Web Components (LWC)", "endorsements": 0},
            {"name": "Salesforce DX", "endorsements": 0},
            {"name": "REST APIs", "endorsements": 0},
            {"name": "Git", "endorsements": 0},
            {"name": "CI/CD Pipelines", "endorsements": 0},
            {"name": "SOQL", "endorsements": 0},
            {"name": "JavaScript", "endorsements": 0},
            {"name": "OAuth2.0", "endorsements": 0},
            {"name": "Gearset", "endorsements": 0},
        ],
        endorsements=[],
        posts=[],
        banner_url=None,
        photo_url=None,
        education=[
            {
                "school": "Samrat Ashok Technological Institute, Vidisha",
                "degree": "B.Tech in Computer Science & Engineering",
                "years": "2019 – 2023",
            }
        ],
        certifications=[
            {"name": "Salesforce Certified AI Specialist"},
            {"name": "Salesforce Certified AI Associate"},
            {"name": "Salesforce Certified Platform Developer I"},
            {"name": "Salesforce Certified JavaScript Developer I"},
            {"name": "Salesforce Certified OmniStudio Developer"},
            {"name": "Salesforce Certified Administrator"},
            {"name": "Gearset Salesforce DevOps Fundamentals"},
            {"name": "Gearset Salesforce DevOps Leadership"},
        ],
        follower_count=0,
        connection_count=0,
        profile_views=None,
    )


async def main():
    console.print("\n[bold blue]LinkedIn Profile Optimizer — Resume Mode[/bold blue]\n")

    # Step 1: Build profile from resume
    console.print("[bold]Stage 1:[/bold] Loading profile from resume PDF...")
    profile = build_profile_from_resume()
    console.print(f"  ✓ Profile loaded: {profile.headline}")
    console.print(f"  ✓ {len(profile.experience)} experience entries, {len(profile.skills)} skills, {len(profile.certifications)} certifications\n")

    # Step 2: GitHub extraction (with SSL bypass for corporate networks)
    console.print("[bold]Stage 2:[/bold] Extracting GitHub data...")
    github_data = None
    try:
        import httpx as _httpx
        # Monkey-patch GitHubExtractor to use verify=False for corporate proxies
        original_extract = GitHubExtractor.extract
        async def _patched_extract(self):
            try:
                import asyncio
                async with _httpx.AsyncClient(
                    base_url="https://api.github.com",
                    timeout=_httpx.Timeout(self.timeout, connect=self.timeout),
                    headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "linkedin-optimizer"},
                    verify=False,
                ) as client:
                    self._client = client
                    return await asyncio.wait_for(self._extract_all(), timeout=30.0)
            except Exception as e:
                from linkedin_optimizer.models import GitHubExtractionResult
                return GitHubExtractionResult(success=False, data=None, error_message=str(e))
        
        GitHubExtractor.extract = _patched_extract
        extractor = GitHubExtractor(username="nikhilshivpuriya29", timeout=15)
        result = await extractor.extract()
        GitHubExtractor.extract = original_extract  # restore
        
        if result.success and result.data:
            github_data = result.data
            console.print(f"  ✓ GitHub: {len(result.data.repos)} repos, {len(result.data.notable_repos)} notable")
            console.print(f"  ✓ Languages: {dict(list(result.data.languages.items())[:5])}")
        else:
            console.print(f"  ⚠ GitHub extraction failed: {result.error_message}")
    except Exception as e:
        console.print(f"  ⚠ GitHub unavailable: {e}")
    console.print()

    # Step 3: Analyze profile (using heuristic scoring — no HF API needed)
    console.print("[bold]Stage 3:[/bold] Analyzing profile sections...")
    analyzer = AnalyzerAgent(
        model_id="mistralai/Mistral-7B-Instruct-v0.3",
        fallback_model_id="google/gemma-2-9b-it",
        hf_client=None,  # Use heuristic scoring (no API call)
    )
    report = await analyzer.analyze(profile, github_data)

    console.print(f"  ✓ Overall score: [bold]{report.overall_score}/100[/bold]")
    console.print()

    # Display section scores
    score_table = Table(title="Section Scores", show_lines=True)
    score_table.add_column("Section", style="cyan")
    score_table.add_column("Score", justify="center")
    score_table.add_column("Status")

    for section in report.sections:
        score = section.overall_score
        if section.missing:
            status = "[dim]Missing[/dim]"
        elif score >= 70:
            status = "[green]Good[/green]"
        elif score >= 50:
            status = "[yellow]Needs Work[/yellow]"
        else:
            status = "[red]Low[/red]"
        score_table.add_row(section.section_name, str(score), status)

    console.print(score_table)
    console.print()

    # Display insights
    console.print("[bold]Key Recommendations:[/bold]\n")
    for insight in report.insights:
        if insight.recommendations:
            for rec in insight.recommendations[:2]:
                priority_color = {"high": "red", "medium": "yellow", "low": "green"}
                color = priority_color.get(rec.priority.value, "white")
                console.print(f"  [{color}]●[/{color}] [{color}]{rec.priority.value.upper()}[/{color}] — {rec.modification}")
    console.print()

    # Step 4: Generate content
    console.print("[bold]Stage 4:[/bold] Generating optimized content...")
    content_creator = ContentCreatorAgent(
        model_id="mistralai/Mistral-7B-Instruct-v0.3",
        fallback_model_id="google/gemma-2-9b-it",
        hf_client=None,  # Use template-based generation (no API call)
    )
    content = await content_creator.generate(report, profile, github_data)
    console.print("  ✓ Content package generated\n")

    # Display generated content
    if content.headline:
        console.print(Panel(
            content.headline.text,
            title="[bold green]Suggested Headline[/bold green]",
            border_style="green",
        ))
        console.print()

    if content.about:
        console.print(Panel(
            content.about.text[:500] + ("..." if len(content.about.text) > 500 else ""),
            title="[bold green]Suggested About Section[/bold green]",
            border_style="green",
        ))
        console.print()

    if content.post_ideas:
        console.print("[bold]Post Ideas:[/bold]")
        for i, idea in enumerate(content.post_ideas, 1):
            console.print(f"  {i}. [cyan]{idea.topic}[/cyan] ({idea.format})")
            console.print(f"     {idea.content_outline[:100]}...")
        console.print()

    # Save results
    data_store = DataStore("./data")
    run_id = f"run_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    data_store.save_profile_snapshot(profile, run_id)
    data_store.save_optimization_report(report, run_id)
    data_store.save_content_package(content, run_id)
    console.print(f"[dim]Results saved to ./data/ (run_id: {run_id})[/dim]")

    console.print("\n[bold green]✓ Pipeline complete![/bold green]\n")


if __name__ == "__main__":
    asyncio.run(main())
