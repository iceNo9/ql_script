# apps/southpro/main.py

import sys
from dataclasses import dataclass

from apps.southpro.core.app import SouthProApp
from apps.southpro.core.config import load_southpro_config
from apps.southpro.core.repositories import init_database
from utils.config import get_config_path, load_global_config
from utils.log import get_logger
from utils.paths import logs

logger = get_logger(
    name="southpro_main",
    log_dir=logs(),
    fmt_type="detailed",
)


# ================================================================
# 执行摘要
# ================================================================


@dataclass
class ExecutionSummary:
    """任务执行摘要，用于生成邮件标题状态。"""

    # 阶段 1：Profile
    profile_success: int = 0
    profile_total: int = 0

    # 阶段 2：日常任务
    daily_success: int = 0
    daily_total: int = 0

    # 阶段 3：周常任务
    weekly_success: int = 0
    weekly_total: int = 0

    # 阶段 4：报告
    report_html: str = ""
    report_ok: bool = False

    # 致命错误
    fatal_error: bool = False
    error_message: str = ""

    @property
    def status(self) -> str:
        """返回状态文本：错误 / 警告 / 成功。"""
        if self.fatal_error:
            return "错误"
        if self._has_warnings():
            return "警告"
        return "成功"

    @property
    def title(self) -> str:
        """生成邮件标题。"""
        base = "SouthPro 任务执行报告"
        if self.daily_total > 0:
            return (
                f"【{self.status}】{base} "
                f"(日常 {self.daily_success}/{self.daily_total})"
            )
        return f"【{self.status}】{base}"

    def _has_warnings(self) -> bool:
        """是否有需要警告的情况。"""
        if self.profile_total > 0 and self.profile_success < self.profile_total:
            return True
        if self.daily_total > 0 and self.daily_success < self.daily_total:
            return True
        if self.weekly_total > 0 and self.weekly_success < self.weekly_total:
            return True
        return not self.report_ok


# ================================================================
# 主入口
# ================================================================


def main():
    """SouthPro 任务主入口。"""
    client: SouthProApp | None = None
    summary: ExecutionSummary | None = None

    try:
        # 1. 加载全局配置
        logger.info("开始加载全局配置...")
        global_config = load_global_config()
        logger.info("全局配置加载完成")

        # 2. 加载 SouthPro 配置
        logger.info("开始加载 SouthPro 配置...")
        southpro_config = load_southpro_config()

        if not southpro_config:
            message = (
                "SouthPro 配置加载失败，请检查 " f"{get_config_path('southpro')} 文件"
            )
            logger.error(message)
            # 此时 client 未创建，不发送通知
            sys.exit(1)

        if not southpro_config.accounts:
            message = (
                "SouthPro 用户列表为空，请检查 " f"{get_config_path('southpro')} 文件"
            )
            logger.error(message)
            sys.exit(1)

        logger.info(
            "SouthPro 配置加载完成，共 %d 个账号",
            len(southpro_config.accounts),
        )

        # 3. 初始化数据库
        logger.info("开始初始化 SouthPro 数据库...")
        init_database()
        logger.info("SouthPro 数据库初始化完成")

        # 4. 创建客户端
        client = SouthProApp(
            global_config=global_config,
            southpro_config=southpro_config,
        )

        # 5. 执行任务
        summary = _execute_operations(client)

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

    except Exception as e:
        logger.exception("程序异常退出")
        summary = ExecutionSummary(
            fatal_error=True,
            error_message=str(e) or "程序异常退出",
        )

    finally:
        # 统一发送通知
        if summary is not None and client is not None:
            _send_report(client, summary)

        if client and hasattr(client, "close"):
            try:
                client.close()
            except Exception:
                logger.exception("关闭 client 时出错")

        logger.info("资源清理完成")


# ================================================================
# 执行操作
# ================================================================


