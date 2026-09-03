"""M0 PR6 — RabbitMQ helpers (queue naming, QoS prefetch, job encode/decode).

The live publish/consume path needs a running broker and is integration-tested
separately; these cover the pure logic."""

from omnicast.jobengine.models import JobSpec, ResourceClass, WorkerSlots
from omnicast.jobengine import rabbit


def test_queue_and_prefetch():
    assert rabbit.queue_name(ResourceClass.GPU) == "jobs.gpu"
    s = WorkerSlots(worker_id="w", slots_gpu=2, slots_cpu=8, slots_net=16)
    assert rabbit.prefetch_for(s, ResourceClass.GPU) == 2
    assert rabbit.prefetch_for(s, ResourceClass.CPU) == 8


def test_encode_decode_roundtrip():
    spec = JobSpec(job_id="j", type="render", resource_class=ResourceClass.GPU,
                   priority=5, payload={"k": "v"})
    back = rabbit.decode_job(rabbit.encode_job(spec))
    assert back.job_id == "j" and back.resource_class == ResourceClass.GPU and back.payload == {"k": "v"}
