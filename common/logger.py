import logging

# 创建 logger
logger = logging.getLogger("global")
logger.setLevel(logging.DEBUG)

# 控制台 handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# 创建控制台 formatter
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
console_handler.setFormatter(formatter)

logger.addHandler(console_handler)
