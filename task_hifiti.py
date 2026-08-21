#!/usr/bin/env python3
# 青龙定时任务配置文件
# 名称: Hifiti签到
# cron: 0 0 * * *

from apps.hifiti.main import main

if __name__ == "__main__":
    main()
