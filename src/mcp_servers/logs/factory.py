from copilot.config import LogsIntegration

from .backend import LogBackend
from .file_backend import FileLogBackend
from .loki_backend import LokiLogBackend


def build_backend(cfg: LogsIntegration) -> LogBackend:
    if cfg.backend == "loki":
        return LokiLogBackend(cfg.loki, cfg.service_label, cfg.fields)
    return FileLogBackend(cfg.file.directory, cfg.fields)
