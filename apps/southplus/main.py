# apps/southplus/main.py

import sys

from apps.southplus.core.config import load_southplus_config
from apps.southplus.core.repositories import init_database
from apps.southplus.core.server import SouthPlusClient
from utils.config import get_config_path, load_global_config
from utils.log import get_logger
from utils.paths import logs

logger = get_logger(
    name="southplus_main",
    log_dir=logs(),
    fmt_type="detailed",
)


def main():
    """SouthPlus 任务主入口。"""

    client: SouthPlusClient | None = None

    try:
        # ================================================================
        # 1. 加载全局配置
        # ================================================================

        logger.info("开始加载全局配置...")

        global_config = load_global_config()

        logger.info("全局配置加载完成")

        # ================================================================
        # 2. 加载 SouthPlus 配置
        # ================================================================

        logger.info("开始加载 SouthPlus 配置...")

        southplus_config = load_southplus_config()

        if not southplus_config:
            message = (
                "SouthPlus 配置加载失败，请检查 " f"{get_config_path('southplus')} 文件"
            )

            logger.error(message)

            # 配置加载阶段 Client 尚未创建，
            # 因此这里无法使用 client.send_report()。
            #
            # 此处仅记录日志并退出。
            sys.exit(1)

        # ------------------------------------------------------------
        # 用户列表为空
        # ------------------------------------------------------------

        if not southplus_config.accounts:
            message = (
                "SouthPlus 用户列表为空，请检查 " f"{get_config_path('southplus')} 文件"
            )

            logger.error(message)

            # 同样，此时 Client 尚未创建，
            # 不进行通知发送。
            sys.exit(1)

        logger.info(
            "SouthPlus 配置加载完成，共 %d 个账号",
            len(southplus_config.accounts),
        )

        # ================================================================
        # 3. 初始化数据库
        # ================================================================

        logger.info("开始初始化 SouthPlus 数据库...")

        init_database()

        logger.info("SouthPlus 数据库初始化完成")

        # ================================================================
        # 4. 创建客户端
        # ================================================================

        client = SouthPlusClient(
            global_config=global_config,
            southplus_config=southplus_config,
        )

        # ================================================================
        # 5. 执行任务
        # ================================================================

        _execute_operations(client)

    except KeyboardInterrupt:
        logger.info("用户中断执行，正在退出...")
        sys.exit(0)

    except FileNotFoundError as e:
        logger.error("配置文件不存在: %s", e)
        sys.exit(1)

    except PermissionError as e:
        logger.error("文件权限不足: %s", e)
        sys.exit(1)

    except ConnectionError as e:
        logger.error("网络连接失败: %s", e)
        sys.exit(1)

    except Exception:
        logger.exception("程序异常退出")
        sys.exit(1)

    finally:
        if client and hasattr(client, "close"):
            try:
                client.close()
            except Exception:
                logger.exception("关闭 client 时出错")

        logger.info("资源清理完成")


# ========================================================================
# Operations
# ========================================================================


