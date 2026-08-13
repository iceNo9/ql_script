"""
数据加解密工具。

每个应用通过 Crypto 实例持有自己的加密密钥，
不同应用之间互不影响。
"""

from cryptography.fernet import Fernet, InvalidToken


class Crypto:
    """Fernet 数据加解密器。"""

    def __init__(self, key: str):
        """
        初始化加密器。

        Args:
            key: Fernet 加密密钥。

        Raises:
            ValueError: 密钥无效。
        """
        try:
            self._cipher = Fernet(key.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise ValueError("无效的 Fernet 加密密钥") from exc

    def encrypt(self, value: str) -> str:
        """
        加密字符串。

        Args:
            value: 待加密的字符串。

        Returns:
            str: 加密后的字符串。
        """
        if not value:
            return value

        return self._cipher.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        """
        解密字符串。

        Args:
            value: 待解密的字符串。

        Returns:
            str: 解密后的字符串。

        Raises:
            ValueError: 数据解密失败。
        """
        if not value:
            return value

        try:
            return self._cipher.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("数据解密失败，密钥错误或数据已损坏") from exc


def generate_key() -> str:
    """
    生成 Fernet 加密密钥。

    Returns:
        str: Base64 编码的 Fernet 密钥。
    """
    return Fernet.generate_key().decode("utf-8")


__all__ = [
    "Crypto",
    "generate_key",
]
