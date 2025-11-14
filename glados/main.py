from .glados import GladosClient
from common.logger import logger

def main():
    client = GladosClient("config.yaml")
    client.checkin_all()

if __name__ == "__main__":
    main()