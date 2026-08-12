import re

def traffic_to_bytes(value: str) -> int:
    value = value.strip().upper().replace(" ", "")
    m = re.match(r"([\d.]+)(B|KB|MB|GB)", value)
    if not m:
        return 0

    num, unit = m.groups()
    num = float(num)

    factor = {
        "B": 1,
        "KB": 1024,
        "MB": 1024 ** 2,
        "GB": 1024 ** 3,
    }
    return int(num * factor[unit])

def format_bytes(bytes_value: int) -> str:
    """格式化字节数为易读的单位"""
    if bytes_value >= 1024 ** 3:  # GB
        return f"{bytes_value / (1024 ** 3):.2f} GB"
    elif bytes_value >= 1024 ** 2:  # MB
        return f"{bytes_value / (1024 ** 2):.2f} MB"
    elif bytes_value >= 1024:  # KB
        return f"{bytes_value / 1024:.2f} KB"
    else:
        return f"{bytes_value} B"