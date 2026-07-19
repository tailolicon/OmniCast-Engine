# AI Memory Ledger: Lessons Learned & Pitfalls

<!-- [VIBECODER-LEDGER-VERSION: v1.1.0] -->

> **CRITICAL STANDARD:** ALL AI models MUST read this ledger before coding.
> Append learnings here autonomously after resolving bugs to prevent circular regression.

## Verified Constraints & Past Fixes

### 1. Baseline Surgical Rule
- **Mistake to Avoid:** Rewiring adjacent working code while trying to fix an isolated bug.
- **Enforced Solution:** Strictly isolate target lines. Verify localized behavior before modifying.

### 2. Provider Constructors Must Not Raise on Missing Credentials (W1.T10)
- **Mistake:** `GeminiImageProvider.__init__` raised `MediaError` when `GOOGLE_API_KEY` was empty, breaking `get_image_provider()` / `list_providers()` for callers that only need metadata.
- **Enforced Solution:** Constructors store config silently; `generate()`/`convert()` validate the key at call time. Mirrors AutoVio's per-call `apiKey` arg.

### 3. Status Flags Must Reflect Semantics, Not List Presence (W1.T11)
- **Mistake:** Orchestrator marked `state.images = DONE` whenever `image_results` was a non-empty list, even if every entry was an empty-path failure stub.
- **Enforced Solution:** Use `any(r.image_path for r in image_results)` to require at least one real success before marking DONE.

### 4. Test Fixtures Must Track Real Call Paths After Refactors (W1.T11)
- **Mistake:** `test_media_orchestrator.py` mocked `image_gen.process()` after the orchestrator was rewired to call providers via `registry.get_image_provider()`, leaving the mock dead.
- **Enforced Solution:** When refactoring a call site, audit every test using `MagicMock.process =`-style fixtures. Add an `autouse` provider-registry fixture that registers/cleans mock providers per test.

### 5. Memoize Array Props passed to useEffect Dependencies
- **Mistake:** Dereferencing array structures directly inside a React component (e.g., `const products = productsData?.products || []`) and passing them to `useEffect` dependencies causes infinite re-renders since a new array reference is created on every render.
- **Enforced Solution:** Depend on the query wrapper object (e.g., `productsData`) directly, or memoize using `useMemo` to ensure stable references.

### 6. TypeScript Unused Variables in Map Loops
- **Mistake:** Declaring intermediate parameter names in React map loops (e.g., `map((shot, sidx) => ...)`) when only the index is needed will fail compiling on strict setups.
- **Enforced Solution:** Use `_` or `_shot` for unused parameters to satisfy TS compilation.

