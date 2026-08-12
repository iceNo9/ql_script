import requests
import re
import base64

from urllib.parse import urljoin
from typing import Optional, Dict, List, Tuple, Any
from pydantic import BaseModel
from datetime import datetime
from bs4 import BeautifulSoup

from utils.log import get_logger
from modules.ikuuu.utils.request_client import RequestClient
from modules.ikuuu.utils.utils import traffic_to_bytes, format_bytes

logger = get_logger(__name__)

class IkuuuEndpoints:
    """IKUUU API 端点配置"""
    BASE_URL = "https://ikuuu.org"

    # 认证相关
    LOGIN = "/auth/login"                           # POST 登录
        
    # 用户相关
    CHECKIN = "/user/checkin"                      # POST 签到

class IkuuuLoginRequest(BaseModel):
    email: str
    passwd: str
    pageLoadedAt: int
    host: str = "ikuuu.org"
    code: Optional[str] = None

class IkuuuCheckinResult(BaseModel):
    success: bool
    message: str
    change_bytes: int = 0  # 获得/变化的流量（字节）
    ret_code: int
    raw: Dict[str, Any] = {}

    @classmethod
    def from_dict(cls, data: dict) -> "IkuuuCheckinResult":
        success = data.get("ret") == 1
        message = data.get("msg", "")
        
        # 解析消息中的流量信息
        change_bytes = 0
        if success and message:
            change_bytes = cls._parse_bytes_from_message(message)
        
        return cls(
            success=success,
            ret_code=data.get("ret", -1),
            message=message,
            change_bytes=change_bytes,
            raw=data,
        )
    
    @staticmethod
    def _parse_bytes_from_message(message: str) -> int:
        """从签到消息中解析获得的流量（转换为字节）"""
        # 解码Unicode转义字符（如果需要）
        try:
            # 如果消息包含Unicode转义序列，先解码
            decoded_message = message.encode('utf-8').decode('unicode_escape')
        except:
            decoded_message = message
        
        # 尝试匹配各种流量单位
        patterns = [
            (r'(\d+(?:\.\d+)?)\s*GB', 1024**3),  # GB
            (r'(\d+(?:\.\d+)?)\s*MB', 1024**2),  # MB
            (r'(\d+(?:\.\d+)?)\s*KB', 1024),     # KB
            (r'(\d+(?:\.\d+)?)\s*B', 1),         # B（字节）
            (r'(\d+(?:\.\d+)?)\s*GiB', 1024**3), # GiB
            (r'(\d+(?:\.\d+)?)\s*MiB', 1024**2), # MiB
            (r'(\d+(?:\.\d+)?)\s*KiB', 1024),    # KiB
        ]
        
        for pattern, multiplier in patterns:
            match = re.search(pattern, decoded_message, re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1))
                    return int(value * multiplier)
                except (ValueError, TypeError):
                    continue
        
        # 如果没有匹配到标准单位，尝试匹配数字（假设为MB）
        match = re.search(r'(\d+(?:\.\d+)?)', decoded_message)
        if match:
            try:
                value = float(match.group(1))
                # 假设这个数字是MB（根据抓包数据）
                return int(value * 1024**2)
            except (ValueError, TypeError):
                pass
        
        return 0
    
class IkuuuStatusResult(BaseModel):
    success: bool
    total_bytes: int          # 总流量
    used_bytes: int           # 已使用流量（累计）
    today_used_bytes: int     # 今日使用流量
    remain_bytes: int         # 剩余流量
    used_percent: float = 0.0     # 已用百分比（从JS获取）
    today_percent: float = 0.0    # 今日使用百分比（从JS获取）
    remain_percent: float = 0.0   # 剩余百分比（从JS获取）

