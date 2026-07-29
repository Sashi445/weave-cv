from weave_cv.agents.cv_analyzer import make_cv_analyzer_agent
from weave_cv.agents.jd_analyzer import make_jd_analyzer_agent
from weave_cv.agents.resume_tailor_agent import tailor
from weave_cv.agents.orchestrator_agent import gather_inputs, run_resume_pipeline, stream_resume_pipeline
from dotenv import load_dotenv
from langchain.messages import HumanMessage
from weave_cv.schemas.cv_analysis import CVProfile
from weave_cv.services.cv_diff import diff_cv_profiles
import asyncio
import time

load_dotenv()

# can be used to create multiple agents
async def test_cv_analyzer_agent():
    cv_analyzer_agent = await make_cv_analyzer_agent()
    response = await cv_analyzer_agent.ainvoke({
        "messages": [
            HumanMessage(
                content="Analyze my resume located at " \
                "'/Users/sashi/my-stuff/agentic-ai/weave-cv/tests/sashidharmotteresume.tex'"
            )
        ]
    })

    from pprint import pprint
    pprint(response["messages"][-1].content)

async def test_jd_analyzer_agent():
    jd_analyzer_agent = await make_jd_analyzer_agent()
    response = await jd_analyzer_agent.ainvoke({
        "messages": [
            HumanMessage(
                content="Analyze this job posting for me - 'https://job-boards.greenhouse.io/tailscale/jobs/4710703005' "
            )
        ]
    })

def print_cv_profile_delta(original: CVProfile, tailored: CVProfile) -> None:
    """Print a structural diff between an original and tailored CVProfile.
    Thin wrapper around services/cv_diff.py, which is also what
    agents/orchestrator_agent.py's verify() uses for the deterministic
    half of verification — this function exists for human-readable
    debugging, not as a separate implementation of the diff itself."""
    print(diff_cv_profiles(original, tailored).render())


async def test_resume_tailor_agent():
    job_url = "https://job-boards.greenhouse.io/tailscale/jobs/4710703005"
    cv_path = "/Users/sashi/my-stuff/agentic-ai/weave-cv/tests/sashidharmotteresume.tex"

    jd_profile, original_cv = await gather_inputs(job_url, cv_path)
    tailored_cv = await tailor(jd_profile, original_cv)

    from pprint import pprint
    print("=== ORIGINAL CVProfile ===")
    pprint(original_cv)
    print("=== TAILORED CVProfile ===")
    pprint(tailored_cv)

    print_cv_profile_delta(original_cv, tailored_cv)

    return original_cv, tailored_cv


async def test_orchestrator_pipeline():
    """Runs the full pipeline skeleton end to end. verify() and generate()
    are still stubs (NotImplementedError), so this is expected to stop at
    the verify stage — the point of this test is to confirm that failure
    is cleanly attributed via state["failed_stage"] instead of surfacing
    as a raw stack trace."""
    state = await run_resume_pipeline(
        job_url="https://job-boards.greenhouse.io/tailscale/jobs/4710703005",
        cv_path="/Users/sashi/my-stuff/agentic-ai/weave-cv/tests/sashidharmotteresume.tex",
        output_dir="/Users/sashi/my-stuff/agentic-ai/weave-cv/tests/output",
    )

    print(f"failed_stage: {state.get('failed_stage')}")
    print(f"error: {state.get('error')}")
    print(f"verification_attempts: {state.get('verification_attempts')}")
    return state


_STAGE_LABELS = {
    "gather_inputs": "Scraping job posting & analyzing resume",
    "tailor": "Tailoring resume",
    "verify": "Verifying tailored resume",
    "generate": "Generating PDF",
}


async def run_full_pipeline_with_progress():
    """Runs the whole pipeline once from scratch with live stage-by-stage
    progress (same streaming source cli.py uses) and reports total wall
    time — with MAX_VERIFICATION_ATTEMPTS set to 1 in orchestrator_agent.py,
    this is a single pass with no retries, so the elapsed time reflects
    one real run's cost, not however many retries happened to occur."""
    job_url = "https://job-boards.greenhouse.io/tailscale/jobs/4710703005"
    cv_path = "/Users/sashi/my-stuff/agentic-ai/weave-cv/tests/sashidharmotteresume.tex"
    output_dir = "/Users/sashi/my-stuff/agentic-ai/weave-cv/tests/output"

    final_state: dict = {}
    start = time.perf_counter()
    stage_start = start

    async for node_name, update in stream_resume_pipeline(job_url, cv_path, output_dir):
        now = time.perf_counter()
        elapsed = now - stage_start
        stage_start = now
        final_state.update(update)

        label = _STAGE_LABELS.get(node_name, node_name)

        if update.get("failed_stage"):
            print(f"[{elapsed:6.1f}s] x {label} failed: {update.get('error')}")
            break

        if node_name == "verify" and not update.get("verification_passed"):
            feedback = update.get("verification_feedback") or "no reason given"
            print(f"[{elapsed:6.1f}s] ... {label} — failed: {feedback}")
        else:
            print(f"[{elapsed:6.1f}s] ok {label}")

    total = time.perf_counter() - start
    print(f"\nTotal time: {total:.1f}s")
    print(f"failed_stage: {final_state.get('failed_stage')}")
    if not final_state.get("failed_stage"):
        print(f"tex_path: {final_state.get('generated_tex_path')}")
        print(f"pdf_path: {final_state.get('generated_pdf_path')}")

    return final_state


if __name__ == "__main__":
    asyncio.run(run_full_pipeline_with_progress())

