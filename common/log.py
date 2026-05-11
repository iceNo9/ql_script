# common\log.py
import logging
import threading

_lock = threading.Lock()
_inited = False

APP_NAME = "ql_script"


def _init_logging():
    global _inited
    if _inited:
        return

    with _lock:
        if _inited:
            return

        # 根 logger：压低第三方库噪音
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.WARNING)

        # 应用 logger
        app_logger = logging.getLogger(APP_NAME)
        app_logger.setLevel(logging.DEBUG)
        app_logger.propagate = False

        if not app_logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)

            # ⭐ 关键在这里：pathname + lineno
            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] "
                "%(pathname)s:%(lineno)d - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

            console_handler.setFormatter(formatter)
            app_logger.addHandler(console_handler)

        _inited = True


def get_logger(name: str | None = None) -> logging.Logger:
    _init_logging()

    if name is None:
        logger_name = APP_NAME
    else:
        if name.startswith(APP_NAME + "."):
            logger_name = name
        else:
            logger_name = f"{APP_NAME}.{name}"

    return logging.getLogger(logger_name)
