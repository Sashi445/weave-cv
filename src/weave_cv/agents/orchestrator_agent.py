"""Orchestrates the full resume-tailoring pipeline as a LangGraph graph:

    gather_inputs -> tailor -> verify (retry loop) -> generate

The graph's edges are all deterministic — no LLM decides routing. The only
branch is "did verification pass," which is a bounded retry driven by plain
state fields, not a judgment call. An LLM (or letting an agent choose which
tool to call next) adds cost/latency/non-determinism for zero benefit when
the routing is this fixed; see the parallel-tool-calling discussion for why
non-decisions shouldn't be delegated to an agent. The actual judgment
(tailoring quality, verification correctness) still lives in the sub-agents
each node calls — LangGraph here is just the deterministic wiring between
them, plus per-node tracing/observability for free.

Every node catches its own stage's failures and records them on state
(`failed_stage`, `error`) instead of letting a bare exception propagate —
that's what makes a failure attributable to exactly one named stage instead
of an opaque stack trace.
"""

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator, TypedDict, cast

from langchain.messages import HumanMessage
from langgraph.graph import StateGraph, START, END

from weave_cv.agents.cv_analyzer import make_cv_analyzer_agent
from weave_cv.agents.jd_analyzer import make_jd_analyzer_agent
from weave_cv.agents.resume_tailor_agent import tailor
from weave_cv.agents.resume_verifier_agent import check_reworded_bullets
from weave_cv.agents.resume_generation_agent import generate_resume
from weave_cv.schemas.cv_analysis import CVProfile
from weave_cv.schemas.jd_analysis import JobDescriptionAnalysis
from weave_cv.services.cv_diff import diff_cv_profiles

MAX_VERIFICATION_ATTEMPTS = 3


# --- Errors -------------------------------------------------------------
# One exception type per stage so a caller (human, or a future supervising
# agent reading `PipelineState["error"]`) can always tell which stage broke
# without parsing a stack trace.

class PipelineStageError(Exception):
    def __init__(self, stage: str, message: str):
        self.stage = stage
        super().__init__(f"[{stage}] {message}")


class GatherInputsError(PipelineStageError):
    def __init__(self, message: str):
        super().__init__("gather_inputs", message)


# --- State ----------------------------------------------------------------

@dataclass
class VerificationResult:
    passed: bool
    feedback: str = ""


class PipelineInput(TypedDict):
    job_url: str
    cv_path: str
    output_dir: str


class PipelineState(PipelineInput, total=False):
    jd_profile: JobDescriptionAnalysis
    original_cv: CVProfile
    tailored_cv: CVProfile

    verification_attempts: int
    verification_passed: bool
    verification_feedback: str

    generated_tex_path: str
    generated_pdf_path: str

    failed_stage: str
    error: str


# --- Stages -----------------------------------------------------------

async def gather_inputs(
    job_url: str, cv_path: str
) -> tuple[JobDescriptionAnalysis, CVProfile]:
    """Fetch the JD analysis and CV analysis concurrently — they don't
    depend on each other, so there's no reason for one to wait on the
    other (see the parallel-tool-calling discussion for why this is done
    in code rather than left to an LLM to decide to batch)."""
    jd_agent, cv_agent = await asyncio.gather(
        make_jd_analyzer_agent(),
        make_cv_analyzer_agent(),
    )
    jd_result, cv_result = await asyncio.gather(
        jd_agent.ainvoke({
            "messages": [
                HumanMessage(content=f"Analyze this job posting for me - '{job_url}'")
            ]
        }),
        cv_agent.ainvoke({
            "messages": [
                HumanMessage(content=f"Analyze my resume located at '{cv_path}'")
            ]
        }),
        return_exceptions=True,
    )

    errors = []
    if isinstance(jd_result, BaseException):
        errors.append(f"JD analysis failed: {jd_result}")
    if isinstance(cv_result, BaseException):
        errors.append(f"CV analysis failed: {cv_result}")
    if errors:
        raise GatherInputsError("; ".join(errors))

    assert not isinstance(jd_result, BaseException)
    assert not isinstance(cv_result, BaseException)
    return jd_result["structured_response"], cv_result["structured_response"]


async def verify(original_cv: CVProfile, tailored_cv: CVProfile) -> VerificationResult:
    """Two-stage verification: a deterministic structural check first (no
    LLM, catches new IDs/skills/factual-field changes — see
    services/cv_diff.py), then an LLM semantic check, but only over the
    bullets that actually changed text. If the structural check already
    fails, there's no point spending a model call on the semantic half.
    """
    diff = diff_cv_profiles(original_cv, tailored_cv)

    if diff.hallucination_signals:
        return VerificationResult(passed=False, feedback="; ".join(diff.hallucination_signals))

    semantic = await check_reworded_bullets(diff.reworded_bullets)
    if not semantic.overall_passed:
        feedback = "; ".join(
            f"{v.bullet_id}: {v.reason}" for v in semantic.bullet_verdicts if not v.fact_preserved
        )
        return VerificationResult(passed=False, feedback=feedback)

    return VerificationResult(passed=True)