class IkuuuServer:
    """Ikuuu 服务器接口封装类"""
    
    def __init__(self, request_client: RequestClient):
        """
        初始化 Ikuuu 服务器接口
        
        Args:
            request_client: 请求客户端实例
        """
        self.client = request_client
        self.base_url = IkuuuEndpoints.BASE_URL
        
    # -------------------------------
    # 基础请求方法
    # -------------------------------    
    def _build_url(self, endpoint: str) -> str:
        """构建完整 URL"""
        return urljoin(self.base_url, endpoint)
    
    def _get_headers(self, additional_headers: Optional[Dict] = None) -> Dict:
        """获取默认请求头"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": self._build_url(IkuuuEndpoints.CHECKIN),
            "Origin": self.base_url,
            "X-Requested-With": "XMLHttpRequest",
        }
                    
        # 添加额外的头部
        if additional_headers:
            headers.update(additional_headers)
            
        return headers
    
    def _handle_response(self, response: requests.Response) -> Tuple[bool, Dict[str, Any]]:
        """统一处理响应，返回 (成功标志, 响应数据)"""
        try:
            # 先获取Content-Type和状态码
            content_type = response.headers.get('Content-Type', '').lower()
            status_code = response.status_code
            
            logger.debug(f"[*] 响应状态码: {status_code}, Content-Type: {content_type}")
            
            # 检查是否为HTML响应
            if 'text/html' in content_type:
                logger.warning(f"[!] 收到HTML响应 - URL: {response.url}")
                logger.warning(f"[!] 状态码: {status_code}, 内容长度: {len(response.text)}")
                
                # HTML响应可能是正常的（如登录页面），也可能是异常的
                # 我们记录但继续处理，让调用者根据状态码判断
                if status_code == 200:
                    logger.debug(f"[*] HTML 200响应可能是正常的页面返回")
                    logger.debug(f"[*] HTML预览:\n{response.text[:300]}")
                else:
                    logger.error(f"[!] HTML响应但状态码异常: {status_code}")
                    logger.debug(f"[!] HTML错误内容:\n{response.text[:500]}")
            
            # 对于所有响应都尝试解析JSON
            try:
                data = response.json()
                logger.debug(f"[+] JSON解析成功: {data}")
                
                # 根据API返回的code判断成功与否
                code = data.get("code")
                success = code == 0 if code is not None else response.status_code == 200
                
                return success, data
                
            except requests.exceptions.JSONDecodeError:
                # JSON解析失败
                logger.debug(f"[!] JSON解析失败，尝试按文本处理")
                
                # 如果状态码不是2xx，记录为错误
                if status_code >= 400:
                    logger.error(f"[!] 请求失败 - 状态码: {status_code}")
                    logger.error(f"[!] 响应文本: {response.text[:1000]}")
                    
                    return False, {
                        "code": status_code,
                        "message": f"HTTP错误: {response.reason}",
                        "status_code": status_code,
                        "url": response.url,
                        "raw_response": response.text[:2000] if response.text else "",
                        "content_type": content_type,
                        "is_html": 'text/html' in content_type
                    }
                else:
                    # 状态码2xx但内容不是JSON，可能服务器就是返回文本
                    logger.warning(f"[!] 服务器返回非JSON内容但状态码正常: {status_code}")
                    logger.debug(f"[!] 响应内容类型: {content_type}")
                    
                    return True, {
                        "code": 0,
                        "message": "服务器返回文本内容",
                        "status_code": status_code,
                        "content": response.text,
                        "content_type": content_type,
                        "is_html": 'text/html' in content_type
                    }
                
        except requests.exceptions.HTTPError as e:
            # HTTPError在response.raise_for_status()时抛出
            logger.error(f"[!] HTTP请求失败: {e}")
            logger.debug(f"[!] URL: {response.url}")
            logger.debug(f"[!] 状态码: {response.status_code}")
            
            # 尝试获取响应内容
            try:
                error_content = response.text[:1000] if hasattr(response, 'text') and response.text else ""
                logger.debug(f"[!] 错误响应: {error_content}")
            except:
                pass
                
            return False, {
                "code": response.status_code,
                "message": f"HTTP错误: {e}",
                "status_code": response.status_code,
                "url": response.url
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[!] 请求异常: {e}")
            logger.debug(f"[!] 异常类型: {type(e).__name__}")
            return False, {
                "code": -1,
                "message": str(e),
                "exception_type": type(e).__name__
            }
            
        except Exception as e:
            logger.error(f"[!] 处理响应时发生未知错误: {e}", exc_info=True)
            return False, {
                "code": -1,
                "message": f"未知错误: {str(e)}",
                "exception_type": type(e).__name__
            }


    # -------------------------------
    # 认证相关 API
    # -------------------------------
    def request_login(self, email: str, passwd: str) -> bool:
        """
        使用密码登录
        Args:
            email: 邮箱地址
            passwd: 密码
            
        Returns:
            (登录成功标志, 登录结果)
        """
        endpoint = IkuuuEndpoints.LOGIN
        url = self._build_url(endpoint)
        payload = IkuuuLoginRequest(email=email, passwd=passwd, pageLoadedAt=int(datetime.now().timestamp() * 1000))
        headers = self._get_headers()
        
        try:
            logger.info(f"[*] 提交邮箱密码登录: {email}")
            response = self.client.post(
                url,
                json=payload.model_dump(),
                headers=headers,
            )
            
            success, result = self._handle_response(response)
            
            if success:
                logger.info(f"[+] 邮箱密码登录成功: {email}")
            else:
                logger.error(f"[!] 邮箱密码登录失败: {result}")
                
            return success
            
        except Exception as e:
            logger.error(f"[!] 邮箱密码登录请求异常: {e}")
            return False
    
    # -------------------------------
    # 用户操作 API
    # -------------------------------    
    def request_checkin(self) -> Optional[IkuuuCheckinResult]:
        """
        执行签到
        
        Returns:
            (签到成功标志, 签到结果)
        """
        endpoint = IkuuuEndpoints.CHECKIN
        url = self._build_url(endpoint)
        headers = self._get_headers()
        
        try:
            logger.info("[*] 执行签到")
            response = self.client.post(
                url,
                headers=headers,
            )
            
            success, result = self._handle_response(response)
            
            if success:
                logger.info("[+] 签到成功")
            else:
                logger.warning(f"[!] 签到失败: {result}")
                
            return IkuuuCheckinResult.from_dict(result)
            
        except Exception as e:
            logger.error(f"[!] 签到请求异常: {e}")
            return None

    # -------------------------------
    # 页面抓取（无 API 场景）
    # -------------------------------
    def fetch_user_page_html(self) -> Optional[str]:
        """
        获取 /user 页面真实 HTML（自动解码 originBody）
        """
        url = self._build_url("/user")
        headers = self._get_headers({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

        try:
            logger.info("[*] 获取 /user 页面源代码")
            response = self.client.get(url, headers=headers)
            response.raise_for_status()

            html = response.text

            # 提取 originBody
            match = re.search(
                r'originBody\s*=\s*"([^"]+)"',
                html,
                re.DOTALL
            )
            if not match:
                logger.error("[!] 未找到 originBody，页面结构可能已变")
                return None

            encoded_body = match.group(1)

            # Base64 解码
            decoded_html = base64.b64decode(encoded_body).decode(
                "utf-8", errors="ignore"
            )

            logger.debug("[+] /user 页面解码成功")
            return decoded_html

        except Exception as e:
            logger.error(f"[!] 获取 /user 页面失败: {e}")
            return None

    def _extract_traffic_dount_chat(self, html: str) -> Optional[list]:
        """专门提取trafficDountChat函数参数的辅助函数"""
        try:
            # 找到所有script标签
            soup = BeautifulSoup(html, "lxml")
            scripts = soup.find_all('script')
            
            # 搜索包含trafficDountChat的script
            target_script = None
            for script in scripts:
                if script.string and 'trafficDountChat' in script.string:
                    target_script = script.string
                    logger.debug(f"[+] 找到包含trafficDountChat的script标签")
                    break
            
            if not target_script:
                # 如果没有找到单独的script，在整个HTML中搜索
                logger.debug("[!] 未在script标签中找到，搜索整个HTML")
                target_script = html
            
            # 使用多种正则模式尝试匹配
            patterns = [
                # 精确匹配6个参数
                r'trafficDountChat\s*\(\s*[\'"]([^\'"]+)[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]\s*\)',
                
                # 匹配参数（不限制引号类型）
                r'trafficDountChat\s*\(\s*([^,]+?)\s*,\s*([^,]+?)\s*,\s*([^,]+?)\s*,\s*([^,]+?)\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)',
                
                # 只匹配前三个参数
                r'trafficDountChat\s*\(\s*([^,]+?)\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, target_script, re.DOTALL)
                if match:
                    logger.debug(f"[+] 使用模式成功匹配: {pattern[:50]}...")
                    
                    # 清理参数
                    params = []
                    for i in range(1, min(match.lastindex + 1, 7)):
                        param = match.group(i).strip()
                        # 去除引号
                        param = re.sub(r'^[\'"]|[\'"]$', '', param)
                        params.append(param)
                    
                    # 如果只有3个参数，补充百分比
                    if len(params) == 3:
                        # 计算百分比（近似值）
                        try:
                            used = traffic_to_bytes(params[0])
                            remain = traffic_to_bytes(params[2])
                            total = used + remain
                            if total > 0:
                                used_pct = (used / total) * 100
                                remain_pct = 100 - used_pct
                                params.extend([f"{used_pct:.2f}", "0.00", f"{remain_pct:.2f}"])
                            else:
                                params.extend(["0", "0", "0"])
                        except:
                            params.extend(["0", "0", "0"])
                    
                    logger.info(f"[+] 提取参数: {params}")
                    return params
            
            logger.error("[!] 所有正则模式都未匹配到trafficDountChat")
            return None
            
        except Exception as e:
            logger.error(f"[!] 提取trafficDountChat时出错: {e}")
            return None            
        
    def _parse_status_from_html(self, html: str) -> Optional[IkuuuStatusResult]:
        """改进版 - 使用辅助函数提取流量数据"""
        try:
            # 使用辅助函数提取trafficDountChat参数
            traffic_data = self._extract_traffic_dount_chat(html)
            
            if not traffic_data:
                logger.error("[!] 无法提取trafficDountChat数据")
                return None
            
            # 确保至少有3个参数
            if len(traffic_data) < 3:
                logger.error(f"[!] 参数不足: {traffic_data}")
                return None
            
            # 解析流量数据
            try:
                # 已用流量
                used_str = traffic_data[0]
                # 今日已用
                today_used_str = traffic_data[1]
                # 可用（剩余）流量
                remain_str = traffic_data[2]
                
                # 转换为字节
                used_bytes = traffic_to_bytes(used_str)
                today_used_bytes = traffic_to_bytes(today_used_str)
                remain_bytes = traffic_to_bytes(remain_str)
                
                # 总流量 = 已用 + 可用
                total_bytes = used_bytes + remain_bytes
                
                # 解析百分比
                used_percent = 0.0
                today_percent = 0.0
                remain_percent = 0.0
                
                if len(traffic_data) >= 6:
                    try:
                        used_percent = float(traffic_data[3])
                        today_percent = float(traffic_data[4])
                        remain_percent = float(traffic_data[5])
                    except ValueError:
                        logger.warning("[!] 百分比解析失败，将进行计算")
                        # 计算百分比
                        if total_bytes > 0:
                            used_percent = (used_bytes / total_bytes) * 100
                            remain_percent = 100 - used_percent
                else:
                    # 计算百分比
                    if total_bytes > 0:
                        used_percent = (used_bytes / total_bytes) * 100
                        remain_percent = 100 - used_percent
                
                logger.info(
                    f"[✓] 流量解析成功: "
                    f"已用={used_str}({used_bytes}B, {used_percent:.2f}%), "
                    f"今日={today_used_str}({today_used_bytes}B, {today_percent:.2f}%), "
                    f"剩余={remain_str}({remain_bytes}B, {remain_percent:.2f}%), "
                    f"总计={format_bytes(total_bytes)}"
                )
                
                return IkuuuStatusResult(
                    success=True,
                    total_bytes=total_bytes,
                    used_bytes=used_bytes,
                    today_used_bytes=today_used_bytes,
                    remain_bytes=remain_bytes,
                    used_percent=used_percent,
                    today_percent=today_percent,
                    remain_percent=remain_percent,
                )
                
            except Exception as e:
                logger.error(f"[!] 解析流量数据时出错: {e}", exc_info=True)
                logger.error(f"[!] 原始数据: {traffic_data}")
                return None
                
        except Exception as e:
            logger.error(f"[!] 解析HTML时发生错误: {e}", exc_info=True)
            return None


    def request_status(self) -> Optional[IkuuuStatusResult]:
        """
        获取用户流量状态（从 /user HTML 页面解析）
        """
        try:
            logger.info("[*] 获取用户流量状态")

            html = self.fetch_user_page_html()
            if not html:
                logger.error("[!] 获取 /user HTML 失败")
                return None

            logger.debug(f"[+] 获取到的 HTML: {html}")
            status = self._parse_status_from_html(html)
            if not status:
                logger.error("[!] 解析用户流量失败")
                return None

            logger.info(
                f"[+] 流量状态: "
                f"used={status.used_bytes}, "
                f"today={status.today_used_bytes}, "
                f"remain={status.remain_bytes}, "
                f"total={status.total_bytes}"
            )

            return status

        except Exception as e:
            logger.error(f"[!] request_status 异常: {e}")
            return None
        
    # -------------------------------
    # Cookies 管理
    # -------------------------------
    
    def update_cookies(self, cookies: Dict[str, str]):
        """
        更新客户端的cookies
        
        Args:
            cookies: cookies字典
        """
        self.client.set_cookies(cookies)
        logger.debug("[*] Cookies已更新")
    
    def get_cookies(self) -> Dict[str, str]:
        """
        获取当前cookies
        
        Returns:
            cookies字典
        """
        return self.client.get_cookies_dict()
    
    def clear_cookies(self):
        """清空cookies"""
        self.client.clear_cookies()
        logger.debug("[*] Cookies已清空")