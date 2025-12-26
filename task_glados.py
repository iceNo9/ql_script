from modules.glados.glados import GladosClient
from modules.glados.config.config import Config
from common.logger import logger
import datetime
import time

def main():
    config = Config("modules/glados/config.yaml", "modules/glados/config.yaml")

    client = GladosClient(config)
    client.login_account(config.accounts[0].name)

    
if __name__ == "__main__":
    main()