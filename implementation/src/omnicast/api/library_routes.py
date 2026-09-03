"""Content-library API (series / episodes / platform accounts / posts).

Isolated router, included by server.py in its own try-block like reup_routes:
a broken import here must not take the whole backend down.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from omnicast.library import backfill, store

library_router = APIRouter(prefix="/api/library", tags=["library"])


def _400(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ── overview / series ───────────────────────────────────────────────────────

@library_router.get("/overview")
def library_overview() -> dict:
    return {
        "series": store.series_overview(),
        "accounts": store.list_accounts(),
    }


@library_router.get("/series")
def library_series_list() -> dict:
    return {"series": store.series_overview()}


class SeriesCreate(BaseModel):
    title: str = Field(..., min_length=1)
    series_id: str | None = None
    kind: str = "series"          # 'series' (phim bộ) | 'single' (gom video lẻ)
    channel_id: str = ""
    source_url: str = ""
    source_author: str = ""
    title_source: str = ""
    note: str = ""


@library_router.post("/series")
def library_series_create(body: SeriesCreate) -> dict:
    if body.kind not in store.SERIES_KINDS:
        raise HTTPException(status_code=400, detail=f"kind phải thuộc {store.SERIES_KINDS}")
    try:
        return store.create_series(
            body.title,
            series_id=body.series_id or None,
            kind=body.kind,
            channel_id=body.channel_id,
            source_url=body.source_url,
            source_author=body.source_author,
            title_source=body.title_source,
            note=body.note,
        )
    except ValueError as exc:
        raise _400(exc)


class SeriesPatch(BaseModel):
    title: str | None = None
    title_source: str | None = None
    kind: str | None = None
    channel_id: str | None = None
    source_url: str | None = None
    source_author: str | None = None
    source_mix_id: str | None = None
    status: str | None = None
    note: str | None = None


@library_router.get("/series/{series_id}")
def library_series_detail(series_id: str) -> dict:
    try:
        payload = store.episodes_with_posts(series_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Không có series {series_id}")
    channel_id = str(payload["series"].get("channel_id") or "")
    accounts = store.list_accounts(channel_id=channel_id) if channel_id else []
    payload["accounts"] = accounts or store.list_accounts()
    return payload


@library_router.patch("/series/{series_id}")
def library_series_patch(series_id: str, body: SeriesPatch) -> dict:
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Không có gì để sửa")
    if "kind" in fields and fields["kind"] not in store.SERIES_KINDS:
        raise HTTPException(status_code=400, detail=f"kind phải thuộc {store.SERIES_KINDS}")
    try:
        return store.update_series(series_id, **fields)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Không có series {series_id}")
    except ValueError as exc:
        raise _400(exc)


@library_router.delete("/series/{series_id}")
def library_series_delete(series_id: str) -> dict:
    if store.get_series(series_id) is None:
        raise HTTPException(status_code=404, detail=f"Không có series {series_id}")
    store.delete_series(series_id)
    return {"deleted": series_id}


# ── source sync (Douyin mix) ────────────────────────────────────────────────

class SyncSourceRequest(BaseModel):
    cookies: dict[str, str] = Field(default_factory=dict)
    proxy: str = ""


@library_router.post("/series/{series_id}/sync-source")
async def library_series_sync_source(
    series_id: str, body: SyncSourceRequest | None = None
) -> dict:
    from omnicast.library.source_sync import SourceSyncError, sync_series_source

    body = body or SyncSourceRequest()
    try:
        return await sync_series_source(
            series_id, cookies=body.cookies, proxy=body.proxy
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Không có series {series_id}")
    except SourceSyncError as exc:
        raise _400(exc)
    except Exception as exc:  # vendor client raises plain RuntimeErrors on auth walls
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}")


# ── episodes ────────────────────────────────────────────────────────────────

class EpisodeUpsert(BaseModel):
    ep_no: int = Field(..., ge=1)
    title: str = ""
    title_vi: str = ""
    source_aweme_id: str = ""
    source_url: str = ""
    reup_job_id: str = ""
    product_dir: str = ""
    video_path: str = ""
    status: str | None = None
    note: str = ""


@library_router.post("/series/{series_id}/episodes")
def library_episode_upsert(series_id: str, body: EpisodeUpsert) -> dict:
    if body.status and body.status not in store.EPISODE_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"status phải thuộc {store.EPISODE_STATUSES}"
        )
    try:
        return store.upsert_episode(
            series_id, body.ep_no,
            title=body.title, title_vi=body.title_vi,
            source_aweme_id=body.source_aweme_id, source_url=body.source_url,
            reup_job_id=body.reup_job_id, product_dir=body.product_dir,
            video_path=body.video_path, status=body.status, note=body.note,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Không có series {series_id}")
    except ValueError as exc:
        raise _400(exc)


class EpisodePatch(BaseModel):
    ep_no: int | None = None
    title: str | None = None
    title_vi: str | None = None
    source_aweme_id: str | None = None
    source_url: str | None = None
    reup_job_id: str | None = None
    product_dir: str | None = None
    video_path: str | None = None
    status: str | None = None
    note: str | None = None


@library_router.patch("/episodes/{episode_id}")
def library_episode_patch(episode_id: str, body: EpisodePatch) -> dict:
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Không có gì để sửa")
    if "status" in fields and fields["status"] not in store.EPISODE_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"status phải thuộc {store.EPISODE_STATUSES}"
        )
    try:
        return store.update_episode(episode_id, **fields)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Không có tập {episode_id}")
    except ValueError as exc:
        raise _400(exc)


@library_router.delete("/episodes/{episode_id}")
def library_episode_delete(episode_id: str) -> dict:
    if store.get_episode(episode_id) is None:
        raise HTTPException(status_code=404, detail=f"Không có tập {episode_id}")
    store.delete_episode(episode_id)
    return {"deleted": episode_id}


# ── platform accounts ───────────────────────────────────────────────────────

@library_router.get("/accounts")
def library_accounts(platform: str | None = None, channel_id: str | None = None) -> dict:
    return {"accounts": store.list_accounts(platform=platform, channel_id=channel_id)}


class AccountCreate(BaseModel):
    platform: str
    name: str = Field(..., min_length=1)
    url: str = ""
    channel_id: str = ""
    external_id: str = ""
    note: str = ""


@library_router.post("/accounts")
def library_account_create(body: AccountCreate) -> dict:
    try:
        return store.create_account(
            body.platform, body.name,
            url=body.url, channel_id=body.channel_id,
            external_id=body.external_id, note=body.note,
        )
    except ValueError as exc:
        raise _400(exc)


class AccountPatch(BaseModel):
    name: str | None = None
    url: str | None = None
    channel_id: str | None = None
    external_id: str | None = None
    status: str | None = None
    note: str | None = None


@library_router.patch("/accounts/{account_id}")
def library_account_patch(account_id: str, body: AccountPatch) -> dict:
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Không có gì để sửa")
    try:
        return store.update_account(account_id, **fields)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Không có tài khoản {account_id}")
    except ValueError as exc:
        raise _400(exc)


@library_router.delete("/accounts/{account_id}")
def library_account_delete(account_id: str) -> dict:
    if store.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail=f"Không có tài khoản {account_id}")
    store.delete_account(account_id)
    return {"deleted": account_id}


class ReconcileRequest(BaseModel):
    limit: int = Field(500, ge=1, le=2000)
    apply: bool = True


@library_router.post("/accounts/{account_id}/reconcile-youtube")
def library_reconcile_youtube(account_id: str, body: ReconcileRequest | None = None) -> dict:
    from omnicast.library.youtube_reconcile import ReconcileError, reconcile_youtube_account

    body = body or ReconcileRequest()
    try:
        return reconcile_youtube_account(account_id, limit=body.limit, apply=body.apply)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Không có tài khoản {account_id}")
    except ReconcileError as exc:
        raise _400(exc)


# ── posts (tick / untick) ───────────────────────────────────────────────────

class PostSet(BaseModel):
    status: str = "posted"
    post_url: str = ""
    external_post_id: str = ""
    posted_at: str = ""
    note: str = ""


@library_router.put("/episodes/{episode_id}/posts/{account_id}")
def library_post_set(episode_id: str, account_id: str, body: PostSet | None = None) -> dict:
    body = body or PostSet()
    try:
        return store.set_post(
            episode_id, account_id,
            status=body.status, post_url=body.post_url,
            external_post_id=body.external_post_id,
            posted_at=body.posted_at, note=body.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@library_router.delete("/episodes/{episode_id}/posts/{account_id}")
def library_post_delete(episode_id: str, account_id: str) -> dict:
    store.delete_post(episode_id, account_id)
    return {"deleted": f"{episode_id}×{account_id}"}


# ── backfill ────────────────────────────────────────────────────────────────

@library_router.post("/backfill/scan")
def library_backfill_scan() -> dict:
    return backfill.scan()


class BackfillCommit(BaseModel):
    groups: list[dict] = Field(default_factory=list)


@library_router.post("/backfill/commit")
def library_backfill_commit(body: BackfillCommit) -> dict:
    return backfill.commit({"groups": body.groups})


# ── reup job → episode sync (manual trigger) ────────────────────────────────

@library_router.post("/jobs/{job_id}/sync")
def library_job_sync(job_id: str) -> dict:
    episode = store.sync_episode_from_job(job_id)
    if episode is None:
        raise HTTPException(
            status_code=404,
            detail="Job chưa gắn với tập nào (chọn series khi tạo job, "
                   "hoặc sync nguồn để hệ thống tự khớp theo aweme_id).",
        )
    return episode
