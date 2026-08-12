import requests
from urllib.parse import urljoin
from typing import Optional, Dict, List, Tuple, Any
from pydantic import BaseModel


from utils.log import get_logger
from utils.config import GlobalConfig, EmailConfig, IMAPConfig
from apps.glados.utils.request_client import RequestClient

logger = get_logger(__name__)

class GladosEndpoints:
    """GLaDOS API 端点配置"""
    BASE_URL = "https://glados.cloud"
    
    # 认证相关
    AUTH = "/api/authorization"                    # POST 发送验证码
    LOGIN_API = "/api/login"                       # POST 提交验证码登录
    LOGIN_PAGE = "/login"                          # GET  登录页面
    
    # 用户相关
    CHECKIN = "/api/user/checkin"                  # POST 签到
    STATUS = "/api/user/status"                    # GET  获取用户状态
    CODE = "/api/user/code"                        # POST 兑换礼品码
    POINT =  "/api/user/points"                     # GET  获取积分信息
    CAKES = "/api/user/cakes"                      # GET  获取蛋糕列表
    REDEEM = "/api/user/cake/redeem"               # POST 兑换蛋糕
    EXCHANGE = "/api/user/exchange"                # POST 积分兑换天数
    
    # 其他（如有需要）
    USAGE = "/api/user/usage"                      # GET  获取使用情况
    PROFILE = "/api/user/profile"                  # GET  获取用户资料

class GladosAuthRequest(BaseModel):
    address: str
    site: str = "glados.network"

