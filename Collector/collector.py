# A program used to collect stock data from the web.
# sammatime22, 2024
from bs4 import BeautifulSoup
from collections import Counter
from factory import stomp_factory
from logging.handlers import RotatingFileHandler
import asyncio
import datetime
import json
import logging
import mariadb
import re
import requests
import stomp
import threading
import time
import traceback
import yaml
# Ensure yaml library works as intended in future Python versions
import collections
import collections.abc
collections.Hashable = collections.abc.Hashable

class Collector(stomp.ConnectionListener):
    '''
    The Collector class, which is responsible for collecting and cleaning stock data.
    '''

    # Constants for Collector
    # Constants to pull from config file
    CONFIG = None
    MARIA_DB_CONFIG = "maria_db_config"
    USER = "user"
    PASSWORD = "password"
    MARIA_DB_IP = "host"
    MARIA_DB_PORT = "port"
    MARIA_DB_DATABASE = "database"
    
    TASKING = "tasking"
    COLLECTOR_ID = "collector_id"
    TOTAL_COLLECTORS = "total_collectors"

    # Constants for operations
    AWAIT_TIME = 90 # 90s between each pull for stock data
    HEADERS = requests.utils.default_headers()
    # Google Finance (beta) serves a "Your device isn't supported" page to unrecognized clients,
    # so present ourselves as a current desktop browser
    HEADERS.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9'
    })
    UNSUPPORTED_PAGE_MARKER = b'alt="Unsupported page"'
    ETOUQ = "etouq"

    # Constants for SQL queries
    GET_COLLECTED_DATA_AT_NEWDAY_FOR_SOURCE_ID_AND_STOCK_ID = "SELECT pull_id, pull_date, dirty_data FROM COLLECTED_DATA WHERE source_id={} AND stock_id={} AND pull_date > SUBDATE(NOW(), 1);"
    GET_DATA_SOURCES = "SELECT source_id, source_location, extension, search_terms FROM DATA_SOURCES;"
    GET_STOCK_IDS = "SELECT stock_id FROM STOCK;"
    GET_SOURCE_IDS = "SELECT source_id FROM DATA_SOURCES;"
    GET_STOCK_ID_FOR_STOCK_NAME = "SELECT stock_id FROM STOCK WHERE acronym=\"{}\";"
    GET_STOCKS_FOR_COLLECTOR_ID = "SELECT stock_id, stock_name, acronym, market FROM STOCK WHERE MOD(stock_id, {}) = {};"
    INSERT_CLEAN_DATA = "INSERT INTO CLEANED_DATA (stock_id, pull_id, pull_date, source_id, price, rate_of_change) VALUES ({},{},\"{}\",{},{},{});"
    INSERT_INTO_COLLECTED_DATA = "INSERT INTO COLLECTED_DATA (source_id, stock_id, dirty_data) VALUES ({},{},\"{}\");"

    # Constants for currencies (currently just USD)
    DOLLAR = "$"
    CURRENCIES = [DOLLAR]

    # Other constants
    PERCENT = "%"

    # Patterns for the text of the tags holding the price (e.g. "$343.92") and rate of change (e.g. "+0.46%")
    PRICE_PATTERN = re.compile(r"^\s*(?:{})([\d,]+(?:\.\d+)?)\s*$".format("|".join(re.escape(currency) for currency in CURRENCIES)))
    RATE_OF_CHANGE_PATTERN = re.compile(r"^\s*([+-]?[\d,]+(?:\.\d+)?){}\s*$".format(re.escape(PERCENT)))

    # Logging
    logger = None
    handler = RotatingFileHandler(
        'collector.log',
        maxBytes = 2_000_000,
        backupCount = 1
    )

    # STOMP stuff
    stomp_connection = None
    
    # Whether we are actively collecting/cleaning or not
    active = False

    # For the asyncio loop
    loop = None
    thread = None

    def __init__(self, collector_config):
        '''
        The initializer for the Collector.

        This initializes an asyncio event loop for the Collector, separating the collection process from the STOMP listener.

        Parameters:
        -----------
        collector_config: The configuration for the Collector's MariaDB connection.
        '''
        self.CONFIG = collector_config

        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

        self.logger = logging.getLogger()
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.INFO)

        # Startup Message
        self.logger.info("Collector started at {}".format(datetime.datetime.now().timestamp()))
        self.logger.info("Collector configuration: {}".format(collector_config))
    

    def maria_db_factory(self, user, password, host, port, database):
        '''
        Returns a connection cursor to mariadb.

        Parameters:
        -----------
        user: the username for the mariadb connection
        password: the password for the mariadb connection
        host: the host for the mariadb connection
        port: the port for the mariadb connection
        database: the database schema for the mariadb connection

        Returns:
        -----------
        - a connection cursor to MariaDB
        '''
        conn = mariadb.connect(user=user, password=password, host=host, port=port, database=database)
        conn.autocommit = True
        return conn.cursor()


    def cleaning_algorithm(self, dirty_data):
        '''
        Returns cleaned data based on the provided dirty data.

        Google Finance renders the quote header (current price, then the day's percent change)
        before any other currency amounts on the page, such as the Open/High/Low stats or the
        related stocks table. The price is taken to be the first text that is only a currency
        amount, and the rate of change the first percentage that follows it.

        Parameters:
        -----------
        dirty_data: the dirty data to clean

        Returns:
        -----------
        - the cleaned price, or -1.0 if none was found
        - the cleaned rate of change, or -1.0 if none was found
        '''
        price = -1.0
        rate_of_change = -1.0
        soupy = BeautifulSoup(dirty_data, features='lxml')
        price_text = soupy.find(string=self.PRICE_PATTERN)
        if price_text is not None:
            price = float(self.PRICE_PATTERN.match(price_text).group(1).replace(",", ""))
            rate_of_change_text = price_text.find_next(string=self.RATE_OF_CHANGE_PATTERN)
            if rate_of_change_text is not None:
                rate_of_change = float(self.RATE_OF_CHANGE_PATTERN.match(rate_of_change_text).group(1).replace(",", ""))

        return price, rate_of_change


    async def conduct_collection(self):
        '''
        The main thread to conduct the collection and cleaning process.
        '''
        collector_config_config = self.CONFIG

        # connect to the DB
        mariadb_cursor = self.maria_db_factory(collector_config_config[self.MARIA_DB_CONFIG][self.USER], \
            collector_config_config[self.MARIA_DB_CONFIG][self.PASSWORD], \
            collector_config_config[self.MARIA_DB_CONFIG][self.MARIA_DB_IP], \
            collector_config_config[self.MARIA_DB_CONFIG][self.MARIA_DB_PORT], \
            collector_config_config[self.MARIA_DB_CONFIG][self.MARIA_DB_DATABASE])
        self.logger.info("Connected to MariaDB at {}".format(datetime.datetime.now().timestamp()))

        # COLLECTION
        # go through all DATA_SOURCES
        # TODO: Somehow we need the Orchestrator to tell us what stocks this particular Collector should collect
        # Alternatively, each collector could determine which stocks to collect based on ID plus some modulo operation
        mariadb_cursor.execute(self.GET_DATA_SOURCES)
        data_sources = mariadb_cursor.fetchall()
        if len(data_sources) > 0:
            for (source_id, source_location, extension, search_terms) in data_sources:
                self.logger.info("Collecting data from source {} at {}".format(source_location, datetime.datetime.now().timestamp()))
                # go through all search_terms
                mariadb_cursor.execute(self.GET_STOCKS_FOR_COLLECTOR_ID.format(\
                    collector_config_config[self.TASKING][self.TOTAL_COLLECTORS],\
                    collector_config_config[self.TASKING][self.COLLECTOR_ID]))
                stock_info = mariadb_cursor.fetchall()
                for (stock_id, stock_name, acronym, market) in stock_info:
                    self.logger.info("Collecting data for stock {}".format(stock_name))
                    resp = requests.get("https://{}/{}/{}:{}".format(source_location, extension, acronym, market))
                    time.sleep(self.AWAIT_TIME) # be polite
                    if resp.status_code != 200 or self.UNSUPPORTED_PAGE_MARKER in resp.content:
                        self.logger.warning("Source {} returned an unusable page for {} (status {}, final url {}, redirects {}), skipping".format(
                            source_location, stock_name, resp.status_code, resp.url, [r.headers.get('Location') for r in resp.history]))
                        continue
                    # place the data into the COLLECTED_DATA
                    modified_content = str(resp.content).replace('"', self.ETOUQ)
                    if stock_id is not None:
                        mariadb_cursor.execute(self.INSERT_INTO_COLLECTED_DATA.format(source_id, stock_id, modified_content))

        # CLEANING
        # Get every stock ID 
        mariadb_cursor.execute(self.GET_STOCK_IDS)
        stock_ids = mariadb_cursor.fetchall()
        mariadb_cursor.execute(self.GET_SOURCE_IDS) 
        source_ids = mariadb_cursor.fetchall()

        # Go through all stock_ids
        #for stock_id in stock_ids:
        for source_id in source_ids:
            for stock_id in stock_ids:
                # ...and get data from the past day that we collected
                try:
                    mariadb_cursor.execute(self.GET_COLLECTED_DATA_AT_NEWDAY_FOR_SOURCE_ID_AND_STOCK_ID.format(source_id[0], stock_id[0]))
                
                    collected_data = mariadb_cursor.fetchall()
                    for (pull_id, pull_date, dirty_data) in collected_data:
                        # For the dirty data, clean it and insert it into the DB
                        price, rate_of_change = self.cleaning_algorithm(dirty_data.replace(self.ETOUQ, '"'))
                        time.sleep(self.AWAIT_TIME)
                        mariadb_cursor.execute(self.INSERT_CLEAN_DATA.format(stock_id[0], pull_id, pull_date, source_id[0], price, rate_of_change))
                        self.logger.info("Cleaned data for stock_id {} and source_id {} at {}".format(stock_id[0], source_id[0], datetime.datetime.now().timestamp()))
                except Exception as e:
                    self.logger.exception("Error seen during data cleaning: {}".format(e))
        self.stomp_connection.send("/topic/collection-reply", json.dumps({"collection_stop": datetime.datetime.now().timestamp()}))
        self.active = False
        self.logger.info("Finished collection and cleaning at {}".format(datetime.datetime.now().timestamp()))


    def on_message(self, message):
        '''
        Collects messages for the Collector.

        Parameters:
        -----------
        headers: the headers of the message received
        message: the message received
        '''
        try:
            if not self.active:
                self.active = True
                asyncio.run_coroutine_threadsafe(self.conduct_collection(), self.loop)
            else:
                self.logger.warning("Already active, ignoring message")
        except Exception as e:
            self.logger.error("Catching exception, {}". format(e))


    def set_stomp_connection(self, stomp_connection):
        '''
        Sets the Collector's STOMP connection.

        Parameters:
        -----------
        stomp_connection: the STOMP connection to set for the Collector
        '''
        self.stomp_connection = stomp_connection


    def main_loop(self):
        '''
        Keeps the Collector alive
        '''
        while True:
            time.sleep(10)


# Collector Setup
if __name__ == "__main__":
    COLLECTOR_ID = 26553
    COLLECTOR_CONFIG = "/config-dir/collector-config-private.yaml"
    with open(COLLECTOR_CONFIG, "r") as collector_config_file:
        collector_config = yaml.safe_load(collector_config_file)
        collector = Collector(collector_config) 
        stomp_factory(collector, COLLECTOR_ID, collector_config["stomp_config"])
        collector_thread = threading.Thread(target=collector.main_loop)

        # Starting Collector
        collector_thread.start()
