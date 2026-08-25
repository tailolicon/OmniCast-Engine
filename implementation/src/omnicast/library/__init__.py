"""Content library — series / episodes / platform accounts / posts.

The reup pipeline produces videos; this package answers the operator's
questions about them: which series does this video belong to, which channel
owns that series, how many episodes does the source have vs. how many were
dubbed, and which platform accounts already carry each episode.

vault.db is the SSOT (tables: series, series_episodes, platform_accounts,
episode_posts). Files stay where they are — `output/products/` for delivered
videos — the library only references them.
"""
