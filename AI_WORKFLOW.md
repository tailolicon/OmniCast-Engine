# OmniCast Engine — AI Orchestration Workflow

> **Dành cho AI agents:** Đọc file này TRƯỚC khi bắt đầu bất kỳ phase nào.
> Định nghĩa cách phân công model, tối ưu cost, đảm bảo quality.

---

## 1. Nguyên tắc cốt lõi

```
Opus   = Spec writer + test author (single-turn, high impact decisions)
Sonnet = Worker (logic-heavy implementation, complex debugging)
Haiku  = Worker (implement-to-pass-tests, mechanical fixes, docs)
```

**Quy tắc vàng:** Opus không review code. Opus định nghĩa "đúng" bằng tests.
Tests là quality gate — deterministic, free, không cần AI review.

**Test-First Spec:** Opus viết spec + complete test file → Workers chỉ implement cho pytest pass.

---

## 2. Model Routing Matrix

| Task | Model | Lý do |
|------|-------|-------|
| Phase planning | **Opus single-turn** | Sai plan = build sai toàn bộ |
| Architecture decisions | **Opus single-turn** | Sai kiến trúc = refactor toàn bộ |
| Security review | **Opus single-turn** | Miss vuln = breach |
| **Task spec + test file viết** | **Opus single-turn** | Tests định nghĩa "đúng" chính xác |
| Complex root cause debug | **Opus single-turn** | Race conditions, non-obvious bugs |
| Implement khi tests đã có sẵn | **Haiku** | Mechanical: make green bar |
| Implement logic phức tạp (no tests) | **Sonnet** | Cần reasoning |
| Fix bugs (known cause) | **Haiku** | Deterministic |
| Rename/format/lint fixes | **Haiku** | Pattern matching |
| Docs/README | **Haiku** | Text gen |

### CRITICAL: Opus Usage Rules

```
❌ KHÔNG BAO GIỜ: Opus review code sau khi implement
   → Tests làm việc đó tốt hơn, miễn phí, không cần AI

❌ KHÔNG BAO GIỜ: Opus trong multi-turn conversation dài
   → Context tích lũy × $15/MTok = cháy tiền
   → 15 turns × 50K context = 750K tokens = $11.25 CHỈ INPUT

✅ LUÔN LUÔN: Opus single-turn, batch input
   → Gom TẤT CẢ context vào 1 prompt
   → Opus trả lời 1 lần, xong

✅ LUÔN LUÔN: Opus viết tests TRƯỚC khi giao worker
   → Tests = spec chính xác, không mơ hồ
   → Worker không thể implement sai nếu tests đủ comprehensive
```

---

## 3. Phase Execution Workflow (Test-First)

### Step 1: Planning (Opus, single-turn)

```
Input:  PROJECT_CONTEXT.md + previous phase output + phase goals
Output:
  - implementation/phaseN/README.md  (dependency graph, conventions)
  - TASK list với dependency ordering

Model:  Opus
Format: SINGLE prompt, ALL context in one message
Cost:   < $1.00
```

### Step 2: Task Spec + Test Writing (Opus, single-turn batch)

```
Gom TẤT CẢ tasks vào 1 Opus prompt:
  Input:  Phase README + schemas + errors + context files
  Output: TASK_A.md, TASK_B.md, ... (mỗi file có complete test code)

Mỗi TASK_X.md PHẢI có:
  1. Mục tiêu (1-2 câu)
  2. Files cần tạo
  3. Interface definition (method signatures + types)
  4. COMPLETE TEST FILE — copy-paste ready, syntactically valid
  5. Stub implementation (để verify tests chạy được, không pass)
  6. DO NOT list
  7. Verify command

Model:  Opus
Cost:   < $2.00 (toàn bộ phase)
```

**Test file requirements:**
- Imports hoạt động (dùng đúng module paths)
- Fixtures rõ ràng (mock objects, tmp_path)
- Happy path + error path + edge cases
- Tests FAIL với stub implementation (đúng lý do: assertion, không phải ImportError)

### Step 3: Worker Implementation (Haiku/Sonnet, parallel)

```
Worker nhận: TASK_X.md (có sẵn test file)
Worker làm:
  1. Đọc interface definition
  2. Copy test file vào tests/unit/test_xxx.py NGUYÊN VẸN
  3. Implement src/ cho đến khi pytest pass
  4. Chạy ruff + pyright

Worker KHÔNG được:
  - Modify test file
  - Thêm/bỏ test cases
  - Skip assertions
  - Implement thêm ngoài interface

Model: Haiku (nếu tests đã có) / Sonnet (nếu cần reasoning)
Cost:  < $0.15/task (Haiku), < $0.30/task (Sonnet)
```

### Step 4: Automated Verification (FREE)

