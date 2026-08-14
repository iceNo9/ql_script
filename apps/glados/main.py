# tasks/task_glados.py
import sys

from apps.glados.core.config import load_glados_config
from apps.glados.core.server import GladosClient
from apps.glados.core.repositories import init_database
from utils.config import get_config_path, load_global_config
from utils.log import get_logger
from utils.paths import logs
from utils.notify import send

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
            message = (f"GLaDOS 配置加载失败，请检查 {get_config_path('glados')} 文件")
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

    except Exception as e:
        logger.exception(f"程序异常退出: {e}")
        sys.exit(1)

    finally:
        if client and hasattr(client, "close"):
            try:
                client.close()
            except Exception as e:
                logger.warning(f"关闭 client 时出错: {e}")
        logger.info("资源清理完成")


def _execute_operations(client: GladosClient) -> None:
    """
    执行所有 GLaDOS 操作
    
    Args:
        client: GLaDOS 客户端实例
    """
    try:
        # ==================== 签到 ====================
        logger.info("=" * 50)
        logger.info("开始执行签到...")
        try:
            checkin_results = client.checkin_all()
            success_count = len([r for r in checkin_results if r.success])
            total_count = len(checkin_results)
            logger.info(f"签到完成: 成功 {success_count}/{total_count}")
            
            # 记录失败的签到
            failed_checkins = [r for r in checkin_results if not r.success]
            for result in failed_checkins:
                account = getattr(result, 'account', 'unknown')
                message = getattr(result, 'message', '未知错误')
                logger.warning(f"签到失败 [{account}]: {message}")
        except Exception:
            logger.exception("签到失败，终止执行")
            raise  # 签到是核心功能，失败则终止

        # # ==================== 礼品码兑换 ====================
        # logger.info("=" * 50)
        # logger.info("开始执行礼品码兑换...")
        # try:
        #     code_results = client.code()
        #     success_count = len([r for r in code_results if r.success])
        #     total_count = len(code_results)
        #     logger.info(f"礼品码兑换完成: 成功 {success_count}/{total_count}")
            
        #     # 记录失败的兑换
        #     failed_codes = [r for r in code_results if not r.success]
        #     for result in failed_codes:
        #         account = getattr(result, 'account', 'unknown')
        #         message = getattr(result, 'message', '未知错误')
        #         logger.warning(f"礼品码兑换失败 [{account}]: {message}")
        # except Exception:
        #     logger.error("礼品码兑换失败，继续执行后续任务")

        # # ==================== 蛋糕兑换 ====================
        # logger.info("=" * 50)
        # logger.info("开始执行蛋糕兑换...")
        # try:
        #     cake_results = client.cake()
        #     success_count = len([r for r in cake_results if r.success])
        #     total_count = len(cake_results)
        #     logger.info(f"蛋糕兑换完成: 成功 {success_count}/{total_count}")
            
        #     failed_cakes = [r for r in cake_results if not r.success]
        #     for result in failed_cakes:
        #         account = getattr(result, 'account', 'unknown')
        #         message = getattr(result, 'message', '未知错误')
        #         logger.warning(f"蛋糕兑换失败 [{account}]: {message}")
        # except Exception:
        #     logger.error("蛋糕兑换失败，继续执行后续任务")

        # # ==================== 积分续费 ====================
        # logger.info("=" * 50)
        # logger.info("开始执行积分续费...")
        # try:
        #     exchange_results = client.exchange()
        #     total_count = len(exchange_results)
        #     logger.info(f"积分续费完成: 成功 {total_count} 笔")
            
        #     # 如果有详细的续费结果
        #     if total_count > 0:
        #         logger.info(f"共执行 {total_count} 笔积分续费")
        # except Exception:
        #     logger.error("积分续费失败，继续执行后续任务")

        # # ==================== 收集账户信息 ====================
        # logger.info("=" * 50)
        # logger.info("开始收集账户信息...")
        # try:
        #     account_infos = client.collect_account_infos()
        #     logger.info(f"账户信息收集完成，共 {len(account_infos)} 个账户")
            
        #     # 打印账户信息摘要
        #     for info in account_infos:
        #         account = getattr(info, 'account', 'unknown')
        #         days = getattr(info, 'days', 0)
        #         points = getattr(info, 'points', 0)
        #         logger.info(f"  {account}: 剩余 {days} 天, 积分 {points}")
        # except Exception:
        #     logger.error("账户信息收集失败，继续执行后续任务")

        # # ==================== 发送通知 ====================
        # logger.info("=" * 50)
        # logger.info("开始发送通知...")
        # try:
        #     notifier = client.get_notifier()
        #     notifier.send()
        #     logger.info("通知发送完成")
        # except Exception:
        #     logger.error("通知发送失败")

    except Exception as e:
        logger.error(f"执行操作时发生严重错误: {e}")
        raise


if __name__ == "__main__":
    main()