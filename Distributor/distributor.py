# A program used to send collected data via email.
# sammatime22, 2024
from factory import stomp_factory
from logging.handlers import RotatingFileHandler
import asyncio
import datetime
import google.generativeai as genai
import json
import logging
import mariadb
import stomp
import threading
import time
import traceback
import yagmail
import yaml
# Ensure yaml library works as intended in future Python versions
import collections
import collections.abc
collections.Hashable = collections.abc.Hashable


class Distributor(stomp.ConnectionListener):

    # Constants to pull from config file
    MARIA_DB_CONFIG = "maria_db_config"
    USER = "user"
    PASSWORD = "password"
    MARIA_DB_IP = "host"
    MARIA_DB_PORT = "port"
    MARIA_DB_DATABASE = "database"
    GOOGLE_GEMINI_CONFIG = "google_gemini_config"
    MY_KEY = "my_key"
    EMAIL_CONFIG = "email_config"
    ATTACHMENT = "attachment"
    EMAIL_ADDRESS = "email_address"
    OAUTH2_FILE = "oauth2_file"

    # Constants for operations
    LIMIT = 20 # temp

    # Constants for SQL queries
    SELECT_ALL_DATA_FROM_PAST_DAYS="SELECT stock_id, price FROM CLEANED_DATA ORDER BY pull_id DESC LIMIT {};"
    SELECT_STOCK_NAME_AND_ACRONYM="SELECT stock_name, acronym FROM STOCK WHERE stock_id={};"
    SELECT_USERS="SELECT email FROM USER;"
 
    # Logging
    logger = None
    handler = RotatingFileHandler(
        'distributor.log',
        maxBytes = 2_000_000,
        backupCount = 1
    )

    # STOMP stuff
    stomp_connection = None

    # Whether we are actively distributing or not
    active = False

    # For the asyncio loop
    loop = None
    thread = None

    def __init__(self, distributor_config):
        '''
        The initializer for the Distributor.

        This initializes an asyncio loop for the Distributor, separating the distribution process from the STOMP listener.

        Parameters:
        -----------
        distributor_config: The configuration for the Distributor's MariaDB connection, GenAI connection, and email connection.
        '''
        self.CONFIG = distributor_config

        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

        self.logger = logging.getLogger()
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.INFO)

        # Startup Message
        self.logger.info("Distributor started at {}".format(datetime.datetime.now().timestamp()))
        self.logger.info("Distributor configuration: {}".format(distributor_config))


    def maria_db_factory(user, password, host, port, database):
        '''
        Returns a connection cursor to mariadb
        '''
        conn = mariadb.connect(user=user, password=password, host=host, port=port, database=database)
        conn.autocommit = True
        return conn.cursor()


    def format_findings(self, findings, mariadb_cursor):
        '''
        Properly formats the data retrieved from the DB into a CSV format
        '''
        try:
            contents = "Stock Name,Stock Acronym,Yesterday's Price,Today's Price,Total Difference,Percent Difference\n"
            findings_dict = {}
            for (stock_id, price) in findings:
                # add findings to findings_dict list
                if findings_dict.get(stock_id) == None:
                    findings_dict[stock_id] = []
                findings_dict[stock_id].append(price)
            
            # run calculations on findings, putting this in CSV format
            for key, value in findings_dict.items():
                mariadb_cursor.execute(self.SELECT_STOCK_NAME_AND_ACRONYM.format(key))
                stock_of_interest_data = mariadb_cursor.fetchall()
                for (stock_name, stock_acronym) in stock_of_interest_data:
                    contents = contents + "{},{},{},{},{},{}\n".format(stock_name, stock_acronym, value[1], value[0], value[0] - value[1], (value[0] - value[1])/value[1])
            return contents
        except Exception as e:
            traceback.print_exc()
            return None


    async def conduct_distribution(self):
        '''
        The main thread to conduct the distribution
        '''
        # get config loaded
        distributor_config_config = self.CONFIG

        self.logger.info("Distributor configuration: {}".format(distributor_config_config))

        # connect to the DB
        mariadb_cursor = self.maria_db_factory(distributor_config_config[self.MARIA_DB_CONFIG][self.USER], \
            distributor_config_config[self.MARIA_DB_CONFIG][self.PASSWORD], \
            distributor_config_config[self.MARIA_DB_CONFIG][self.MARIA_DB_IP], \
            distributor_config_config[self.MARIA_DB_CONFIG][self.MARIA_DB_PORT], \
            distributor_config_config[self.MARIA_DB_CONFIG][self.MARIA_DB_DATABASE])
        self.logger.info("Connected to MariaDB at {}".format(datetime.datetime.now().timestamp()))

        # Gemini setup
        genai.configure(api_key=distributor_config_config[self.GOOGLE_GEMINI_CONFIG][self.MY_KEY])
        model = genai.GenerativeModel("gemini-2.0-flash")

        # check and gather the stock data from one pull ago and the most recent pull
        mariadb_cursor.execute(self.SELECT_ALL_DATA_FROM_PAST_DAYS.format(self.LIMIT))
        data = self.format_findings(mariadb_cursor.fetchall(), mariadb_cursor)

        # ask AI for some insight
        if data is not None:
            self.logger.info("Data could be pulled, and we will attempt to query the AI agent for insights at {}".format(datetime.datetime.now().timestamp()))
            query = "Can you please tell me out of this data which three stocks had the biggest change?\n" + data

            # put AI response in email
            ai_response = None
            try:
                ai_response = model.generate_content(query)
                ai_response = ai_response.text
            except Exception as e:
                ai_response = "An error occurred in querying the AI agent."
                traceback.print_exc()

            # get recipients from DB
            mariadb_cursor.execute(self.SELECT_USERS)
            recipient_list = mariadb_cursor.fetchall()
            recipients = []
            for recipient in recipient_list:
                recipients.append(recipient[0])

            # put content in .csv
            csv_content = open(distributor_config_config[self.EMAIL_CONFIG][self.ATTACHMENT], "w+")
            csv_content.truncate(0) # erase data before writing
            csv_content.write(data)
            csv_content.close()
            yag = yagmail.SMTP(distributor_config_config[self.EMAIL_CONFIG][self.EMAIL_ADDRESS], oauth2_file=distributor_config_config[self.EMAIL_CONFIG][self.OAUTH2_FILE])
            yag.send(
                to=recipients,
                subject="Todays Stock Data " + str(datetime.datetime.now()),
                contents=ai_response,
                attachments=[distributor_config_config[self.EMAIL_CONFIG][self.ATTACHMENT]]
            )
        else:
            self.logger.info("Data could not be pulled, and we will request an apology statement from the AI agent at {}".format(datetime.datetime.now().timestamp()))
            query = "Can you write an apology statement saying the data pipeline had an issue developing today's results, and we are working to fix it? Don't provide a date."

            # put AI response in email
            ai_response = None
            try:
                ai_response = model.generate_content(query)
                ai_response = ai_response.text
            except Exception as e:
                ai_response = "An error occurred in querying the AI agent."
                traceback.print_exc()

            # get recipients from DB
            mariadb_cursor.execute(self.SELECT_USERS)
            recipient_list = mariadb_cursor.fetchall()
            recipients = []
            for recipient in recipient_list:
                recipients.append(recipient[0])

            yag = yagmail.SMTP(distributor_config_config[self.EMAIL_CONFIG][self.EMAIL_ADDRESS], oauth2_file=distributor_config_config[self.EMAIL_CONFIG][self.OAUTH2_FILE])
            yag.send(
                to=recipients,
                subject="StockRate Pipeline Issue " + str(datetime.datetime.now()),
                contents=ai_response.text
            )
        self.stomp_connection.send("/topic/distribution-reply", json.dumps({"distribution_stop": datetime.datetime.now().timestamp()}))
        self.active = False
        self.logger.info("Finished distribution at {}".format(datetime.datetime.now().timestamp()))


    def on_message(self, message):
        '''
        Collects messages for the Distributor.

        Parameters:
        -----------
        headers: the headers of the message received
        message: the message received
        '''
        try:
            if not self.active:
                self.active = True
                asyncio.run_coroutine_threadsafe(self.conduct_distribution(), self.loop)
            else:
                self.logger.warning("Already active, ignoring message")
        except Exception as e:
            self.logger.error("Catching exception, {}". format(e))


    def set_stomp_connection(self, stomp_connection):
        '''
        Sets the Distributor's STOMP connection.

        Parameters:
        -----------
        stomp_connection: the STOMP connection to set for the Distributor
        '''
        self.stomp_connection = stomp_connection


    def main_loop(self):
        '''
        Keeps the Distributor alive
        '''
        while True:
            time.sleep(10)


# Distributor Setup
DISTRIBUTOR_ID = 34787
DISTRIBUTOR_CONFIG = "/config-dir/distributor-config-private.yaml"
with open(DISTRIBUTOR_CONFIG, "r") as distributor_config_file:
    distributor_config = yaml.safe_load(distributor_config_file)
    distributor = Distributor(distributor_config)
    stomp_factory(distributor, DISTRIBUTOR_ID, distributor_config["stomp_config"])
    distributor_thread = threading.Thread(target=distributor.main_loop)

    # Starting Distributor
    distributor_thread.start()
