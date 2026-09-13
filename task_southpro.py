#!/usr/bin/env python3
# 青龙定时任务配置文件
# 名称: SouthPro任务
# cron: */30 * * * *

from apps.southpro.main import main

if __name__ == "__main__":
    main()
