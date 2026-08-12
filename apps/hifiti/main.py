# modules/hifiti/main.py

from utils.log import get_logger
from utils.config import GlobalConfigManager

from apps.hifiti.core.config import ConfigManager
from apps.hifiti.core.app import App

logger = get_logger(__name__)

MODULE_NAME = "HiFiTi"


def main():
    """HiFiTi 签到任务主入口"""
    
    # 1. 加载全局配置
    global_config_manager = GlobalConfigManager("./config/global.yaml")
    global_config = global_config_manager.read()
    logger.info(f"[{MODULE_NAME}] 全局配置加载完成")
    
    # 2. 加载 HiFiTi 配置
    hifiti_config_manager = ConfigManager("./config/hifiti.yaml")
    hifiti_config = hifiti_config_manager.read()
    
    if not hifiti_config:
        logger.error(f"[{MODULE_NAME}] 配置加载失败")
        return
    
    # 获取账号列表
    accounts = [{"username": acc.username, "password": acc.password} for acc in hifiti_config.accounts]
    logger.info(f"[{MODULE_NAME}] 配置加载完成，共 {len(accounts)} 个账号")
    
    # 3. 创建客户端（自动初始化数据库表）
    client = App(
        global_config=global_config,
        accounts=accounts,
    )
    
    # 4. 执行操作
    try:
        # 执行签到
        logger.info("=" * 50)
        sign_results = client.sign()
        logger.info(f"[{MODULE_NAME}] 签到完成: 成功 {len([r for r in sign_results if r.success])}/{len(sign_results)}")

        # 获取用户信息
        logger.info("=" * 50)
        user_infos = client.get_user_info()
        logger.info(f"[{MODULE_NAME}] 用户信息获取完成，共 {len(user_infos)} 个账户")
        
        # 收集账户信息
        logger.info("=" * 50)
        account_infos = client.collect_account_infos()
        logger.info(f"[{MODULE_NAME}] 账户信息收集完成，共 {len(account_infos)} 个账户")
        
        # 发送通知
        notifier = client.get_notifier()
        notifier.send()
        logger.info(f"[{MODULE_NAME}] 通知发送完成")
        
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] 运行中发生错误: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()