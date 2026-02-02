import datetime

from common.log import get_logger
from common.global_config import GlobalConfigManager, GlobalConfig

from modules.glados.core.config import GladosAccount, GladosConfigModel, GladosConfigManager
from modules.glados.core.glados import GladosClient
from modules.glados.core.data import GladosDataManager, GladosDataConfig, GladosAccountData

logger = get_logger(__name__)

def _ensure_data_accounts(
    config_accounts: list[GladosAccount],
    data_manager: GladosDataManager,
) -> None:
    """确保 data 中存在 config 里的所有账号（只增不删）"""

    data = data_manager.config
    if data is None:
        raise RuntimeError("Data config not loaded")

    data_map = {acc.id: acc for acc in data.accounts}

    changed = False

    for cfg in config_accounts:
        if cfg.id not in data_map:
            data.accounts.append(
                GladosAccountData(
                    id=cfg.id,
                    username=cfg.username,
                )
            )
            changed = True

    if changed:
        data_manager.save()

def _get_working_accounts(
    config_accounts: list[GladosAccount],
    data_manager: GladosDataManager,
) -> list[GladosAccountData]:
    """
    根据 config.accounts 构建运行时使用的 GladosAccountData 列表
    - 只返回 config 中存在的账号
    - 复用 data 中已有数据
    """

    data = data_manager.config
    if data is None:
        raise RuntimeError("Data config not loaded")

    data_map = {acc.id: acc for acc in data.accounts}

    working_accounts: list[GladosAccountData] = []

    for cfg in config_accounts:
        acc = data_map.get(cfg.id)
        if acc is None:
            # 理论上不会发生（ensure 已处理）
            acc = GladosAccountData(
                id=cfg.id,
                username=cfg.username,
            )
            data.accounts.append(acc)

        working_accounts.append(acc)

    return working_accounts


def main():

    global_config_manager = GlobalConfigManager(r"./config/global.yaml")
    # 全局配置
    global_config = global_config_manager.read()
    logger.info(f"Global Config Init OK")

    glados_config_manager = GladosConfigManager(r"./config/glados.yaml")
    # 工具配置
    glados_config = glados_config_manager.read()
    logger.info(f"Glados Config Init OK")

    data_manager = GladosDataManager(r"./modules/glados/data/date.yaml")
    # 简单数据存储
    data = data_manager.read()
    logger.info(f"Data Init OK")

    if glados_config_manager and glados_config_manager and data_manager and glados_config:
        _ensure_data_accounts(glados_config.accounts, data_manager)
        working_accounts = _get_working_accounts(glados_config.accounts, data_manager)

        try:
            client = GladosClient(global_config.proxy, working_accounts, global_config)
            client.checkin()
            client.send_result_notification()
            # client.code()
            # client.cake()
            data_manager.save()
        except Exception as e:
            pass

if __name__ == "__main__":
    main()