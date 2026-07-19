# TASK F FIX: Storage — structlog format + sync I/O

> **Severity:** MINOR — structured logging broken, 1 sync I/O in async context
> **Files:** `src/omnicast/storage/health.py`, `src/omnicast/storage/cleanup.py`
> **Estimated time:** 10 min

---

## 1. Fix `health.py` — 1 structlog format

```python
# FIND (line ~139):
                        logger.warning(
                            "NAS unavailable after %d consecutive failures, switching to local",
                            self.consecutive_failures,
                        )

# REPLACE WITH:
                        logger.warning(
                            "NAS unavailable, switching to local",
                            consecutive_failures=self.consecutive_failures,
                        )
```

---

## 2. Fix `cleanup.py` — 7 structlog formats + 1 sync I/O

### 2a. `clean_temp` — lines ~85, ~90

```python
# FIND:
                    logger.info(
                        "GC deleted %s, age=%.1fh", file_path.name, age_hours
                    )

# REPLACE WITH:
                    logger.info(
                        "GC deleted temp file",
                        filename=file_path.name,
                        age_hours=round(age_hours, 1),
                    )
```

```python
# FIND:
                logger.warning("GC failed to delete %s: %s", file_path.name, e)

# REPLACE WITH:
                logger.warning("GC failed to delete temp file", filename=file_path.name, error=str(e))
```

### 2b. `clean_empty_dirs` — sync I/O fix + 2 structlog fixes

```python
# FIND (line ~125-126):
                contents = list(dir_path.iterdir())
                if not contents:

# REPLACE WITH:
                contents = await asyncio.to_thread(lambda p=dir_path: list(p.iterdir()))
                if not contents:
```

Note: `lambda p=dir_path:` captures current value, avoids closure-in-loop issue.

```python
# FIND:
                    logger.info("GC deleted empty directory: %s", dir_path)

# REPLACE WITH:
                    logger.info("GC deleted empty directory", path=str(dir_path))
```

```python
# FIND:
                logger.warning(
                    "GC failed to delete empty dir %s: %s", dir_path, e
                )

# REPLACE WITH:
                logger.warning(
                    "GC failed to delete empty dir",
                    path=str(dir_path),
                    error=str(e),
                )
```

### 2c. `clean_orphaned_renders` — 2 structlog fixes

```python
# FIND:
                        logger.info(
                            "GC deleted orphaned render: %s", file_path.name
                        )

# REPLACE WITH:
                        logger.info(
                            "GC deleted orphaned render",
                            filename=file_path.name,
                        )
```

```python
# FIND:
                    except Exception as e:
                        logger.warning(
                            "GC failed to delete orphaned %s: %s",
                            file_path.name,
                            e,
                        )

# REPLACE WITH:
                    except Exception as e:
                        logger.warning(
                            "GC failed to delete orphaned render",
                            filename=file_path.name,
                            error=str(e),
                        )
```

### 2d. `run` — 1 structlog fix

```python
# FIND:
        logger.info(
            "GC complete: deleted %d files, freed %.1fMB, %.1f%% free",
            total_deleted,
            total_freed / (1024 * 1024),
            free_pct,
        )

# REPLACE WITH:
        logger.info(
            "GC complete",
            deleted_count=total_deleted,
            freed_mb=round(total_freed / (1024 * 1024), 1),
            free_pct=round(free_pct, 1),
        )
```

---

## Summary: 9 changes total

| File | Change | Count |
|------|--------|-------|
| `health.py` | structlog `%s` → keyword args | 1 |
| `cleanup.py` | structlog `%s` → keyword args | 7 |
| `cleanup.py` | sync `iterdir()` → `asyncio.to_thread` | 1 |

## Verify

```bash
uv run pytest tests/unit/test_storage.py -v
uv run pyright src/omnicast/storage/
```

## DO NOT

- Do NOT change any logic or algorithms
- Do NOT touch `file_ops.py`, `paths.py`, `__init__.py`
- Do NOT add new methods or classes
- Do NOT refactor function signatures
