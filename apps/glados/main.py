# tasks/task_glados.py
import sys

from apps.glados.core.config import load_glados_config
from apps.glados.core.repositories import init_database
from apps.glados.core.server import GladosClient
from utils.config import get_config_path, load_global_config
from utils.log import get_logger
from utils.notify import send
from utils.paths import logs

logger = get_logger(name="glados_main", log_dir=logs(), fmt_type="detailed")


def main():
    """GLaDOS 签到任务主入口"""
    client: GladosClient | None = None

    try:
        # 1. 加载全局配置
        logger.info("开始加载全局配置...")
        global_config = load_global_config()
        logger.info("全局配置加载完成")

        # 2. 加载 GLaDOS 配置
        logger.info("开始加载 GLaDOS 配置...")
        glados_config = load_glados_config()
        if not glados_config:
            message = f"GLaDOS 配置加载失败，请检查 {get_config_path('glados')} 文件"
            logger.error(message)
            send("GLaDOS 任务失败", message, SMTP_HTML="false")
            sys.exit(1)

        # 如果用户列表为空,跳过执行
        if not glados_config.accounts:
            message = f"GLaDOS 用户列表为空，请检查 {get_config_path('glados')} 文件"
            logger.error(message)
            send("GLaDOS 任务跳过", message, SMTP_HTML="false")
            sys.exit(1)

        logger.info(f"GLaDOS 配置加载完成，共 {len(glados_config.accounts)} 个账号")

        # 3. 初始化数据库, 创建客户端
        init_database()

        client = GladosClient(
            global_config=global_config,
            glados_config=glados_config,
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


def _execute_operations(client: GladosClient) -> None:
    """
    执行所有 GLaDOS 操作

    Args:
        client: GLaDOS 客户端实例
    """
    try:
        # ==================== 1. 更新全部状态 ====================
        logger.info("=" * 50)
        logger.info("开始更新全部账号状态...")
        try:
            # 获取所有账号状态
            status_results = client.status_all()
            total_count = len(status_results)
            success_count = sum(
                1 for r in status_results.values() if r is not None and r.success
            )
            logger.info(f"状态更新完成: 成功 {success_count}/{total_count}")

            # 记录状态详情
            for username, result in status_results.items():
                if result is None:
                    logger.warning(f"获取状态失败 [{username}]: 返回结果为 None")
                elif result.success:
                    logger.info(
                        f"账号 {username}: VIP={result.vip}, "
                        f"剩余天数={result.left_days:.1f}天, "
                        f"已用流量={result.traffic_byte / (1024**3):.2f}GB, "
                        f"总流量={result.total_traffic_byte / (1024**3):.2f}GB"
                    )
                else:
                    logger.warning(f"获取状态失败 [{username}]: {result.error}")

            # 获取所有账号积分
            points_results = client.points_all()
            total_count = len(points_results)
            success_count = sum(
                1 for r in points_results.values() if r is not None and r.success
            )
            logger.info(f"积分更新完成: 成功 {success_count}/{total_count}")

            for username, result in points_results.items():
                if result is None:
                    logger.warning(f"获取积分失败 [{username}]: 返回结果为 None")
                elif result.success:
                    logger.info(f"账号 {username}: 积分={result.points:.2f}")
                else:
                    logger.warning(f"获取积分失败 [{username}]: {result.error}")

        except Exception:
            logger.exception("更新状态失败: ")
            raise  # 状态更新是基础操作，失败则终止

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

            # 记录失败的签到
            for username, result in checkin_results.items():
                if result is None:
                    logger.warning(f"签到失败 [{username}]: 返回结果为 None")
                elif not result.success:
                    logger.warning(f"签到失败 [{username}]: {result.message}")
        except Exception:
            logger.exception("签到失败，终止执行")
            raise  # 签到是核心功能，失败则终止

        # ==================== 3. 积分续费 ====================
        logger.info("=" * 50)
        logger.info("开始执行积分续费...")
        try:
            exchange_results = client.exchange_all_by_rules()
            total_count = len(exchange_results)
            success_count = sum(
                1 for r in exchange_results.values() if r is not None and r.success
            )

            logger.info(f"积分续费完成: 成功 {success_count}/{total_count}")

            # 记录续费结果
            for username, result in exchange_results.items():
                if result is None:
                    logger.debug(f"账号 {username}: 无需续费")
                elif result.success:
                    logger.info(
                        f"账号 {username}: 续费成功，增加 {result.days_added} 天，剩余 {result.points} 积分"
                    )
                else:
                    logger.warning(
                        f"账号 {username}: 续费失败 - {result.message if hasattr(result, 'message') else '未知错误'}"
                    )
        except Exception:
            logger.exception("积分续费失败，继续执行后续任务")

        # ==================== laster. 报告导出 ====================
        logger.info("=" * 50)
        logger.info("开始执行报告导出...")
        try:
            html = client.build_report_html()
            logger.info("报告导出完成")
            send(
                title="GLaDOS 任务执行报告",
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
