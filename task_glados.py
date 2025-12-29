from modules.glados.glados import GladosClient
from modules.glados.config.config import Config
from common.logger import logger
import datetime
import time

def main():
    config = Config("modules/glados/config.yaml", "modules/glados/config.yaml")

    client = GladosClient(config)
    client.redeem_gift_codes()
    client.checkin_all()
    
if __name__ == "__main__":
    main()