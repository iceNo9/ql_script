# tasks/task_glados.py
from utils.log import get_logger
from utils.config import GlobalConfigManager

from modules.glados.core.config import GladosConfigManager
from modules.glados.core.glados import GladosClient

logger = get_logger(__name__)


def main():
    """GLaDOS 签到任务主入口"""
    
    # 1. 加载全局配置
    global_config_manager = GlobalConfigManager("./config/global.yaml")
    global_config = global_config_manager.read()
    logger.info("全局配置加载完成")
    
    # 2. 加载 GLaDOS 配置
    glados_config_manager = GladosConfigManager("./config/glados.yaml")
    glados_config = glados_config_manager.read()
    
    if not glados_config:
        logger.error("GLaDOS 配置加载失败")
        return
    
    logger.info(f"GLaDOS 配置加载完成，共 {len(glados_config.accounts)} 个账号")
    
    # 3. 创建客户端（自动初始化数据库表）
    client = GladosClient(
        global_config=global_config,
        glados_config=glados_config,
    )
    
    # 4. 执行操作
    try:
        # 执行签到
        logger.info("=" * 50)
        checkin_results = client.checkin()
        logger.info(f"签到完成: 成功 {len([r for r in checkin_results if r.success])}/{len(checkin_results)}")
        
        # 执行礼品码兑换
        logger.info("=" * 50)
        code_results = client.code()
        logger.info(f"礼品码兑换完成: 成功 {len([r for r in code_results if r.success])}/{len(code_results)}")
        
        # 执行蛋糕兑换
        logger.info("=" * 50)
        cake_results = client.cake()
        logger.info(f"蛋糕兑换完成: 成功 {len([r for r in cake_results if r.success])}/{len(cake_results)}")
        
        # 执行积分续费（根据配置规则）
        logger.info("=" * 50)
        exchange_results = client.exchange()
        logger.info(f"积分续费完成: 成功 {len(exchange_results)} 笔")
        
        # 收集账户信息
        logger.info("=" * 50)
        account_infos = client.collect_account_infos()
        logger.info(f"账户信息收集完成，共 {len(account_infos)} 个账户")
        
        # 发送通知
        notifier = client.get_notifier()
        notifier.send()
        logger.info("通知发送完成")
        
    except Exception as e:
        logger.error(f"GLaDOS 运行中发生错误: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()