def _execute_operations(
    client: SouthProApp,
) -> ExecutionSummary:
    """
    执行所有 SouthPro 操作。

    阶段 1/2/3 失败时记录摘要，继续执行；
    阶段 4（报告构建）失败时记录摘要。

    Args:
        client: SouthPro 客户端实例。

    Returns:
        ExecutionSummary。
    """
    summary = ExecutionSummary()

    # ==================== 1. 获取 Profile ====================
    logger.info("=" * 60)
    logger.info("开始获取全部账号 Profile...")

    try:
        profile_results = client.get_profile_all()
        total_count = len(profile_results)
        success_count = sum(
            1 for r in profile_results.values() if r is not None and r.success
        )

        logger.info("Profile 获取完成: 成功 %d/%d", success_count, total_count)

        summary.profile_total = total_count
        summary.profile_success = success_count

        for username, result in profile_results.items():
            if result is None:
                logger.warning("获取 Profile 失败 [%s]: 返回结果为 None", username)
            elif result.success:
                logger.info("账号 %s: 当前 SP %s", username, result.points_sp)
            else:
                logger.warning("获取 Profile 失败 [%s]: %s", username, result.error)

    except Exception:
        logger.exception("获取 Profile 失败，继续执行后续任务")
        summary.error_message = "获取 Profile 失败"

    # ==================== 2. 日常任务 ====================
    logger.info("=" * 60)
    logger.info("开始执行每日任务...")

    try:
        daily_results = client.complete_daily_all()
        total_count = len(daily_results)
        success_count = sum(
            1 for r in daily_results.values() if r is not None and r.success
        )

        logger.info("每日任务完成: 成功 %d/%d", success_count, total_count)

        summary.daily_total = total_count
        summary.daily_success = success_count

        for username, result in daily_results.items():
            if result is None:
                logger.warning("每日任务失败 [%s]: 返回结果为 None", username)
            elif result.success:
                logger.info(
                    "账号 %s: 每日任务完成，SP 变化 %+d",
                    username,
                    result.delta_points_sp,
                )
            else:
                logger.warning("每日任务失败 [%s]: %s", username, result.error)

    except Exception:
        logger.exception("每日任务执行失败，继续执行周常任务")
        summary.error_message = "每日任务执行失败"

    # ==================== 3. 周常任务 ====================
    logger.info("=" * 60)
    logger.info("开始执行每周任务...")

    try:
        weekly_results = client.complete_weekly_all()
        total_count = len(weekly_results)
        success_count = sum(
            1 for r in weekly_results.values() if r is not None and r.success
        )

        logger.info("每周任务完成: 成功 %d/%d", success_count, total_count)

        summary.weekly_total = total_count
        summary.weekly_success = success_count

        for username, result in weekly_results.items():
            if result is None:
                logger.warning("每周任务失败 [%s]: 返回结果为 None", username)
            elif result.success:
                logger.info(
                    "账号 %s: 每周任务完成，SP 变化 %+d",
                    username,
                    result.delta_points_sp,
                )
            else:
                logger.warning("每周任务失败 [%s]: %s", username, result.error)

    except Exception:
        logger.exception("每周任务执行失败，继续执行后续操作")
        summary.error_message = "每周任务执行失败"

    # ==================== 4. 构建报告 ====================
    logger.info("=" * 60)
    logger.info("开始构建 SouthPro 运行报告...")

    try:
        html = client.build_report_html()
        logger.info("SouthPro 报告构建完成")

        summary.report_html = html
        summary.report_ok = True

    except Exception:
        logger.exception("构建 SouthPro 报告失败")

    return summary


# ================================================================
# 发送报告
# ================================================================


def _send_report(
    client: SouthProApp,
    summary: ExecutionSummary,
) -> None:
    """
    根据执行摘要发送通知。

    - 有 HTML：调 client.send_report(html, title=...)。
    - 无 HTML：直接构造简单文本，不经过 client.send_report（因为没有 HTML）。

    注意：
        client.send_report 内部有"每天只发一次"检查。
    """
    try:
        if summary.report_html:
            client.send_report(
                summary.report_html,
                title=summary.title,
            )
        else:
            # 没有 HTML：尝试用纯文本兜底
            from utils.notify import send

            content = summary.error_message or "任务执行失败，无可用报告内容"
            send(
                title=summary.title,
                content=content,
                SMTP_HTML="false",
            )
    except Exception:
        logger.exception("发送 SouthPro 报告邮件失败")


if __name__ == "__main__":
    main()
