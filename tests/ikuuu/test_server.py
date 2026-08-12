from apps.ikuuu.core.server import IkuuuServer, IkuuuCheckinResult
from apps.ikuuu.utils.request_client import RequestClient
from apps.ikuuu.core.config import IkuuuConfigManager




def test_checkin():
    client = RequestClient(proxies=[], max_retries=2)
    server = IkuuuServer(request_client=client)
    manager = IkuuuConfigManager(r"./config/ikuuu.yaml")
    config = manager.read()
    if config:
        account = config.accounts[0]

    success = server.request_login(account.username, account.password)
    print(f"login success:{success}")

    print(f"cookie:{server.get_cookies()}")

    html = server.fetch_user_page_html()
    if html:
        with open("user.html", "w", encoding="utf-8") as f:
            f.write(html)

    # ret = server.request_checkin()
    # if ret:
    #     print(f"checkin: success:{ret.success} msg:{ret.message}")

if __name__ == "__main__":
    test_checkin()