async def generate(cv_profile: CVProfile, master_tex_path: str, output_dir: str, jd_analysis: JobDescriptionAnalysis | None) -> tuple[str, str]:
    return await generate_resume(cv_profile, master_tex_path, output_dir, jd_analysis=jd_analysis)


# --- Nodes ----------------------------------------------------------------
# Each node catches its own stage's exceptions and records failed_stage/error
# on state rather than raising, so run_resume_pipeline() always returns a
# state dict — callers never need a try/except around it.

async def gather_inputs_node(state: PipelineState) -> dict:
    try:
        jd_profile, original_cv = await gather_inputs(state["job_url"], state["cv_path"])
    except GatherInputsError as e:
        return {"failed_stage": e.stage, "error": str(e)}
    return {"jd_profile": jd_profile, "original_cv": original_cv, "tailored_cv": original_cv}


async def tailor_node(state: PipelineState) -> dict:
    # jd_profile/original_cv are always set by this point — gather_inputs_node
    # runs first and _stop_if_failed short-circuits to END if it didn't
    # succeed, so tailor_node only ever runs with both populated.
    jd_profile = state.get("jd_profile")
    original_cv = state.get("original_cv")
    assert jd_profile is not None and original_cv is not None

    attempt = state.get("verification_attempts", 0) + 1
    try:
        tailored_cv = await tailor(
            jd_profile,
            original_cv,
            feedback=state.get("verification_feedback") or None,
        )
    except Exception as e:
        return {"failed_stage": "tailor", "error": str(e)}
    return {"tailored_cv": tailored_cv, "verification_attempts": attempt}


async def verify_node(state: PipelineState) -> dict:
    # Same guarantee as above: only reached after tailor_node succeeds.
    original_cv = state.get("original_cv")
    tailored_cv = state.get("tailored_cv")
    assert original_cv is not None and tailored_cv is not None

    try:
        result = await verify(original_cv, tailored_cv)
    except Exception as e:
        return {"failed_stage": "verify", "error": str(e)}
    return {"verification_passed": result.passed, "verification_feedback": result.feedback}


async def generate_node(state: PipelineState) -> dict:
    tailored_cv = state.get("tailored_cv")
    jd_analysis = state.get("jd_profile")
    assert tailored_cv is not None

    try:
        # cv_path is the master resume's .tex file — its template gets
        # reused by generate_resume(), not just its content.
        tex_path, pdf_path = await generate(tailored_cv, state["cv_path"], state["output_dir"], jd_analysis=jd_analysis)
    except Exception as e:
        return {"failed_stage": "generate", "error": str(e)}
    return {"generated_tex_path": tex_path, "generated_pdf_path": pdf_path}


# --- Graph ------------------------------------------------------------

def _stop_if_failed(state: PipelineState) -> str:
    return "end" if state.get("failed_stage") else "next"


def _route_after_verify(state: PipelineState) -> str:
    if state.get("failed_stage"):
        return "end"
    if state.get("verification_passed"):
        return "generate"
    if state.get("verification_attempts", 0) >= MAX_VERIFICATION_ATTEMPTS:
        # TODO: decide the fallback policy for exhausting attempts without
        # passing — currently proceeds to generate with the last
        # (unverified) tailored_cv rather than aborting.
        return "generate"
    return "tailor"


def build_resume_pipeline_graph():
    graph = StateGraph(PipelineState)

    graph.add_node("gather_inputs", gather_inputs_node)
    graph.add_node("tailor", tailor_node)
    graph.add_node("verify", verify_node)
    graph.add_node("generate", generate_node)

    graph.add_edge(START, "gather_inputs")
    graph.add_conditional_edges("gather_inputs", _stop_if_failed, {"end": END, "next": "tailor"})
    graph.add_conditional_edges("tailor", _stop_if_failed, {"end": END, "next": "verify"})
    graph.add_conditional_edges(
        "verify", _route_after_verify, {"tailor": "tailor", "generate": "generate", "end": END}
    )
    graph.add_edge("generate", END)

    return graph.compile(name="Resume-Tailoring-Pipeline")


resume_pipeline_graph = build_resume_pipeline_graph()


async def run_resume_pipeline(job_url: str, cv_path: str, output_dir: str) -> PipelineState:
    result = await resume_pipeline_graph.ainvoke({
        "job_url": job_url,
        "cv_path": cv_path,
        "output_dir": output_dir,
        "verification_attempts": 0,
    })
    return cast(PipelineState, result)


async def stream_resume_pipeline(
    job_url: str, cv_path: str, output_dir: str
) -> AsyncIterator[tuple[str, dict]]:
    """Same pipeline as run_resume_pipeline(), but yields (node_name,
    state_update) as each stage completes instead of only returning the
    final state — for callers (like the CLI) that want live progress
    instead of sitting silent for the whole run."""
    async for chunk in resume_pipeline_graph.astream(
        {
            "job_url": job_url,
            "cv_path": cv_path,
            "output_dir": output_dir,
            "verification_attempts": 0,
        },
        stream_mode="updates",
    ):
        for node_name, update in chunk.items():
            yield node_name, update
