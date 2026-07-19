"""Kestra-lite declarative pipeline runner for OmniCast Engine.

Usage:
    from omnicast.pipeline.runner import PipelineRunner
    from pathlib import Path

    runner = PipelineRunner()
    execution = await runner.run_file(
        Path("pipelines/default_channel.yaml"),
        inputs={"channel_id": "my_channel", "do_upload": False},
    )
"""

from omnicast.pipeline.models import PipelineSpec, StepSpec, StepResult, Execution
from omnicast.pipeline.runner import PipelineRunner

__all__ = ["PipelineSpec", "StepSpec", "StepResult", "Execution", "PipelineRunner"]
