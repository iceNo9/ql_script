# modules/southplus/main.py

from utils.log import get_logger
from utils.config import GlobalConfigManager

from apps.southplus.core.config import ConfigManager
from apps.southplus.core.app import App

logger = get_logger(__name__)

MODULE_NAME = "南+"


def main():
    """southplus 任务调度主入口"""

    # =========================
    # 1. 加载全局配置
    # =========================
    global_config_manager = GlobalConfigManager("./config/global.yaml")
    global_config = global_config_manager.read()

    logger.info(f"[{MODULE_NAME}] 全局配置加载完成")

    # =========================
    # 2. 加载 southplus 配置
    # =========================
    config_manager = ConfigManager("./config/southplus.yaml")
    config = config_manager.read()

    if not config:
        logger.error(f"[{MODULE_NAME}] 配置加载失败")
        return

    usernames = [acc.username for acc in config.accounts]

    logger.info(f"[{MODULE_NAME}] 账号加载完成，共 {len(usernames)} 个: {usernames}")

    # =========================
    # 3. 创建 APP
    # =========================
    app = App(
        global_config=global_config,
        config_manager=config_manager,
    )

    # =========================
    # 4. 执行任务
    # =========================
    try:
        logger.info("=" * 50)
        logger.info("[任务] 开始执行日常和周常任务")

        task_results = app.run()

        # 打印任务执行结果
        success_count = len([r for r in task_results if r.message and "无任务执行" not in r.message])
        logger.info(f"[任务] 执行完成，共执行 {success_count} 个任务")

        # 打印每个用户的任务状态
        for result in task_results:
            logger.info(f"  - {result.username}: {result.message}")

        # =========================
        # 5. 发送邮件通知（按需发送，同一天只发一次）
        # =========================
        logger.info("=" * 50)
        logger.info("[邮件] 检查是否需要发送报告")

        sent = app.send_report_if_needed()

        if sent:
            logger.info(f"[{MODULE_NAME}] 邮件报告发送成功")
        else:
            logger.info(f"[{MODULE_NAME}] 今日已发送过邮件报告，跳过")

        # =========================
        # 6. 打印账户信息摘要
        # =========================
        logger.info("=" * 50)
        logger.info("[账户] 当前账户信息摘要")

        for acc in app._account_infos:
            change = acc.sp_coin - acc.last_sp_coin
            change_str = f"+{change}" if change >= 0 else str(change)
            logger.info(
                f"  - {acc.username}: "
                f"当前SP币={acc.sp_coin}, "
                f"上次SP币={acc.last_sp_coin}, "
                f"变化={change_str}, "
                f"日常={acc.daily_count}, "
                f"周常={acc.weekly_count}"
            )

    except Exception as e:
        logger.error(f"[{MODULE_NAME}] 运行失败: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()