"""Kestra-lite pipeline runner.

Loads a YAML pipeline spec, resolves Jinja2 template inputs, runs steps in
dependency order with per-step retry + timeout, and persists every execution
to pipeline_executions in vault.db.

Usage:
    runner = PipelineRunner()
    execution = await runner.run_file(
        Path("pipelines/default_channel.yaml"),
        inputs={"channel_id": "my_channel"},
    )

Scheduling (auto-register all pipelines in a directory):
    scheduler = PipelineScheduler(pipelines_dir=Path("pipelines/"))
    scheduler.start()   # registers APScheduler jobs for every spec with schedule:
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

import structlog
import yaml

from omnicast.pipeline.executions import upsert_execution, init_executions_table
from omnicast.pipeline.models import (
    Execution, ExecutionStatus, PipelineSpec,
    RetrySpec, StepResult, StepSpec, StepStatus,
)
from omnicast.pipeline.steps import get_step

logger = structlog.get_logger()


# ── Jinja2-lite template resolver ─────────────────────────────────────────────

def _resolve(value: Any, context: dict) -> Any:
    """Recursively resolve Jinja2-style ``{{ expr }}`` placeholders.

    Supports simple dotted lookups:
        {{ channel_id }}
        {{ inputs.do_upload }}
        {{ steps.discovery.topic }}
    Does NOT execute arbitrary Python — intentionally limited.
    """
    if isinstance(value, str):
        def _sub(m: re.Match) -> str:
            expr = m.group(1).strip()
            parts = expr.split(".")
            node: Any = context
            for p in parts:
                if isinstance(node, dict):
                    node = node.get(p)
                else:
                    node = getattr(node, p, None)
                if node is None:
                    return ""
            return str(node) if node is not None else ""
        result = re.sub(r"\{\{\s*(.*?)\s*\}\}", _sub, value)
        # If the whole string was one placeholder, try to preserve original type
        if re.fullmatch(r"\{\{\s*.*?\s*\}\}", value.strip()):
            inner = re.sub(r"\{\{\s*(.*?)\s*\}\}", _sub, value)
            try:
                return int(inner) if inner.isdigit() else (
                    float(inner) if re.match(r"^-?\d+\.\d+$", inner) else (
                        True if inner == "True" else (
                            False if inner == "False" else inner
                        )
                    )
                )
            except Exception:
                return inner
        return result
    if isinstance(value, dict):
        return {k: _resolve(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, context) for v in value]
    return value


def _eval_condition(expr: str | None, context: dict) -> bool:
    """Evaluate a simple condition expression from the spec.

    Supported forms:
        {{ inputs.do_upload == true }}
        {{ steps.render.video_path != "" }}
    Returns True if condition is absent (step always runs).
    """
    if not expr:
        return True
    resolved = _resolve(expr, context)
    if isinstance(resolved, bool):
        return resolved
    low = str(resolved).lower().strip()
    return low not in ("false", "0", "none", "", "null")


# ── Runner ────────────────────────────────────────────────────────────────────

class PipelineRunner:
    """Loads + runs pipeline YAML specs with retry, timeout, and executions log."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db = db_path
        init_executions_table(db_path)

    @staticmethod
    def load_spec(path: Path) -> PipelineSpec:
        """Parse a YAML pipeline definition into a PipelineSpec."""
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return PipelineSpec.model_validate(raw)

    async def run_file(self, path: Path, inputs: dict[str, Any] | None = None) -> Execution:
        """Load spec from YAML file and run it."""
        spec = self.load_spec(path)
        return await self.run(spec, inputs=inputs)

    async def run_checkpointed_file(
        self,
        path: Path,
        inputs: dict[str, Any] | None,
        *,
        job_id: str,
        events=None,
    ) -> Execution:
        """Run a YAML spec with JobEngine checkpoints per pipeline step."""
        from omnicast.jobengine import store as job_store
        from omnicast.jobengine.idempotency import idempotency_key

        spec = self.load_spec(path)
        inputs = dict(inputs or {})
        execution_id = str(uuid.uuid4())
        execution = Execution(
            execution_id=execution_id,
            pipeline_id=spec.id,
            channel_id=inputs.get("channel_id"),
            status=ExecutionStatus.RUNNING,
            started_at=datetime.now(UTC),
            inputs=inputs,
        )
        upsert_execution(execution, self._db)

        context: dict[str, Any] = {"inputs": inputs, "steps": {}, **inputs}
        try:
            order = spec.step_order()
        except Exception as exc:
            execution = execution.model_copy(update={
                "status": ExecutionStatus.FAILED,
                "finished_at": datetime.now(UTC),
                "error": f"Dependency resolution failed: {exc}",
            })
            upsert_execution(execution, self._db)
            return execution

        step_map = {s.id: s for s in spec.steps}
        total = len([sid for sid in order if sid in step_map])
        idx = 0
        for step_id in order:
            if step_id not in step_map:
                continue
            idx += 1
            step_spec = step_map[step_id]
            resolved_inputs = _resolve(step_spec.inputs, context)
            for k, v in inputs.items():
                resolved_inputs.setdefault(k, v)

            key = idempotency_key(step_spec.type, {"step_id": step_id, "inputs": resolved_inputs})
            checkpoint = job_store.get_checkpoint(job_id, step_id, db_path=self._db)
            if checkpoint and checkpoint["idempotency_key"] == key:
                outputs = dict(checkpoint.get("output") or {})
                result = StepResult(
                    step_id=step_id,
                    status=StepStatus.SKIPPED,
                    started_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                    outputs=outputs,
                )
                if events:
                    events.emit("job.step.progress", job_id=job_id, idx=idx,
                                total=total, name=step_id, state="skipped")
            else:
                if events:
                    events.emit("job.step.progress", job_id=job_id, idx=idx,
                                total=total, name=step_id, state="running")
                result = await self._run_step(step_spec, context, execution_id)
                if result.status == StepStatus.SUCCESS:
                    output_ref = (
                        result.outputs.get("video_path")
                        or result.outputs.get("script_path")
                        or result.outputs.get("url")
                        or result.outputs.get("topic")
                    )
                    job_store.save_checkpoint(
                        job_id, step_id, key, output_ref, result.outputs, db_path=self._db
                    )
                    if events:
                        events.emit("job.step.progress", job_id=job_id, idx=idx,
                                    total=total, name=step_id, state="success")

                    # Check pause after script
                    if step_id == "script":
                        pause_after_script = False
                        channel_id = inputs.get("channel_id")
                        if channel_id:
                            try:
                                ch_file = Path("channels") / f"{channel_id}.json"
                                if ch_file.exists():
                                    import json
                                    ch_data = json.loads(ch_file.read_text(encoding="utf-8"))
                                    pause_after_script = ch_data.get("pause_after_script", False)
                            except Exception:
                                pass

                        if pause_after_script and not inputs.get("resume_script"):
                            raise RuntimeError(f"WAITING_EDIT:{result.outputs.get('script_path')}")

            execution.steps[step_id] = result
            context["steps"][step_id] = result.outputs
            upsert_execution(execution, self._db)
            if result.status == StepStatus.FAILED:
                execution = execution.model_copy(update={
                    "status": ExecutionStatus.FAILED,
                    "finished_at": datetime.now(UTC),
                    "error": f"Step '{step_id}' failed: {result.error}",
                })
                upsert_execution(execution, self._db)
                return execution

        execution = execution.model_copy(update={
            "status": ExecutionStatus.SUCCESS,
            "finished_at": datetime.now(UTC),
        })
        upsert_execution(execution, self._db)
        return execution

    async def run_single_step(
        self,
        step_id: str,
        step_type: str,
        inputs: dict[str, Any] | None = None,
        *,
        pipeline_id: str = "single_step",
        timeout_seconds: float = 3900.0,  # was 2100 — heavier debate (revise+expand) timed out
        retry: RetrySpec | None = None,
    ) -> StepResult:
        """Run one registered step through the same execution ledger as YAML specs."""
        inputs = dict(inputs or {})
        execution_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        execution = Execution(
            execution_id=execution_id,
            pipeline_id=pipeline_id,
            channel_id=inputs.get("channel_id"),
            status=ExecutionStatus.RUNNING,
            started_at=now,
            inputs=inputs,
        )
        upsert_execution(execution, self._db)

        context: dict[str, Any] = {"inputs": inputs, "steps": {}, **inputs}
        step_spec = StepSpec(
            id=step_id,
            type=step_type,
            inputs=inputs,
            timeout_seconds=timeout_seconds,
            retry=retry or RetrySpec(max_attempts=1, delay_seconds=0),
        )
        result = await self._run_step(step_spec, context, execution_id)
        execution.steps[step_id] = result
        execution = execution.model_copy(update={
            "status": ExecutionStatus.SUCCESS if result.status == StepStatus.SUCCESS else ExecutionStatus.FAILED,
            "finished_at": datetime.now(UTC),
            "error": result.error,
        })
        upsert_execution(execution, self._db)

        # Observability: a FAILED step must not leave a ghost "Đang chạy" row —
        # write a terminal event + clear the active job (best-effort; timeouts
        # and crashes previously left the dashboard showing running forever).
        if result.status != StepStatus.SUCCESS and inputs.get("channel_id"):
            try:
                from omnicast.api import state as _api_state
                _cid = str(inputs["channel_id"])
                _phase = {"omnicast.script": "script_generation",
                          "omnicast.discovery": "discovery",
                          "omnicast.render": "render",
                          "omnicast.upload": "upload"}.get(step_type, step_type)
                _api_state.write_pipeline_event(
                    _cid, _phase, "failed",
                    topic=str(inputs.get("topic", "")),
                    extra={"error": (result.error or "")[:300]})
                _api_state.clear_active_job(_cid)
            except Exception:
                pass
        return result

    async def run(self, spec: PipelineSpec, inputs: dict[str, Any] | None = None) -> Execution:
        """Execute a pipeline spec. Returns the completed Execution."""
        inputs = dict(inputs or {})
        execution_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        execution = Execution(
            execution_id=execution_id,
            pipeline_id=spec.id,
            channel_id=inputs.get("channel_id"),
            status=ExecutionStatus.RUNNING,
            started_at=now,
            inputs=inputs,
        )
        upsert_execution(execution, self._db)
        logger.info("pipeline.run: started", pipeline=spec.id,
                    execution=execution_id, inputs=inputs)

        # Build Jinja2 context for template resolution
        context: dict[str, Any] = {
            "inputs": inputs,
            "steps": {},
            **inputs,  # shorthand: {{ channel_id }} == {{ inputs.channel_id }}
        }

        try:
            order = spec.step_order()
        except Exception as exc:
            execution = execution.model_copy(update={
                "status": ExecutionStatus.FAILED,
                "finished_at": datetime.now(UTC),
                "error": f"Dependency resolution failed: {exc}",
            })
            upsert_execution(execution, self._db)
            return execution

        step_map = {s.id: s for s in spec.steps}

        for step_id in order:
            if step_id not in step_map:
                continue   # deps-only phantom node
            step_spec = step_map[step_id]
            result = await self._run_step(step_spec, context, execution_id)

            execution.steps[step_id] = result
            context["steps"][step_id] = result.outputs
            upsert_execution(execution, self._db)

            if result.status == StepStatus.FAILED:
                execution = execution.model_copy(update={
                    "status": ExecutionStatus.FAILED,
                    "finished_at": datetime.now(UTC),
                    "error": f"Step '{step_id}' failed: {result.error}",
                })
                upsert_execution(execution, self._db)
                logger.error("pipeline.run: failed", pipeline=spec.id,
                             execution=execution_id, step=step_id, error=result.error)
                return execution

        execution = execution.model_copy(update={
            "status": ExecutionStatus.SUCCESS,
            "finished_at": datetime.now(UTC),
        })
        upsert_execution(execution, self._db)
        logger.info("pipeline.run: success", pipeline=spec.id, execution=execution_id)
        return execution

    async def _run_step(
        self,
        step_spec,
        context: dict[str, Any],
        execution_id: str,
    ) -> StepResult:
        """Run one step with retry + timeout. Returns StepResult."""
        from omnicast.pipeline.models import StepSpec
        started_at = datetime.now(UTC)

        # Resolve inputs using current context
        resolved_inputs = _resolve(step_spec.inputs, context)
        # Also inject top-level inputs so steps don't need to be explicit
        for k, v in context.get("inputs", {}).items():
            resolved_inputs.setdefault(k, v)

        # Condition check
        if not _eval_condition(step_spec.condition, context):
            logger.info("pipeline.step: skipped (condition false)",
                        step=step_spec.id, execution=execution_id)
            return StepResult(
                step_id=step_spec.id,
                status=StepStatus.SKIPPED,
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )

        retry = step_spec.retry
        delay = retry.delay_seconds
        last_error: str = ""

        for attempt in range(1, retry.max_attempts + 1):
            try:
                step_fn = get_step(step_spec.type)
                from omnicast.pipeline.steps import StepContext
                ctx = StepContext(
                    execution_id=execution_id,
                    pipeline_id="",
                    inputs=resolved_inputs,
                    step_outputs={k: v.outputs for k, v in {}.items()},
                )
                outputs = await asyncio.wait_for(
                    step_fn(resolved_inputs, ctx),
                    timeout=step_spec.timeout_seconds,
                )
                logger.info("pipeline.step: success",
                            step=step_spec.id, attempt=attempt, execution=execution_id)
                return StepResult(
                    step_id=step_spec.id,
                    status=StepStatus.SUCCESS,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    outputs=outputs or {},
                    attempts=attempt,
                )
            except asyncio.TimeoutError:
                last_error = f"Timed out after {step_spec.timeout_seconds}s"
                logger.warning("pipeline.step: timeout",
                               step=step_spec.id, attempt=attempt,
                               timeout=step_spec.timeout_seconds)
            except Exception as exc:
                last_error = str(exc)
                logger.warning("pipeline.step: error",
                               step=step_spec.id, attempt=attempt,
                               error=last_error)

            if attempt < retry.max_attempts:
                sleep_time = delay * (retry.backoff_multiplier ** (attempt - 1))
                logger.info("pipeline.step: retrying",
                            step=step_spec.id, after_seconds=sleep_time)
                await asyncio.sleep(sleep_time)

        return StepResult(
            step_id=step_spec.id,
            status=StepStatus.FAILED,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            error=last_error,
            attempts=retry.max_attempts,
        )