```bash
# Worker tự chạy, PHẢI PASS trước khi báo xong:
uv run pytest tests/unit/test_xxx.py -v     # tests must pass
uv run ruff check src/omnicast/xxx/          # 0 errors
uv run pyright src/omnicast/xxx/             # 0 errors
```

Nếu fail → worker tự fix, không escalate.

### Step 5: Fix Iteration (Haiku, nếu cần)

```
Nếu pytest fail sau implementation:
  - Haiku đọc error + test code + implementation
  - Fix implementation (KHÔNG sửa tests)
  - Max 3 iterations tự fix
  - Nếu vẫn fail → escalate Sonnet với full context

Nếu tests sai (Opus viết test lỗi):
  - Document lỗi cụ thể
  - Sonnet fix test (phải match spec intent)
  - Log: "test correction needed"
```

### Step 6: Phase Completion

```
Sau TẤT CẢ tasks xong:
  1. Chạy full test suite: uv run pytest tests/ -v
  2. Import verification (xem README.md của phase)
  3. Update project memory (project_omnicast.md)
  
KHÔNG cần Opus review nếu:
  - pytest pass 100%
  - pyright 0 errors
  - ruff 0 warnings
  
CHỈ dùng Opus review khi:
  - Security-critical code (auth, API keys, injection paths)
  - Architecture change ảnh hưởng multiple phases
  - 3+ failed fix iterations (Opus diagnose root cause)
```

---

## 4. Cost Budget per Phase (Test-First Model)

| Component | Cost | Notes |
|-----------|-----:|-------|
| Opus planning | $0.50 | 1 single-turn |
| Opus spec + test writing | $1.50 | Batch all tasks, 1 turn |
| Haiku workers (parallel) | $0.60 | 6 tasks × $0.10 |
| Sonnet workers (complex) | $0.30 | 1-2 logic-heavy tasks |
| Automated screening | $0.00 | Free |
| Opus review | $0.00 | Not needed (tests = gate) |
| Fix iterations | $0.20 | Haiku fixes |
| **Total per phase** | **$3.10** | |

### Comparison

```
All Opus approach:        ~$10.00/phase
Old orchestration:        ~$5.60/phase  (Sonnet review + Opus spot-check)
Test-First approach:      ~$3.10/phase  ← CURRENT STANDARD
All Sonnet no QA:         ~$2.00/phase  (no quality gate, risky)

Test-First = All-Sonnet + $1.10 quality premium
Quality gate: Opus-written tests (comprehensive, deterministic, free to run)
```

---

## 5. Task Spec Template (Test-First)

```markdown
# TASK_X: [Module Name]

## Model: haiku | sonnet
## Estimated time: XX minutes
## Dependencies: TASK_A (must complete first)

## Mục tiêu
[1-2 câu mô tả module làm gì]

## Files

| File | Lines | Description |
|------|------:|-------------|
| `src/omnicast/xxx/yyy.py` | ~100 | Implementation |
| `tests/unit/test_xxx.py` | ~120 | Pre-written tests — COPY AS-IS |

## Context Files (đọc trước)

- `src/omnicast/models/schemas.py` — Pydantic models
- `src/omnicast/shared/errors.py` — Error types

## Interface Definition

```python
# src/omnicast/xxx/yyy.py

from omnicast.shared.errors import OmnicastError

class MyClass:
    """Docstring."""

    def __init__(self, dep: Dependency) -> None: ...

    async def method(self, arg: str) -> Result:
        """
        Steps:
        1. Validate arg
        2. Do thing
        3. Return Result
        Raises: OmnicastError on failure
        """
        raise NotImplementedError  # stub — implement này
```

## Pre-Written Tests

```python
# tests/unit/test_xxx.py
# DO NOT MODIFY — copy this file exactly

import pytest
from unittest.mock import AsyncMock, patch
from omnicast.xxx.yyy import MyClass
from omnicast.shared.errors import OmnicastError


@pytest.fixture
def mock_dep() -> AsyncMock:
    dep = AsyncMock()
    dep.some_method.return_value = "ok"
    return dep


@pytest.fixture
def my_class(mock_dep) -> MyClass:
    return MyClass(dep=mock_dep)


class TestMyClass:
    async def test_happy_path(self, my_class, mock_dep):
        """Normal operation returns Result."""
        result = await my_class.method("valid_input")
        assert result.field == "expected_value"
        mock_dep.some_method.assert_called_once_with("valid_input")

    async def test_error_propagates(self, my_class, mock_dep):
        """Dependency error raises OmnicastError."""
        mock_dep.some_method.side_effect = Exception("conn failed")
        with pytest.raises(OmnicastError, match="conn failed"):
            await my_class.method("input")

    async def test_empty_input(self, my_class):
        """Empty string raises OmnicastError."""
        with pytest.raises(OmnicastError, match="empty"):
            await my_class.method("")
