# A class used to collect stock data from the web.
# sammatime22, 2024
import mariadb
import yaml

CONFIG = "collector-config-private.yaml"
MARIA_DB_CONFIG = "maria_db_config"
USER = "user"
PASSWORD = "password"
MARIA_DB_IP = "maria_db_ip"
MARIA_DB_PORT = "maria_db_port"
MARIA_DB_DATABASE = "maria_db_database"

def maria_db_factory(user, password, host, port, database):
    '''
    Returns a connection cursor to mariadb
    '''
    conn = mariadb.connect(user=user, password=password, host=host, port=port, database=database)
    conn.autocommit = True
    return conn.cursor()

if __name__ == '__main__':
    with open(CONFIG, 'r') as collector_config_file:
        collector_config_config = yaml.safe_load(collector_config)

    # connect to the DB

    # while alive
        # wait for it...
        # go through all DATA_SOURCES
            # go through all search_terms
                # if we get data back
                    # place the data into the COLLECTED_DATA
