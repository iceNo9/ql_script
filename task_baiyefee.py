#!/usr/bin/env python3
# 青龙定时任务配置文件
# 名称: Baiyefee签到
# cron: 0 6 * * *

from apps.baiyefee.main import main

if __name__ == "__main__":
    main()