```

## DO NOT

- ❌ Không sửa test file
- ❌ Không dùng sync I/O
- ❌ Không hardcode values
- ❌ Không swallow exceptions silently
- ❌ Không implement methods ngoài interface trên

## Verify (chạy trước khi báo xong)

```bash
uv run pytest tests/unit/test_xxx.py -v   # phải PASS
uv run ruff check src/omnicast/xxx/        # phải 0 errors
uv run pyright src/omnicast/xxx/           # phải 0 errors
```
```

---

## 6. Fix Task Template

```markdown
# TASK_X_fix: [Description]

## Model: haiku | sonnet
## Estimated time: XX minutes

## Bugs Found

### Bug 1: [Description]
**File:** `src/omnicast/xxx/yyy.py`
**Line:** 42
**Test that fails:** `test_happy_path`
**Error:** `AssertionError: expected "foo", got None`
**Root cause:** [1 sentence]
**Fix:**
```python
# BEFORE (line 42):
old_code_here

# AFTER:
new_code_here
```

## DO NOT
- ❌ Không đổi gì ngoài bugs listed above
- ❌ Không refactor adjacent code
- ❌ Không sửa test file

## Verify
```bash
uv run pytest tests/unit/test_xxx.py -v
```
```

---

## 7. Checklist (worker self-check trước khi báo xong)

```
□ pytest tests/unit/test_xxx.py -v → ALL PASS
□ ruff check → 0 errors, 0 warnings
□ pyright → 0 errors
□ Không sửa test file
□ Tất cả methods trong interface có implementation
□ Không có print() hay debug code
□ Imports đúng (absolute, từ omnicast.xxx)
□ Async functions dùng await, không blocking calls
□ Custom exceptions từ shared/errors.py
```

---

## 8. Parallel Execution Rules

### Worker Independence

```
Mỗi worker session:
  - Fresh context (không share conversation history)
  - Đọc: TASK_X.md + context files được list
  - Viết: chỉ files listed trong TASK_X.md
  - KHÔNG đọc/sửa files của worker khác

File ownership: 1 writer per file at any time
Nếu 2 tasks cần sửa cùng 1 file → serialize, không parallelize
```

### Dependency Ordering

```
TASK_A (foundation) ← PHẢI XONG TRƯỚC (tạo shared interfaces)
    ↓
TASK_B ─┐
TASK_C  ├── PARALLEL (independent modules)
TASK_D ─┘
    ↓
TASK_E (depends on B+C+D) ← SEQUENTIAL

Không parallelize tasks có shared file dependencies.
```

---

## 9. Session Management

### Context Preservation

```
Mỗi phase tạo:
  - implementation/phaseN/README.md     — dependency graph, verify checklist
  - implementation/phaseN/TASK_X.md    — spec + complete test file
  - implementation/phaseN/TASK_X_fix.md — fix specs nếu cần

Sau phase hoàn thành:
  - Update project_omnicast.md (memory)
  - Log: tasks done, files created, test coverage, cost estimate
  - Document next phase dependencies
```

### Compaction Safety

```
Nếu session bị compaction:
  - TASK_X.md là source of truth — đọc lại
  - project_omnicast.md có summary — đọc lại
  - KHÔNG phụ thuộc conversation history
  - Mọi decision phải trong files, không chỉ trong chat
```

---

## 10. When to Use Opus Review (exceptions)

Normally: tests pass = done. Opus review chỉ cho:

```
1. Security-critical modules (auth, API keys, injection paths)
   → Opus single-turn: "Review này cho security issues only"
   → Cost: ~$0.50

2. Cross-phase architecture changes
   → Opus single-turn: "Does this change break Phase N contract?"
   → Cost: ~$0.50

3. After 3 failed fix iterations
   → Opus diagnose root cause, viết detailed fix spec
   → Giao Haiku implement fix spec
   → Cost: ~$0.50 Opus + $0.10 Haiku

4. Final integration before production deploy
   → Opus spot-check: critical paths only, batch input
   → Cost: ~$1.00
```

**Never:** Opus multi-turn, Opus implement code, Opus routine review.

---

## 11. Cost Tracking

```
Sau mỗi phase, log vào project memory:
  - Phase N: DONE
  - Opus: $X.XX (N single-turn prompts)
  - Sonnet: $X.XX (N tasks)
  - Haiku: $X.XX (N tasks)
  - Fix iterations: N
  - Total: $X.XX
  - Tests written by Opus: N test files, N test cases
  - pytest pass rate: X/X
```

### Alerts

```
Phase > $6.00 → STOP, review what went wrong
Fix iterations > 3 per task → Opus diagnose (single-turn)
Opus multi-turn > 3 turns → STOP, consolidate to single-turn
pytest pass rate < 90% → Opus rewrite test file (spec was wrong)
```