# ── Scheduler ─────────────────────────────────────────────────────────────────

class PipelineScheduler:
    """Registers APScheduler cron jobs for every pipeline with a schedule: block.

    Usage:
        sched = PipelineScheduler(pipelines_dir=Path("pipelines/"))
        sched.start()
        # call sched.shutdown() on process exit
    """

    def __init__(
        self,
        pipelines_dir: Path,
        db_path: Path | None = None,
        runner: PipelineRunner | None = None,
    ) -> None:
        self._dir = pipelines_dir
        self._runner = runner or PipelineRunner(db_path)
        self._sched = None

    def start(self) -> None:
        """Scan pipelines_dir and register APScheduler jobs."""
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            logger.warning("APScheduler not installed — PipelineScheduler disabled")
            return

        self._sched = AsyncIOScheduler()

        for yaml_file in self._dir.glob("*.yaml"):
            try:
                spec = PipelineRunner.load_spec(yaml_file)
            except Exception as exc:
                logger.warning("pipeline: failed to load spec",
                               file=str(yaml_file), error=str(exc))
                continue
            if not spec.schedule:
                continue

            schedule = spec.schedule
            inputs: dict[str, Any] = {}
            if schedule.channel_id:
                inputs["channel_id"] = schedule.channel_id
            inputs["do_upload"] = schedule.do_upload

            # Capture loop variables for the closure
            def _make_job(s: PipelineSpec, i: dict):
                async def _job():
                    logger.info("PipelineScheduler: firing", pipeline=s.id, inputs=i)
                    await self._runner.run(s, inputs=i)
                return _job

            try:
                trigger = CronTrigger.from_crontab(schedule.cron)
            except Exception:
                # Try space-separated cron directly
                trigger = CronTrigger.from_crontab(schedule.cron)

            self._sched.add_job(
                _make_job(spec, inputs),
                trigger,
                id=f"pipeline_{spec.id}",
                replace_existing=True,
            )
            logger.info("PipelineScheduler: registered",
                        pipeline=spec.id, cron=schedule.cron)

        self._sched.start()
        logger.info("PipelineScheduler: started",
                    jobs=len(self._sched.get_jobs()))

    def shutdown(self) -> None:
        if self._sched and self._sched.running:
            self._sched.shutdown(wait=False)