class GladosAuthResult:
    def __init__(
        self,
        success: bool,
        code: int = 0,
        method: str = "",
        raw: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.code = code
        self.method = method
        self.raw = raw

    @classmethod
    def from_response(cls, response: Dict):
        success = response.get("code") == 0
        return cls(
            success=success,
            code=response.get("code", -1),
            method=response.get("method", ""),
            raw=response,
        )

class GladosLoginRequest(BaseModel):
    email: str
    mailcode: str
    method: str = "email"
    site: str = "glados.network"

class GladosPointHistoryItem:
    """积分变动记录"""

    def __init__(
        self,
        time: int,
        change: float,
        balance: float,
        business: str,
        detail: str,
        raw: Dict[str, Any],
    ):
        self.time = time                # 原始时间戳（ms）
        self.change = change
        self.balance = balance
        self.business = business
        self.detail = detail
        self.raw = raw

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GladosPointHistoryItem":
        return cls(
            time=int(data.get("time", 0)),
            change=float(data.get("change", 0)),
            balance=float(data.get("balance", 0)),
            business=data.get("business", ""),
            detail=data.get("detail", ""),
            raw=data,
        )

class GladosPointPlanItem:
    """积分兑换套餐"""

    def __init__(self, name: str, points: int, days: int):
        self.name = name
        self.points = points
        self.days = days

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "GladosPointPlanItem":
        return cls(
            name=name,
            points=int(data.get("points", 0)),
            days=int(data.get("days", 0)),
        )

class GladosPointResult:
    """GLaDOS 积分信息"""

    def __init__(
        self,
        success: bool,
        code: int = 0,
        points: float = 0.0,
        history: Optional[List[GladosPointHistoryItem]] = None,
        plans: Optional[Dict[str, GladosPointPlanItem]] = None,
        raw: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.code = code
        self.points = points
        self.history = history or []
        self.plans = plans or {}
        self.raw = raw

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GladosPointResult":
        success = data.get("code") == 0

        history_items = [
            GladosPointHistoryItem.from_dict(item)
            for item in data.get("history", [])
        ]

        plans = {
            name: GladosPointPlanItem.from_dict(name, plan)
            for name, plan in data.get("plans", {}).items()
        }

        return cls(
            success=success,
            code=int(data.get("code", 0)),
            points=float(data.get("points", 0)),
            history=history_items,
            plans=plans,
            raw=data,
        )

class GladosCheckinReqest(BaseModel):
    token: str = "glados.cloud"

class GladosCheckinResult:
    def __init__(self, success: bool, code: int, points: int, message: str, raw: Optional[dict] = None):
        self.success = success
        self.code = code
        self.points = points
        self.message = message
        self.raw = raw or {}

    @classmethod
    def from_dict(cls, data: dict) -> "GladosCheckinResult":
        success = data.get("code") == 0
        return cls(
            success=success,
            code=data.get("code", -1),
            points=data.get("points", 0),
            message=data.get("message", ""),
            raw=data,
        )

class GladosStatusResult:
    """GLaDOS 账号状态结果"""

    def __init__(
        self,
        success: bool,
        code: int,
        traffic: int = 0,
        vip: int = 0,
        left_days: float = 0.0,
        cake_count: int = 0,
        raw: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.code = code
        self.traffic = traffic
        self.vip = vip
        self.left_days = left_days
        self.cake_count = cake_count
        self.raw = raw

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GladosStatusResult":
        """
        从接口返回 dict 创建 GladosStatusResult

        data: 整个接口返回（包含 code / data）
        """
        payload = data.get("data", {})

        return cls(
            success=data.get("code") == 0,
            code=int(data.get("code", -1)),
            traffic=int(payload.get("traffic", 0)),
            vip=int(payload.get("vip", 0)),
            left_days=float(payload.get("leftDays", 0)),
            cake_count=int(payload.get("cakeCount", 0)),
            raw=data,
        )

class GlasdosCodeRequest(BaseModel):
    code: str

class GladosCodeResult:
    def __init__(self, success: bool, code: int, message: str, raw: Optional[dict] = None):
        self.success = success
        self.code = code
        self.message = message
        self.raw = raw or {}

    @classmethod
    def from_dict(cls, data: dict) -> "GladosCodeResult":
        success = data.get("code") == 0
        return cls(
            success=success,
            code=data.get("code", -1),
            message=data.get("message", ""),
            raw=data,
        )
    
class GladosCakeItem:
    """GLaDOS Cake 单条记录"""

    def __init__(
        self,
        id: int,
        amount: int,
        available: int,
        business: str,
        reason: str,
        expired_at: int,
    ):
        self.id = id
        self.amount = amount
        self.available = available
        self.business = business
        self.reason = reason
        self.expired_at = expired_at

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GladosCakeItem":
        return cls(
            id=data.get("id", 0),
            amount=data.get("amount", 0),
            available=data.get("available", 0),
            business=data.get("business", ""),
            reason=data.get("reason", ""),
            expired_at=data.get("expired_at", 0),
        )
    
class GladosCakesResult:
    """GLaDOS Cake 接口返回"""
    def __init__(
        self,
        success: bool,
        code: int,
        available: List[GladosCakeItem],
        raw: Dict[str, Any],
    ):
        self.success = success
        self.code = code
        self.available = available
        self.raw = raw

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GladosCakesResult":
        success = data.get("code") == 0
        payload = data.get("data", {})

        available_items = [
            GladosCakeItem.from_dict(item)
            for item in payload.get("available", [])
        ]

        return cls(
            success=success,
            code=data.get("code", -1),
            available=available_items,
            raw=data,
        )
    
class GladosRedeemRequest(BaseModel):
    cakeId: int

class GladosRedeemResult:
    def __init__(self, success: bool, code: int, message: str, raw: Optional[dict] = None):
        self.success = success
        self.code = code
        self.message = message
        self.raw = raw or {}

    @classmethod
    def from_dict(cls, data: dict) -> "GladosRedeemResult":
        success = data.get("code") == 0
        return cls(
            success=success,
            code=data.get("code", -1),
            message=data.get("message", ""),
            raw=data,
        )
    
class GladosExchangeRequest(BaseModel):
    """积分兑换请求模型"""
    planType: str  # 兑换计划类型，如 "plan100/plan200/plan500"

class GladosExchangeResult:
    """GLaDOS 积分兑换结果"""
    
    def __init__(
        self,
        success: bool,
        code: int,
        message: str = "",
        points_used: int = 0,
        days_added: int = 0,
        points_remaining: float = 0.0,
        history: Optional[List[GladosPointHistoryItem]] = None,
        raw: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.code = code
        self.message = message
        self.points_used = points_used
        self.days_added = days_added
        self.points_remaining = points_remaining
        self.history = history or []
        self.raw = raw

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GladosExchangeResult":
        """
        从 API 响应创建 GladosExchangeResult 实例
        
        Args:
            data: API 响应数据
            
        Returns:
            GladosExchangeResult 实例
        """
        success = data.get("code") == 0
        
        # 解析历史记录
        history_items = [
            GladosPointHistoryItem.from_dict(item)
            for item in data.get("history", [])
        ]
        
        # 解析积分余额（可能是字符串格式）
        points_remaining = 0.0
        if "points" in data:
            try:
                points_remaining = float(data.get("points", 0))
            except (ValueError, TypeError):
                points_remaining = 0.0
        
        return cls(
            success=success,
            code=data.get("code", -1),
            message=data.get("message", ""),
            points_used=data.get("pointsUsed", 0),
            days_added=data.get("daysAdded", 0),
            points_remaining=points_remaining,
            history=history_items,
            raw=data,
        )
    
    def __str__(self) -> str:
        """友好的字符串表示"""
        if self.success:
            return f"兑换成功: 使用 {self.points_used} 积分获得 {self.days_added} 天，剩余积分: {self.points_remaining}"
        else:
            return f"兑换失败: {self.message} (code: {self.code})"
        


class GladosServer:
    """GLaDOS 服务器接口封装类"""
    
    def __init__(self, request_client: RequestClient):
        """
        初始化 GLaDOS 服务器接口
        
        Args:
            request_client: 请求客户端实例
        """
        self.client = request_client
        self.base_url = GladosEndpoints.BASE_URL
        self.token = ""
        
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
            "Referer": self._build_url(GladosEndpoints.LOGIN_PAGE),
            "Origin": self.base_url,
            "X-Requested-With": "XMLHttpRequest",
        }
        
        # 添加授权令牌（如果存在）
        if self.token:
            headers["Authorization"] = self.token
            
        # 添加额外的头部
        if additional_headers:
            headers.update(additional_headers)
            
        return headers
    
    def _handle_response(self, response: requests.Response) -> Tuple[bool, Dict[str, Any]]:
        """统一处理响应，返回 (成功标志, 响应数据)"""
        try:
            response.raise_for_status()
            data = response.json()
            logger.debug(f"API响应: {data}")
            
            # 根据API返回的code判断成功与否
            code = data.get("code")
            success = code == 0 if code is not None else response.status_code == 200
            
            return success, data
            
        except requests.exceptions.JSONDecodeError:
            logger.error(f"JSON解析失败: {response.text[:200]}")
            return False, {"code": -1, "message": "响应解析失败", "raw_response": response.text[:500]}
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP请求失败: {e}")
            return False, {"code": response.status_code, "message": f"HTTP错误: {e}", "status_code": response.status_code}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {e}")
            return False, {"code": -1, "message": str(e)}
            
        except Exception as e:
            logger.error(f"处理响应时发生未知错误: {e}")
            return False, {"code": -1, "message": f"未知错误: {str(e)}"}
    
    # -------------------------------
    # 认证相关 API
    # -------------------------------    
    def request_authorization(self, email: str) -> Optional[GladosAuthResult]:
        """
        请求发送登录验证码
        
        Args:
            email: 邮箱地址
            
        Returns:
            (成功标志, API响应数据)
        """
        endpoint = GladosEndpoints.AUTH
        url = self._build_url(endpoint)
        payload = GladosAuthRequest(address=email)
        headers = self._get_headers()
        
        try:
            logger.info(f"[*] 请求发送登录验证码到: {email}")
            response = self.client.post(
                url,
                json=payload.model_dump(),
                headers=headers,
            )
                        
            success, result = self._handle_response(response)            
            
            if success:
                logger.info(f"[+] 验证码请求发送成功: {email}")
            else:
                logger.error(f"[!] 验证码请求发送失败: {result}")
                
            return GladosAuthResult.from_response(result)
            
        except Exception as e:
            logger.error(f"[!] 发送验证码请求异常: {e}")
            return None
        
    def request_login(self, email: str, mailcode: str) -> bool:
        """
        使用邮箱验证码登录
        
        Args:
            email: 邮箱地址
            mailcode: 邮箱验证码
            
        Returns:
            (登录成功标志, 登录结果)
        """
        endpoint = GladosEndpoints.LOGIN_API
        url = self._build_url(endpoint)
        payload = GladosLoginRequest(email=email, mailcode=mailcode)
        headers = self._get_headers()
        
        try:
            logger.info(f"[*] 提交邮箱验证码登录: {email}")
            response = self.client.post(
                url,
                json=payload.model_dump(),
                headers=headers,
            )
            
            success, result = self._handle_response(response)
            
            if success:
                logger.info(f"[+] 邮箱验证码登录成功: {email}")
            else:
                logger.error(f"[!] 邮箱验证码登录失败: {result}")
                
            return success
            
        except Exception as e:
            logger.error(f"[!] 邮箱验证码登录请求异常: {e}")
            return False
    
    # -------------------------------
    # 用户操作 API
    # -------------------------------
    def request_point(self) -> Optional[GladosPointResult]:

        endpoint = GladosEndpoints.POINT
        url = self._build_url(endpoint)
        headers = self._get_headers()

        try:
            logger.info(f"[*] 请求积分信息")
            response = self.client.get(
                url,
                headers=headers,
            )

            success, result = self._handle_response(response)

            if success:
                logger.info(f"[+] 请求积分信息成功")
            else:
                logger.error(f"[!] 请求积分信息失败: {result}")

            return GladosPointResult.from_dict(result)

        except Exception as e:
            logger.error(f"[!] 请求积分信息请求异常: {e}")
            return None
    
    def request_checkin(self) -> Optional[GladosCheckinResult]:
        """
        执行签到
        
        Returns:
            (签到成功标志, 签到结果)
        """
        endpoint = GladosEndpoints.CHECKIN
        url = self._build_url(endpoint)
        payload = GladosCheckinReqest()
        headers = self._get_headers()
        
        try:
            logger.info("[*] 执行签到")
            response = self.client.post(
                url,
                json=payload.model_dump(),
                headers=headers,
            )
            
            success, result = self._handle_response(response)
            
            if success:
                logger.info("[+] 签到成功")
            else:
                logger.warning(f"[!] 签到失败: {result}")
                
            return GladosCheckinResult.from_dict(result)
            
        except Exception as e:
            logger.error(f"[!] 签到请求异常: {e}")
            return None
    
    def request_status(self) -> Optional[GladosStatusResult]:
        """
        获取用户状态
        
        Returns:
            (获取成功标志, 用户状态信息)
        """
        endpoint = GladosEndpoints.STATUS
        url = self._build_url(endpoint)        
        headers = self._get_headers()
        
        try:
            logger.debug("[*] 获取用户状态")
            response = self.client.get(
                url,
                headers=headers,
            )
            
            success, result = self._handle_response(response)
            
            if success:
                logger.debug("[+] 获取状态成功")
            else:
                logger.warning(f"[!] 获取状态失败: {result}")
                
            return GladosStatusResult.from_dict(result)
            
        except Exception as e:
            logger.error(f"[!] 获取状态请求异常: {e}")
            return None
    
    def request_code(self, code: str) -> Optional[GladosCodeResult]:
        """
        兑换礼品码
        
        Args:
            code: 礼品码
            
        Returns:
            (兑换成功标志, 兑换结果)
        """
        endpoint = GladosEndpoints.CODE
        url = self._build_url(endpoint)
        
        # 清理礼品码格式
        clean_code = code.strip().upper().replace(" ", "")        
        payload = GlasdosCodeRequest(code=clean_code)        
        headers = self._get_headers()
        
        try:
            logger.info(f"[*] 兑换礼品码: {clean_code}")
            response = self.client.post(
                url,
                json=payload.model_dump(),
                headers=headers,
                timeout=30
            )
            
            success, result = self._handle_response(response)
            result = GladosCodeResult.from_dict(result)
            
            if success:
                logger.info(f"[+] 兑换成功: {clean_code}")
            else:
                logger.warning(f"[!] 兑换失败: {result.message}")
                
            return result
            
        except Exception as e:
            logger.error(f"[!] 兑换请求异常: {e}")
            return None
        
    def request_cakes(self) -> Optional[GladosCakesResult]:
        """
        请求蛋糕列表
        
        Returns:
            Optional[GladosCakesResult]: 蛋糕信息
        """

        endpoint = GladosEndpoints.CAKES
        url = self._build_url(endpoint)
        headers = self._get_headers()

        try:
            logger.info(f"[*] 请求蛋糕列表")
            response = self.client.get(
                url,
                headers=headers,
            )

            success, result = self._handle_response(response)

            if success:
                logger.info(f"[+] 请求蛋糕列表成功")
            else:
                logger.error(f"[!] 请求蛋糕列表失败: {result}")

            return GladosCakesResult.from_dict(result)

        except Exception as e:
            logger.error(f"[!] 请求蛋糕列表请求异常: {e}")
            return None
        
    def request_redeem(self, cake_id: int) -> Optional[GladosRedeemResult]:
        """
        兑换蛋糕
        
        Args:
            cake_id: 蛋糕ID
            
        Returns:
            Optional[GladosRedeemResult]: 兑换结果
        """

        endpoint = GladosEndpoints.REDEEM
        url = self._build_url(endpoint)
        payload = GladosRedeemRequest(cakeId=cake_id)
        headers = self._get_headers()

        try:
            logger.info(f"[*] 兑换蛋糕 ID: {cake_id}")
            response = self.client.post(
                url,
                json=payload.model_dump(),
                headers=headers,
            )

            success, result = self._handle_response(response)
            result = GladosRedeemResult.from_dict(result)

            if success:
                logger.info(f"[+] 蛋糕兑换成功 ID: {cake_id}")
            else:
                logger.warning(f"[!] 蛋糕兑换失败 ID: {cake_id} - {result.message}")

            return result

        except Exception as e:
            logger.error(f"[!] 蛋糕兑换请求异常: {e}")
            return None
        
    
    def request_exchange(self, plan_type: str = "plan500") -> Optional[GladosExchangeResult]:
        """
        使用积分兑换天数
        
        Args:
            plan_type: 兑换计划类型，默认为 "plan500" (500积分兑换100天)
                       可选值: "plan500", "plan200", 等根据实际API支持
            
        Returns:
            Optional[GladosExchangeResult]: 兑换结果，失败返回 None
            
        Example:
            result = glados.request_exchange("plan500")
            if result and result.success:
                print(f"获得 {result.days_added} 天，消耗 {result.points_used} 积分")
            else:
                print(f"兑换失败: {result.message if result else '未知错误'}")
        """
        endpoint = GladosEndpoints.EXCHANGE
        url = self._build_url(endpoint)
        payload = GladosExchangeRequest(planType=plan_type)
        headers = self._get_headers()
        
        try:
            logger.info(f"[*] 积分兑换: {plan_type}")
            response = self.client.post(
                url,
                json=payload.model_dump(),
                headers=headers,
                timeout=30
            )
            
            success, result = self._handle_response(response)
            exchange_result = GladosExchangeResult.from_dict(result)
            
            if success and exchange_result.success:
                logger.info(f"[+] 积分兑换成功: 使用 {exchange_result.points_used} 积分获得 {exchange_result.days_added} 天")
                logger.info(f"[+] 剩余积分: {exchange_result.points_remaining}")
            else:
                logger.warning(f"[!] 积分兑换失败: {exchange_result.message}")
                
            return exchange_result
            
        except Exception as e:
            logger.error(f"[!] 积分兑换请求异常: {e}")
            return None
            
    # -------------------------------
    # 辅助方法
    # -------------------------------
    def get_total_traffic(self, vip_level: int) -> int:
        """
        根据VIP等级计算总流量
        
        Args:
            vip_level: VIP等级
            
        Returns:
            总流量（字节）
        """
        if vip_level == 21:
            return 200 * 1024 * 1024 * 1024  # 200GB
        else:
            return 10 * 1024 * 1024 * 1024  # 10GB
    
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