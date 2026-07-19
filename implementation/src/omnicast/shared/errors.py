"""Custom exceptions cho OmniCast Engine.

Hierarchy:
  OmnicastError
  ├── ConfigError
  ├── DatabaseError
  │   └── NotFoundError
  ├── QueueError
  ├── CacheError
  ├── StorageError
  │   └── NASUnavailableError
  ├── RateLimitError
  ├── CircuitOpenError
  ├── UploadError
  ├── UploadPipelineError
  ├── ComplianceError
  ├── AgentError
  ├── DiscoveryError
  ├── MediaError
  └── AnalyticsError
"""


class OmnicastError(Exception):
    """Base exception. Tất cả custom exceptions kế thừa từ đây."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigError(OmnicastError): ...


class DatabaseError(OmnicastError): ...


class NotFoundError(DatabaseError): ...


class QueueError(OmnicastError): ...


class CacheError(OmnicastError): ...


class StorageError(OmnicastError): ...


class NASUnavailableError(StorageError): ...


class RateLimitError(OmnicastError): ...


class QuotaExhausted(RateLimitError): ...


class QuotaExceeded(RateLimitError): ...


class CircuitOpenError(OmnicastError): ...


class UploadError(OmnicastError): ...


class UploadPipelineError(OmnicastError): ...


class ComplianceError(OmnicastError): ...


class AgentError(OmnicastError): ...


class DiscoveryError(OmnicastError): ...


class MediaError(OmnicastError): ...


class AnalyticsError(OmnicastError): ...
