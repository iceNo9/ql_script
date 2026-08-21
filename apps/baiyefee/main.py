# apps/baiyefee/main.py

import sys

from apps.baiyefee.core.config import load_baiyefee_config
from apps.baiyefee.core.repositories import init_database
from apps.baiyefee.core.server import BaiyefeeClient
from utils.config import get_config_path, load_global_config
from utils.log import get_logger
from utils.notify import send
from utils.paths import logs

logger = get_logger(name="baiyefee_main", log_dir=logs(), fmt_type="detailed")


def main():
    """Baiyefee 签到任务主入口"""
    client: BaiyefeeClient | None = None

    try:
        # 1. 加载全局配置
        logger.info("开始加载全局配置...")
        global_config = load_global_config()
        logger.info("全局配置加载完成")

        # 2. 加载 Baiyefee 配置
        logger.info("开始加载 Baiyefee 配置...")
        baiyefee_config = load_baiyefee_config()
        if not baiyefee_config:
            message = (
                f"Baiyefee 配置加载失败，请检查 {get_config_path('baiyefee')} 文件"
            )
            logger.error(message)
            send("Baiyefee 任务失败", message, SMTP_HTML="false")
            sys.exit(1)

        # 如果用户列表为空,跳过执行
        if not baiyefee_config.accounts:
            message = (
                f"Baiyefee 用户列表为空，请检查 {get_config_path('baiyefee')} 文件"
            )
            logger.error(message)
            send("Baiyefee 任务跳过", message, SMTP_HTML="false")
            sys.exit(1)

        logger.info(f"Baiyefee 配置加载完成，共 {len(baiyefee_config.accounts)} 个账号")

        # 3. 初始化数据库, 创建客户端
        init_database()

        client = BaiyefeeClient(
            global_config=global_config,
            baiyefee_config=baiyefee_config,
        )

        # 4. 执行操作
        _execute_operations(client)

    except KeyboardInterrupt:
        logger.info("用户中断执行，正在退出...")
        sys.exit(0)

    except FileNotFoundError as e:
        logger.error(f"配置文件不存在: {e}")
        sys.exit(1)

    except PermissionError as e:
        logger.error(f"文件权限不足: {e}")
        sys.exit(1)

    except ConnectionError as e:
        logger.error(f"网络连接失败: {e}")
        sys.exit(1)

    except Exception:
        logger.exception("程序异常退出: ")
        sys.exit(1)

    finally:
        if client and hasattr(client, "close"):
            try:
                client.close()
            except Exception:
                logger.exception("关闭 client 时出错: ")
        logger.info("资源清理完成")


def _execute_operations(client: BaiyefeeClient) -> None:
    """
    执行所有 Baiyefee 操作

    Args:
        client: Baiyefee 客户端实例
    """
    try:
        # ==================== 1. 获取签到信息 ====================
        logger.info("=" * 50)
        logger.info("开始获取全部账号签到信息...")
        try:
            sign_info_results = client.get_sign_info_all()
            total_count = len(sign_info_results)
            success_count = sum(
                1 for r in sign_info_results.values() if r is not None and r.success
            )
            logger.info(f"签到信息获取完成: 成功 {success_count}/{total_count}")

            # 记录签到信息详情
            for username, result in sign_info_results.items():
                if result is None:
                    logger.warning(f"获取签到信息失败 [{username}]: 返回结果为 None")
                elif result.success:
                    logger.info(
                        f"账号 {username}: 今日签到可获得 {result.checkin_points} 积分, "
                        f"当前总积分 {result.points}, "
                        f"{'可签到' if result.can_checkin else '已签到'}"
                    )
                else:
                    logger.warning(f"获取签到信息失败 [{username}]: {result.error}")

        except Exception:
            logger.exception("获取签到信息失败: ")
            raise  # 签到信息获取是基础操作，失败则终止

        # ==================== 2. 签到 ====================
        logger.info("=" * 50)
        logger.info("开始执行签到...")
        try:
            checkin_results = client.checkin_all()

            # 获取所有成功的结果（排除 None）
            success_results = [
                r for r in checkin_results.values() if r is not None and r.success
            ]
            success_count = len(success_results)
            total_count = len(checkin_results)

            logger.info(f"签到完成: 成功 {success_count}/{total_count}")

            # 记录签到结果
            for username, result in checkin_results.items():
                if result is None:
                    logger.warning(f"签到失败 [{username}]: 返回结果为 None")
                elif result.success:
                    if result.already_checked:
                        logger.info(
                            f"账号 {username}: 今日已签到，当前总积分 {result.points}"
                        )
                    else:
                        logger.info(
                            f"账号 {username}: 签到成功，获得 {result.checkin_points} 积分，"
                            f"当前总积分 {result.points}"
                        )
                else:
                    logger.warning(f"签到失败 [{username}]: {result.error}")

        except Exception:
            logger.exception("签到失败，终止执行")
            raise  # 签到是核心功能，失败则终止

        # ==================== 3. 获取用户数据 ====================
        logger.info("=" * 50)
        logger.info("开始获取全部账号用户数据...")
        try:
            user_data_results = client.get_user_data_all()
            total_count = len(user_data_results)
            success_count = sum(
                1 for r in user_data_results.values() if r is not None and r.success
            )
            logger.info(f"用户数据获取完成: 成功 {success_count}/{total_count}")

            # 记录用户数据详情
            for username, result in user_data_results.items():
                if result is None:
                    logger.warning(f"获取用户数据失败 [{username}]: 返回结果为 None")
                elif result.success:
                    logger.info(
                        f"账号 {username}: 当前积分 {result.points}, 余额 {result.money:.2f}"
                    )
                else:
                    logger.warning(f"获取用户数据失败 [{username}]: {result.error}")

        except Exception:
            logger.exception("获取用户数据失败，继续执行后续任务")

        # ==================== 4. 报告导出 ====================
        logger.info("=" * 50)
        logger.info("开始执行报告导出...")
        try:
            html = client.build_report_html()
            logger.info("报告导出完成")
            send(
                title="Baiyefee 任务执行报告",
                content=html,
                SMTP_HTML="true",
            )

        except Exception:
            logger.exception("导出报告失败，结束执行")

    except Exception as e:
        logger.error(f"执行操作时发生严重错误: {e}")
        raise


if __name__ == "__main__":
    main()
