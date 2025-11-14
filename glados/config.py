from typing import Any, Dict
from ruamel.yaml import YAML

class Config:
    def __init__(self, path: str = "config.yaml"):
        self.path = path
        self.yaml = YAML()
        self.yaml.preserve_quotes = True  # 保留引号
        self._load()

    def _load(self):
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
