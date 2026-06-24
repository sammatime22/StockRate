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

    # Constants for operations
    AWAIT_TIME = 90 # 90s between each pull for stock data
    HEADERS = requests.utils.default_headers()
    HEADERS.update({'User-Agent': 'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36'})
    ETOUQ = "etouq"

    # Constants for SQL queries
    GET_COLLECTED_DATA_AT_NEWDAY_FOR_SOURCE_ID_AND_STOCK_ID = "SELECT pull_id, dirty_data FROM COLLECTED_DATA WHERE source_id={} AND stock_id={} AND pull_date > SUBDATE(NOW(), 1);"
    GET_DATA_SOURCES = "SELECT source_id, source_location, extension, search_terms FROM DATA_SOURCES;"
    GET_STOCK_IDS = "SELECT stock_id FROM STOCK;"
    GET_SOURCE_IDS = "SELECT source_id FROM DATA_SOURCES;"
    GET_STOCK_ID_FOR_STOCK_NAME = "SELECT stock_id FROM STOCK WHERE acronym=\"{}\";"
    INSERT_CLEAN_DATA = "INSERT INTO CLEANED_DATA (stock_id, pull_id, source_id, price, rate_of_change) VALUES ({},{},{},{},{});"
    INSERT_INTO_COLLECTED_DATA = "INSERT INTO COLLECTED_DATA (source_id, stock_id, dirty_data) VALUES ({},{},\"{}\");"

    # Constants for currencies (currently just USD)
    DOLLAR = "$"
    CURRENCIES = [DOLLAR]

    # Other constants
    PERCENT = "%"

    # this will be globally kept - the collector probably should be a class but oh well at this time
    value_tag_class = None
    rate_of_change_class = None

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


    def learn_tag_contents(self, soupy):
        '''
        This method determines which tags will have currency values.

        Parameters:
        -----------
        soupy: the BeautifulSoup object to learn from

        Returns:
        -----------
        - the class of the tag that contains the currency value
        - the class of the tag that contains the rate of change value
        '''
        # return example_tag_value['class'], example_tag_rate_of_change['class']
        example_tag_value = soupy.find_all('div',string=re.compile("\$\d+(?:\.\d+)?"))[0].find_all('div')[-1]
        example_tag_rate = soupy.find_all('div',string=re.compile("\d+(?:\.\d+)\%?"))[0].find_all('div')[-1]

        return ' '.join(example_tag_value.attrs['class']), ' '.join(example_tag_rate.attrs['class'])


    def cleaning_algorithm(self, dirty_data):
        '''
        Returns cleaned data based on the provided dirty data.

        Parameters:
        -----------
        dirty_data: the dirty data to clean

        Returns:
        -----------
        - the cleaned price
        - the cleaned rate of change
        '''
        price = -1.0
        rate_of_change = -1.0
        # clean my data please!
        # within the data
        soupy = BeautifulSoup(dirty_data, features='lxml')
        if self.value_tag_class == None and self.rate_of_change_class == None:
            # there are likely tags that contain numeric currency values
            self.value_tag_class, self.rate_of_change_class = self.learn_tag_contents(soupy)
        all_value_tags = soupy.find_all(class_=self.value_tag_class)
        all_rate_of_change_tags = soupy.find_all(class_=self.rate_of_change_class)
        # it is possible that there is only one numeric currency value in the content
        if len(all_value_tags) > 1:
            # if this is the case, just grab this
            price = float(all_value_tags[0].text.replace("$","").replace(",",""))
            rate_of_change = float(all_rate_of_change_tags[0].text.replace("%","").replace(",",""))
        
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
        mariadb_cursor.execute(self.GET_DATA_SOURCES)
        data_sources = mariadb_cursor.fetchall()
        if len(data_sources) > 0:
            for (source_id, source_location, extension, search_terms) in data_sources:
                self.logger.info("Collecting data from source {} at {}".format(source_location, datetime.datetime.now().timestamp()))
                # go through all search_terms
                for search_term in search_terms.split(","):
                    resp = requests.get("https://{}/{}/{}".format(source_location, extension, search_term))
                    time.sleep(self.AWAIT_TIME) # be polite
                    # place the data into the COLLECTED_DATA
                    mariadb_cursor.execute(self.GET_STOCK_ID_FOR_STOCK_NAME.format(search_term))
                    stock_id = mariadb_cursor.fetchall()
                    modified_content = str(resp.content).replace('"', self.ETOUQ)
                    if len(stock_id) > 0:
                        mariadb_cursor.execute(self.INSERT_INTO_COLLECTED_DATA.format(source_id, stock_id[0][0], modified_content))

        # CLEANING
        # Get every stock ID 
        mariadb_cursor.execute(self.GET_STOCK_IDS)
        stock_ids = mariadb_cursor.fetchall()
        mariadb_cursor.execute(self.GET_SOURCE_IDS) 
        source_ids = mariadb_cursor.fetchall()

        # Go through all stock_ids
        #for stock_id in stock_ids:
        for source_id in source_ids:
            value_tag_class = None
            rate_of_change_class = None

            for stock_id in stock_ids:
                # ...and get data from the past day that we collected
                try:
                    mariadb_cursor.execute(self.GET_COLLECTED_DATA_AT_NEWDAY_FOR_SOURCE_ID_AND_STOCK_ID.format(source_id[0], stock_id[0]))
                
                    collected_data = mariadb_cursor.fetchall()
                    for (pull_id, dirty_data) in collected_data:
                        # For the dirty data, clean it and insert it into the DB
                        price, rate_of_change = self.cleaning_algorithm(dirty_data.replace(self.ETOUQ, '"'))
                        time.sleep(self.AWAIT_TIME)
                        mariadb_cursor.execute(self.INSERT_CLEAN_DATA.format(stock_id[0], pull_id, source_id[0], price, rate_of_change))
                        self.logger.info("Cleaned data for stock_id {} and source_id {} at {}".format(stock_id[0], source_id[0], datetime.datetime.now().timestamp()))
                except Exception as e:
                    self.logger.error("Error seen during data cleaning", e)
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
        if not self.active:
            self.active = True
            asyncio.run_coroutine_threadsafe(self.conduct_collection(), self.loop)
        else:
            self.logger.warning("Already active, ignoring message")


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
COLLECTOR_ID = 26553
COLLECTOR_CONFIG = "/config-dir/collector-config-private.yaml"
with open(COLLECTOR_CONFIG, "r") as collector_config_file:
    collector_config = yaml.safe_load(collector_config_file)
    collector = Collector(collector_config) 
    stomp_factory(collector, COLLECTOR_ID, collector_config["stomp_config"])
    collector_thread = threading.Thread(target=collector.main_loop)

    # Starting Collector
    collector_thread.start()