def _execute_operations(
    client: SouthPlusClient,
) -> None:
    """
    执行所有 SouthPlus 操作。

    当前编排顺序：

        1. 获取用户 Profile
        2. 执行每日任务
        3. 执行每周任务
        4. 再次获取 Profile
        5. 构建报告
        6. 发送通知

    具体业务判断由 SouthPlusClient 负责。
    """

    try:
        # ================================================================
        # 1. 获取用户 Profile
        # ================================================================

        logger.info("=" * 60)
        logger.info("开始获取全部账号 Profile...")

        try:
            profile_results = client.get_profile_all()

            total_count = len(profile_results)

            success_count = sum(
                1
                for result in profile_results.values()
                if result is not None and result.success
            )

            logger.info(
                "Profile 获取完成: 成功 %d/%d",
                success_count,
                total_count,
            )

            for username, result in profile_results.items():

                if result is None:
                    logger.warning(
                        "获取 Profile 失败 [%s]: 返回结果为 None",
                        username,
                    )

                elif result.success:
                    logger.info(
                        "账号 %s: 当前 SP %s",
                        username,
                        result.points_sp,
                    )

                else:
                    logger.warning(
                        "获取 Profile 失败 [%s]: %s",
                        username,
                        result.error,
                    )

        except Exception:
            logger.exception(
                "获取 Profile 失败，继续执行后续任务",
            )

        # ================================================================
        # 2. 执行每日任务
        # ================================================================

        logger.info("=" * 60)
        logger.info("开始执行每日任务...")

        try:
            daily_results = client.complete_daily_all()

            total_count = len(daily_results)

            success_results = [
                result
                for result in daily_results.values()
                if result is not None and result.success
            ]

            success_count = len(success_results)

            logger.info(
                "每日任务完成: 成功 %d/%d",
                success_count,
                total_count,
            )

            for username, result in daily_results.items():

                if result is None:
                    logger.warning(
                        "每日任务失败 [%s]: 返回结果为 None",
                        username,
                    )

                elif result.success:
                    logger.info(
                        "账号 %s: 每日任务完成，SP 变化 %+d",
                        username,
                        result.delta_points_sp,
                    )

                else:
                    logger.warning(
                        "每日任务失败 [%s]: %s",
                        username,
                        result.error,
                    )

        except Exception:
            logger.exception(
                "每日任务执行失败，继续执行周常任务",
            )

        # ================================================================
        # 3. 执行每周任务
        # ================================================================

        logger.info("=" * 60)
        logger.info("开始执行每周任务...")

        try:
            weekly_results = client.complete_weekly_all()

            total_count = len(weekly_results)

            success_results = [
                result
                for result in weekly_results.values()
                if result is not None and result.success
            ]

            success_count = len(success_results)

            logger.info(
                "每周任务完成: 成功 %d/%d",
                success_count,
                total_count,
            )

            for username, result in weekly_results.items():

                if result is None:
                    logger.warning(
                        "每周任务失败 [%s]: 返回结果为 None",
                        username,
                    )

                elif result.success:
                    logger.info(
                        "账号 %s: 每周任务完成，SP 变化 %+d",
                        username,
                        result.delta_points_sp,
                    )

                else:
                    logger.warning(
                        "每周任务失败 [%s]: %s",
                        username,
                        result.error,
                    )

        except Exception:
            logger.exception(
                "每周任务执行失败，继续执行后续操作",
            )

        # ================================================================
        # 4. 再次获取 Profile
        #
        # 用于同步每日 / 每周任务执行后的最新 SP。
        # ================================================================

        logger.info("=" * 60)
        logger.info("开始获取任务执行后的全部账号 Profile...")

        try:
            profile_results = client.get_profile_all()

            total_count = len(profile_results)

            success_count = sum(
                1
                for result in profile_results.values()
                if result is not None and result.success
            )

            logger.info(
                "任务后 Profile 获取完成: 成功 %d/%d",
                success_count,
                total_count,
            )

            for username, result in profile_results.items():

                if result is None:
                    logger.warning(
                        "获取任务后 Profile 失败 [%s]: 返回结果为 None",
                        username,
                    )

                elif result.success:
                    logger.info(
                        "账号 %s: 当前 SP %s",
                        username,
                        result.points_sp,
                    )

                else:
                    logger.warning(
                        "获取任务后 Profile 失败 [%s]: %s",
                        username,
                        result.error,
                    )

        except Exception:
            logger.exception(
                "获取任务后 Profile 失败，继续执行报告",
            )

        # ================================================================
        # 5. 构建报告
        # ================================================================

        logger.info("=" * 60)
        logger.info("开始构建 SouthPlus 运行报告...")

        try:
            html = client.build_report_html()

            logger.info("SouthPlus 报告构建完成")

        except Exception:
            logger.exception(
                "构建 SouthPlus 报告失败",
            )
            raise

        # ================================================================
        # 6. 发送通知
        # ================================================================

        logger.info("=" * 60)
        logger.info("开始发送 SouthPlus 运行报告...")

        try:
            sent = client.send_report(
                html,
            )

            if sent:
                logger.info(
                    "SouthPlus 运行报告发送完成",
                )
            else:
                logger.info(
                    "SouthPlus 运行报告未发送",
                )

        except Exception:
            logger.exception(
                "SouthPlus 报告发送处理失败",
            )

    except Exception as e:
        logger.error(
            "执行 SouthPlus 操作时发生严重错误: %s",
            e,
        )
        raise


if __name__ == "__main__":
    main()
