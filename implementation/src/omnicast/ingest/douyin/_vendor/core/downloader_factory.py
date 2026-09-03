from typing import Any, Optional

from omnicast.ingest.douyin._vendor.auth import CookieManager
from omnicast.ingest.douyin._vendor.config import ConfigLoader
from omnicast.ingest.douyin._vendor.control import QueueManager, RateLimiter, RetryHandler
from omnicast.ingest.douyin._vendor.core.api_client import DouyinAPIClient
from omnicast.ingest.douyin._vendor.core.downloader_base import BaseDownloader
from omnicast.ingest.douyin._vendor.core.live_downloader import LiveDownloader
from omnicast.ingest.douyin._vendor.core.live_replay_downloader import LiveReplayDownloader
from omnicast.ingest.douyin._vendor.core.mix_downloader import MixDownloader
from omnicast.ingest.douyin._vendor.core.music_downloader import MusicDownloader
from omnicast.ingest.douyin._vendor.core.user_downloader import UserDownloader
from omnicast.ingest.douyin._vendor.core.video_downloader import VideoDownloader
from omnicast.ingest.douyin._vendor.storage import Database, FileManager
from omnicast.ingest.douyin._vendor.utils.logger import setup_logger

logger = setup_logger("DownloaderFactory")


class DownloaderFactory:
    @staticmethod
    def create(
        url_type: str,
        config: ConfigLoader,
        api_client: DouyinAPIClient,
        file_manager: FileManager,
        cookie_manager: CookieManager,
        database: Optional[Database] = None,
        rate_limiter: Optional[RateLimiter] = None,
        retry_handler: Optional[RetryHandler] = None,
        queue_manager: Optional[QueueManager] = None,
        progress_reporter: Optional[Any] = None,
        job_id: Optional[str] = None,
    ) -> Optional[BaseDownloader]:

        common_args = {
            "config": config,
            "api_client": api_client,
            "file_manager": file_manager,
            "cookie_manager": cookie_manager,
            "database": database,
            "rate_limiter": rate_limiter,
            "retry_handler": retry_handler,
            "queue_manager": queue_manager,
            "progress_reporter": progress_reporter,
            "job_id": job_id,
        }

        if url_type == "video":
            return VideoDownloader(**common_args)
        elif url_type == "user":
            return UserDownloader(**common_args)
        elif url_type == "gallery":
            return VideoDownloader(**common_args)
        elif url_type == "collection":
            return MixDownloader(**common_args)
        elif url_type == "music":
            return MusicDownloader(**common_args)
        elif url_type == "live":
            return LiveDownloader(**common_args)
        elif url_type == "live_replay":
            return LiveReplayDownloader(**common_args)
        elif url_type == "short":
            logger.error(
                "Short URL was not resolved before dispatching. "
                "Please call api_client.resolve_short_url() first."
            )
            return None
        else:
            logger.error("Unsupported URL type: %s", url_type)
            return None
