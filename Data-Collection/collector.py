# A class used to collect stock data from the web.
# sammatime22, 2024
from bs4 import BeautifulSoup
from collections import Counter
import mariadb
import requests
import time
import yaml

# Constants to pull from config file
CONFIG = "/Users/samuelreles/GitHub/StockRate/Data-Collection/collector-config-private.yaml"
MARIA_DB_CONFIG = "maria_db_config"
USER = "user"
PASSWORD = "password"
MARIA_DB_IP = "host"
MARIA_DB_PORT = "port"
MARIA_DB_DATABASE = "database"

# Constants for operations
NAP_TIME = 24 * 60 * 60 # 24 hours
AWAIT_TIME = 5 # 5s between each pull for stock data
HEADERS = requests.utils.default_headers()
HEADERS.update({'User-Agent': 'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36'})

# Constants for SQL queries
GET_COLLECTED_DATA_AT_NEWDAY_FOR_SOURCE_ID_AND_STOCK_ID = "SELECT pull_id, dirty_data FROM COLLECTED_DATA WHERE source_id={} AND stock_id={} AND pull_date > GETDATE();"
GET_DATA_SOURCES = "SELECT source_id, source_location, extension, search_terms FROM DATA_SOURCES;"
GET_STOCK_IDS = "SELECT stock_id FROM STOCK;"
GET_STOCK_ID_FOR_STOCK_NAME = "SELECT stock_id FROM STOCK WHERE stock_name=\"{}\";"
INSERT_CLEAN_DATA = "INSERT INTO CLEANED_DATA () VALUES ({},{},{},{},{});"
INSERT_INTO_COLLECTED_DATA = "INSERT INTO COLLECTED_DATA (source_id, stock_id, dirty_data) VALUES ({},{},\"{}\");"

# Constants for currencies (currently just USD and JPY)
DOLLAR = "$"
YEN = "¥"
CURRENCIES = [DOLLAR, YEN]

# Other constants
PERCENT = "%"

# this will be globally kept - the collector probably should be a class but oh well at this time
value_tag_class = None
rate_of_change_class = None

def maria_db_factory(user, password, host, port, database):
    '''
    Returns a connection cursor to mariadb
    '''
    conn = mariadb.connect(user=user, password=password, host=host, port=port, database=database)
    conn.autocommit = True
    return conn.cursor()


def learn_tag_contents(soupy):
    '''
    This method determines which tags will have currency values
    '''
    example_tag_value = soupy.find_next(lambda tag: DOLLAR in tag.contents)
    example_tag_rate_of_change = soupy.find_next(lambda tag: PERCENT in tag.contents)
    return example_tag_value['class'], example_tag_rate_of_change['class']


def get_values_seen(value_tags):
    '''
    Retrieves all of the values seen within the value tags.
    '''
    values = []
    for value_tag in value_tags:
        values.push(int(value_tag.value))
    return values


def cleaning_algorithm(dirty_data):
    '''
    Returns cleaned data based on the provided dirty data.
    '''
    price = -1.0
    rate_of_change = -1.0
    # clean my data please!
    # within the data
    soupy = BeautifulSoup(dirty_data, features='lxml')
    if value_tag_class == None and rate_of_change_class == None:
        # there are likely tags that contain numeric currency values
        value_tag_class, rate_of_change_class = learn_tag_contents(soupy)
    all_value_tags = soupy.find_all(value_tag_class)
    all_rate_of_change_tags = soupy.find_all(rate_of_change_class)
    # it is possible that there is only one numeric currency value in the content
    if len(all_value_tags) > 1:
        # if this is the case, just grab this
        price = float(all_value_tags[0].text)
        rate_of_change = float(all_rate_of_change_tags[0].text)
    
    return price, rate_of_change


if __name__ == '__main__':
    with open(CONFIG, 'r') as collector_config_file:
        collector_config_config = yaml.safe_load(collector_config_file)

    # connect to the DB
    mariadb_cursor = maria_db_factory(collector_config_config[MARIA_DB_CONFIG][USER], \
        collector_config_config[MARIA_DB_CONFIG][PASSWORD], \
        collector_config_config[MARIA_DB_CONFIG][MARIA_DB_IP], \
        collector_config_config[MARIA_DB_CONFIG][MARIA_DB_PORT], \
        collector_config_config[MARIA_DB_CONFIG][MARIA_DB_DATABASE])

    # while alive
    while True:
        # wait for it...
        # time.sleep(NAP_TIME)

        # COLLECTION
        # go through all DATA_SOURCES
        mariadb_cursor.execute(GET_DATA_SOURCES)
        data_sources = mariadb_cursor.fetchall()
        if len(data_sources) > 0:
            for (source_id, source_location, extension, search_terms) in data_sources:
                # go through all search_terms
                for search_term in search_terms.split(","):
                    resp = requests.get("https://{}/{}/{}".format(source_location, extension, search_term))
                    time.sleep(AWAIT_TIME) # be polite
                    # place the data into the COLLECTED_DATA
                    print(search_term)
                    mariadb_cursor.execute(GET_STOCK_ID_FOR_STOCK_NAME.format(search_term))
                    stock_id = mariadb_cursor.fetchall()
                    if len(stock_id) > 0:
                        print(INSERT_INTO_COLLECTED_DATA.format(source_id, stock_id[0], resp.content))
                        mariadb_cursor.execute(INSERT_INTO_COLLECTED_DATA.format(source_id, stock_id, resp.content))
                        print(str(source_id) + " " + str(stock_id) + str(resp.content))

        # CLEANING
        # Get every stock ID 
        mariadb_cursor.execute(GET_STOCK_IDS)
        stock_ids = mariadb_cursor.fetchall()
        mariadb_cursor.execute(GET_SOURCE_IDS) 
        source_ids = mariadb_cursor.fetchall()

        # Go through all stock_ids
        #for stock_id in stock_ids:
        for source_id in source_ids:
            value_tag_class = None
            rate_of_change_class = None

            for stock_id in stock_ids:
                # ...and get data from the past day that we collected
                mariadb_cursor.execute(GET_COLLECTED_DATA_AT_NEWDAY_FOR_SOURCE_ID_AND_STOCK_ID.format(source_id, stock_id))
                pull_id, source_id, dirty_data = mariadb_cursor.fetchall()

                # For the dirty data, clean it and insert it into the DB
                price, rate_of_change = cleaning_algorithm(dirty_data)
                mariadb_cursor.execute(INSERT_CLEAN_DATA.format(stock_id, pull_id, source_id, price, rate_of_change))
