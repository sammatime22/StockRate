# A class used to collect stock data from the web.
# sammatime22, 2024
import date
import mariadb
import time
import yaml

# Constants to pull from config file
CONFIG = "collector-config-private.yaml"
MARIA_DB_CONFIG = "maria_db_config"
USER = "user"
PASSWORD = "password"
MARIA_DB_IP = "maria_db_ip"
MARIA_DB_PORT = "maria_db_port"
MARIA_DB_DATABASE = "maria_db_database"

# Constants for operations
NAP_TIME = 24 * 60 * 60 # 24 hours
AWAIT_TIME = 5 # 5s between each pull for stock data
HEADERS = requests.utils.default_headers()
HEADERS.update({'User-Agent': 'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36'})

# Constants for SQL queries
GET_COLLECTED_DATA_AT_NEWDAY_FOR_STOCK_ID = "SELECT pull_id, source_id, dirty_data FROM COLLECTED_DATA WHERE stock_id={} AND pull_date > GETDATE();"
GET_DATA_SOURCES = "SELECT source_location, extension, search_terms FROM DATA_SOURCES;"
GET_STOCK_IDS = "SELECT stock_id FROM STOCK;"
GET_STOCK_ID_FOR_STOCK_NAME = "SELECT stock_id FROM STOCK WHERE stock_name=\"{}\";"
INSERT_CLEAN_DATA = "INSERT INTO CLEANED_DATA () VALUES ({},{},{},{},{});"
INSERT_INTO_COLLECTED_DATA = "INSERT INTO COLLECTED_DATA (source_id, stock_id, dirty_data) VALUES ({},{},{});"

def maria_db_factory(user, password, host, port, database):
    '''
    Returns a connection cursor to mariadb
    '''
    conn = mariadb.connect(user=user, password=password, host=host, port=port, database=database)
    conn.autocommit = True
    return conn.cursor()


def cleaning_algorithm(dirty_data):
    '''
    Returns cleaned data based on the provided dirty data.
    '''
    clean_data = dirty_data
    # clean my data please!
    price = 0.0
    rate_of_change = 0.0
    return price, rate_of_change


if __name__ == '__main__':
    with open(CONFIG, 'r') as collector_config_file:
        collector_config_config = yaml.safe_load(collector_config)

    # connect to the DB
    mariadb_cursor = maria_db_factory()

    # while alive
    while True:
        # wait for it...
        time.sleep(NAP_TIME)

        # COLLECTION
        # go through all DATA_SOURCES
        mariadb_cursor.execute(GET_DATA_SOURCES)
        data_sources = mariadb_cursor.fetchall()
        if len(data_sources) > 0:
            for (source_id, source_location, extension, search_terms) in data_sources:
                # go through all search_terms
                for search_term in search_terms.split(","):
                    resp = requests.get("https://{}/{}/{}".format(source_location, extension, search_term)
                    # place the data into the COLLECTED_DATA
                    mariadb_cursor.execute(GET_STOCK_ID_FOR_STOCK_NAME.format(search_term))
                    stock_id = mariadb_cursor.fetchall()
                    mariadb_cursor.execute(INSERT_INTO_COLLECTED_DATA.format(source_id, stock_id, resp.content))

        # CLEANING
        # Get every stock ID 
        mariadb_cursor.execute(GET_STOCK_IDS)
        stock_ids = mariadb_cursor.fetchall()
        
        # Go through all stock_ids
        for stock_id in stock_ids:
            # ...and get data from the past day that we collected
            mariadb_cursor.execute(GET_COLLECTED_DATA_AT_NEWDAY_FOR_STOCK_ID.format(stock_id))
            dirty_data_points = mariadb_cursor.fetchall()

            # For all the dirty data, clean it and insert it into the DB
            for (pull_id, source_id, dirty_data) in dirty_data_points:
                price, rate_of_change = cleaning_algorithm(dirty_data)
                mariadb_cursor.execute(CLEANED_DATA.format(stock_id, pull_id, source_id, price, rate_of_change))
