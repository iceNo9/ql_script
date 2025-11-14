# repo/common/notify.py

def ql_notify(title, content):
    """
    通用通知中间件：
    - 在青龙运行时优先导入 notify/sendNotify
    - 本地调试 fallback 打印
    """
    notify_impl = None

    # 尝试青龙新版 notify.py（青龙系统自带）
    try:
        from notify import send as notify_impl
    except:
        pass

    # 尝试青龙旧版 sendNotify.py
    if notify_impl is None:
        try:
            from sendNotify import send as notify_impl
        except:
            pass

    # 如果都无法导入，使用本地 fallback
    if notify_impl is None:
        def notify_impl(title, content):
            print("\n========== 本地通知 ==========")
            print(f"标题: {title}")
            print(f"内容: {content}")
            print("=============================\n")

    # 执行通知
    notify_impl(title, content)
