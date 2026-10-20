"""应用日志配置：统一输出简洁、可按级别筛选的中文运行信息。"""

from logging.config import dictConfig


def configure_logging(log_level: str) -> None:
    """配置控制台日志；DEBUG 只展开本项目日志，避免第三方库刷屏。"""
    normalized_level = log_level.upper()
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "console": {
                    "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "console",
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"handlers": ["console"], "level": "WARNING"},
            "loggers": {
                "app": {"handlers": ["console"], "level": normalized_level, "propagate": False},
                "uvicorn.error": {"handlers": ["console"], "level": "INFO", "propagate": False},
                "uvicorn.access": {"handlers": ["console"], "level": "INFO", "propagate": False},
            },
        }
    )
