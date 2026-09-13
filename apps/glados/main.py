# apps/glados/main.py

import sys
from dataclasses import dataclass

from apps.glados.core.app import GladosApp
from apps.glados.core.config import load_glados_config
from apps.glados.core.repositories import init_database
from utils.config import get_config_path, load_global_config
from utils.log import get_logger
from utils.notify import send
from utils.paths import logs

logger = get_logger(name="glados_main", log_dir=logs(), fmt_type="detailed")


# ================================================================
# 执行摘要
# ================================================================


@dataclass
class ExecutionSummary:
    """任务执行摘要，用于生成邮件标题状态。"""

    # 阶段 1：状态 / 积分
    status_success: int = 0
    status_total: int = 0
    points_success: int = 0
    points_total: int = 0

    # 阶段 2：签到
    checkin_success: int = 0
    checkin_total: int = 0

    # 阶段 3：积分续费
    exchange_success: int = 0
    exchange_total: int = 0

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
        base = "GLaDOS 任务执行报告"
        if self.checkin_total > 0:
            return (
                f"【{self.status}】{base} "
                f"(签到 {self.checkin_success}/{self.checkin_total})"
            )
        return f"【{self.status}】{base}"

    def _has_warnings(self) -> bool:
        """是否有需要警告的情况。"""
        if self.status_total > 0 and self.status_success < self.status_total:
            return True
        if self.points_total > 0 and self.points_success < self.points_total:
            return True
        if self.checkin_total > 0 and self.checkin_success < self.checkin_total:
            return True
        if self.exchange_total > 0 and self.exchange_success < self.exchange_total:
            return True
        return not self.report_ok


# ================================================================
# 主入口
# ================================================================


def main():
    """GLaDOS 签到任务主入口。"""
    client: GladosApp | None = None
    summary: ExecutionSummary | None = None

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
            send("【错误】GLaDOS 任务失败", message, SMTP_HTML="false")
            sys.exit(1)

        # 如果用户列表为空,跳过执行
        if not glados_config.accounts:
            message = f"GLaDOS 用户列表为空，请检查 {get_config_path('glados')} 文件"
            logger.error(message)
            send("【错误】GLaDOS 任务跳过", message, SMTP_HTML="false")
            sys.exit(1)

        logger.info(f"GLaDOS 配置加载完成，共 {len(glados_config.accounts)} 个账号")

        # 3. 初始化数据库, 创建客户端
        init_database()

        client = GladosApp(
            global_config=global_config,
            glados_config=glados_config,
        )

        # 4. 执行操作
        summary = _execute_operations(client)

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

    except Exception as e:
        logger.exception("程序异常退出: ")
        summary = ExecutionSummary(
            fatal_error=True,
            error_message=str(e) or "程序异常退出",
        )

    finally:
        # 统一发送邮件
        if summary is not None:
            _send_report(summary)

        if client and hasattr(client, "close"):
            try:
                client.close()
            except Exception:
                logger.exception("关闭 client 时出错: ")

        logger.info("资源清理完成")


# ================================================================
# 执行操作
# ================================================================


def _execute_operations(client: GladosApp) -> ExecutionSummary:
    """
    执行所有 GLaDOS 操作。

    阶段 1（状态/积分）、阶段 2（签到）失败时抛异常，由 main 兜底；
    阶段 3（续费）、阶段 4（报告）失败时记录摘要，继续执行。

    Args:
        client: GLaDOS 客户端实例。

    Returns:
        ExecutionSummary。
    """
    summary = ExecutionSummary()

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

        summary.status_total = total_count
        summary.status_success = success_count

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

        summary.points_total = total_count
        summary.points_success = success_count

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

        summary.checkin_total = total_count
        summary.checkin_success = success_count

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

        summary.exchange_total = total_count
        summary.exchange_success = success_count

        # 记录续费结果
        for username, result in exchange_results.items():
            if result is None:
                logger.debug(f"账号 {username}: 无需续费")
            elif result.success:
                logger.info(
                    f"账号 {username}: 续费成功，增加 {result.days_added} 天，"
                    f"剩余 {result.points} 积分"
                )
            else:
                logger.warning(f"账号 {username}: 续费失败 - {result.message}")

    except Exception:
        logger.exception("积分续费失败，继续执行后续任务")
        summary.error_message = "积分续费失败"

    # ==================== 4. 报告导出 ====================
    logger.info("=" * 50)
    logger.info("开始执行报告导出...")
    try:
        html = client.build_report_html()
        logger.info("报告导出完成")

        summary.report_html = html
        summary.report_ok = True

    except Exception:
        logger.exception("导出报告失败，结束执行")
        summary.report_ok = False

    return summary


# ================================================================
# 发送报告
# ================================================================


def _send_report(summary: ExecutionSummary) -> None:
    """
    根据执行摘要发送邮件。

    - 有 HTML：发 HTML 邮件。
    - 无 HTML（阶段 1/2/3 失败）：发纯文本邮件，正文用异常信息。
    """
    try:
        if summary.report_html:
            send(
                title=summary.title,
                content=summary.report_html,
                SMTP_HTML="true",
            )
        else:
            content = summary.error_message or "任务执行失败，无可用报告内容"
            send(
                title=summary.title,
                content=content,
                SMTP_HTML="false",
            )
    except Exception:
        logger.exception("发送报告邮件失败: ")


if __name__ == "__main__":
    main()
