from typing import Any, Dict
from ruamel.yaml import YAML
import os
import shutil


class Config:
    def __init__(self, path: str = "config.yaml", default_path: str = "default_config.yaml"):
        self.path = path
        self.default_path = default_path
        self.yaml = YAML()
        self.yaml.preserve_quotes = True  # 保留引号

        # 初始化配置文件
        self._ensure_config_exists()
        self._load()

    def _ensure_config_exists(self):
        """
        如果 config.yaml 不存在：
        - 用 default_config.yaml 复制一份
        如果 default_config.yaml 也不存在则报错
        """
        if os.path.exists(self.path):
            return  # config.yaml 已存在，不处理

        if not os.path.exists(self.default_path):
            raise FileNotFoundError(
                f"配置文件不存在：{self.path}，且找不到默认文件：{self.default_path}"
            )

        # 用默认配置创建主配置
        shutil.copy(self.default_path, self.path)

    def _load(self):
        """加载 YAML 配置到内存"""
        with open(self.path, "r", encoding="utf-8") as f:
            self._cfg: Dict[str, Any] = self.yaml.load(f)

    def save(self):
        """将内存中的配置写回文件，同时尽量保持原排版"""
        with open(self.path, "w", encoding="utf-8") as f:
            self.yaml.dump(self._cfg, f)

    def get(self, section: str, key: str, default=None):
        return self._cfg.get(section, {}).get(key, default)

    def set(self, section: str, key: str, value: Any):
        if section not in self._cfg:
            self._cfg[section] = {}
        self._cfg[section][key] = value
        self.save()

    @property
    def email(self):
        return self._cfg.get("email", {})

    @property
    def glados(self):
        return self._cfg.get("glados", {})
