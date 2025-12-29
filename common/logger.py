import logging

logger = logging.getLogger("global")
logger.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s"
)

console_handler.setFormatter(formatter)

# 防止重复添加 handler
if not logger.handlers:
    logger.addHandler(console_handler)
