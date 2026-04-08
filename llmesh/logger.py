import logging


def get_logger(name: str = "llmesh") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(handler)
        logger.propagate = False  # 不向 root logger 传播，避免重复输出
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)
    return logger
