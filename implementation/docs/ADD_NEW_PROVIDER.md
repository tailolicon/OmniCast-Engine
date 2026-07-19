# Add a New OmniCast Provider

Use this when adding a new TTS, image, video, or music/BGM source.

## Contract

New providers should implement the relevant Protocol in:

- `src/omnicast/media/providers/interfaces.py`

Required public fields:

- `id`
- `name`
- `capability`
- `models`
- `cost_per_unit`
- `rate_limit`

Required methods:

- `health_check()`
- `generate(...)` for image/TTS-style providers
- `convert(...)` for image-to-video providers

## Steps

1. Create an adapter module under `src/omnicast/media/providers/`.
2. Implement the smallest provider class that wraps the external API or local runtime.
3. Add one entry to `providers.manifest.yaml`.
4. Start the app or call `GET /api/capabilities`; the provider should appear without editing `agents/`, `pipeline/`, or `media/orchestrator.py`.
5. Add a focused unit test or dry-run test for the adapter.

## Manifest Example

```yaml
providers:
  - id: example-image
    capability: image
    name: Example Image Provider
    adapter_class: omnicast.media.providers.example.ExampleImageProvider
    runtime: remote
    priority: 50
    cost_per_unit: 0.02
    requires_credential: true
    config_schema:
      api_key:
        type: secret
        provider: example
      base_url:
        type: url
```

## Runtime Selection

`CapabilityBus` and `RuntimeRouter` use the manifest metadata to select providers:

- `runtime`: `local`, `remote`, or `browser`
- `min_vram_mb`: minimum local GPU memory needed
- `cost_per_unit`: budget estimate
- `fallback_chain`: ordered provider IDs for failover

Example:

```python
from omnicast.capabilities import CapabilityBus, ResolvePolicy

bus = CapabilityBus()
chain = bus.resolve_with_fallback(
    "image",
    policy=ResolvePolicy(
        prefer_runtime="local",
        fallback_chain=["local-sd", "gemini", "flow"],
    ),
)
```

If a local provider cannot run because `OMNICAST_GPU_FREE_MB` is below `min_vram_mb`, the router skips it and selects the next valid provider.
