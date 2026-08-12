import datetime

from utils.log import get_logger
from utils.config import GlobalConfigManager, GlobalConfig

from apps.ikuuu.core.config import IkuuuAccount, IkuuuConfigModel, IkuuuConfigManager
from apps.ikuuu.core.ikuuu import IkuuuClient
from apps.ikuuu.core.data import IkuuuDataManager, IkuuuDataConfig, IkuuuAccountData

logger = get_logger(__name__)

def _ensure_data_accounts(
    config_accounts: list[IkuuuAccount],
    data_manager: IkuuuDataManager,
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
                IkuuuAccountData(
                    id=cfg.id,
                    username=cfg.username,
                    password=cfg.password,
                )
            )
            changed = True

    if changed:
        data_manager.save()

def _get_working_accounts(
    config_accounts: list[IkuuuAccount],
    data_manager: IkuuuDataManager,
) -> list[IkuuuAccountData]:
    """
    根据 config.accounts 构建运行时使用的 IkuuuAccountData 列表
    - 只返回 config 中存在的账号
    - 复用 data 中已有数据
    """

    data = data_manager.config
    if data is None:
        raise RuntimeError("Data config not loaded")

    data_map = {acc.id: acc for acc in data.accounts}

    working_accounts: list[IkuuuAccountData] = []

    for cfg in config_accounts:
        acc = data_map.get(cfg.id)
        if acc is None:
            # 理论上不会发生（ensure 已处理）
            acc = IkuuuAccountData(
                id=cfg.id,
                username=cfg.username,
                password=cfg.password,
            )
            data.accounts.append(acc)

        working_accounts.append(acc)

    return working_accounts


def main():

    global_config_manager = GlobalConfigManager(r"./config/global.yaml")
    # 全局配置
    global_config = global_config_manager.read()
    logger.info(f"Global Config Init OK")

    ikuuu_config_manager = IkuuuConfigManager(r"./config/ikuuu.yaml")
    # 工具配置
    ikuuu_config = ikuuu_config_manager.read()
    logger.info(f"Ikuuu Config Init OK")

    data_manager = IkuuuDataManager(r"./modules/ikuuu/data/data.yaml")
    # 简单数据存储
    data = data_manager.read()
    logger.info(f"Data Init OK")

    if ikuuu_config_manager and ikuuu_config_manager and data_manager and ikuuu_config:
        _ensure_data_accounts(ikuuu_config.accounts, data_manager)
        working_accounts = _get_working_accounts(ikuuu_config.accounts, data_manager)

        try:
            client = IkuuuClient(global_config.proxy, working_accounts, global_config)
            client.checkin()            
            client.collect_account_infos()
            notify = client.get_notifier()
            notify.send()
            data_manager.save()
        except Exception as e:
            logger.error(f"Ikuuu 运行中发生错误: {e}")
            pass

if __name__ == "__main__":
    main()