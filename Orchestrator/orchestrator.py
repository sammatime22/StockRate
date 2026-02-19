# A program used to orchestrate the backend automation of Stockrate.
# sammatime22, 2026
from enum import Enum
import math
import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import requests
import time
import threading
import stomp
import sys
import yaml
from factory import stomp_factory


class Orchestrator(stomp.ConnectionListener):
    '''
    The orchestrator for StockRate.
    '''

    COLLECTION_REQUEST = '{{"time": {}}}'
    DISTRIBUTION_REQUEST = COLLECTION_REQUEST
    SEND_TIME = 283 # When we get past 00:00z, and provided we are not still in Collection, we will kick off Collection
    WAIT_TIME = 60 # Seconds

    class OrchestratorState(Enum):
        AWAITING = 0
        AMID_COLLECTION = 1
        AMID_DISTRIBUTION = 2

    matchadb_url = None
    stats_to_post = None
    logger = None
    handler = RotatingFileHandler(
        'orchestrator.log',
        maxBytes = 2_000_000,
        backupCount = 1
    )
    stomp_connection = None
    current_state = None


    def __init__(self, matchadb_url):
        '''
        Initializes the Orchestrator

        Parameters:
        -----------
        matchadb_url: the URL of the MatchaDB instance to post updates to
        '''
        self.logger = logging.getLogger()
        self.handler.stream.flush()
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.INFO)
        self.matchadb_url = matchadb_url


    def matcha_db_post(self, updates_to_post):
        '''
        Posts daily status to the MatchaDB instance

        Parameters:
        -----------
        updates_to_post: the updates to post to the MatchaDB instance
        '''
        try:
            requests.post(self.matchadb_url, data = repr(updates_to_post))
            return True
        except Exception as e:
            print("An error has occurred: " + str(e))
            return False


    def handle_collector_response(self, message_body):
        '''
        Handles the response from the Collector.

        Parameters:
        -----------
        message_body: the body of the message received from the Collector
        '''
        # send message to kick off distributor
        self.stats_to_post["stats"]["collection_stop"] = message_body["collection_stop"]
        distribution_start = datetime.datetime.now().timestamp()
        self.stomp_connection.send("/distribution", self.DISTRIBUTION_REQUEST.format(int(distribution_start)))
        self.stats_to_post["stats"]["distribution_start"] = distribution_start
        self.current_state = self.OrchestratorState.AMID_DISTRIBUTION


    def handle_distributor_response(self, message_body):
        '''
        Handles the response from the Distributor.

        Parameters:
        -----------
        message_body: the body of the message received from the Distributor
        '''
        # insert metadata on job in DB
        self.stats_to_post["stats"]["distribution_stop"] = message_body["distribution_stop"]
        self.current_state = self.OrchestratorState.AWAITING
        self.logger.info("Received Distributor response (at {:02}:{:02}z): {}".format(datetime.datetime.now().hour, datetime.datetime.now().minute, message_body))
        self.matcha_db_post(self.stats_to_post)
        self.stats_to_post = None


    def on_message(self, headers, message):
        '''
        Collects messages for the Orchestrator.

        Parameters:
        -----------
        headers: the headers of the message received
        message: the message received
        '''
        message_body = json.loads(str(message.body))
        if headers['destination'] == '/collector':
            handle_collector_response(message_body)
        elif headers['destination'] == '/distributor':
            handle_distributor_response(message_body)
            matcha_db_post(self.stats_to_post)
            self.stats_to_post = None

    
    def set_stomp_connection(self, stomp_connection):
        '''
        Sets the Orchestrator's STOMP connection.

        Parameters:
        -----------
        stomp_connection: the STOMP connection to set for the Orchestrator
        '''
        self.stomp_connection = stomp_connection


    def main_loop(self):
        '''
        Schedules components to run at particular times.
        '''
        self.current_state = self.OrchestratorState.AWAITING
        while True:
            # assess the time - how can we determine that we are at the time where we need to send a request to the collector?
            current_time_mins = (math.ceil(time.time() * 1000) % 86400000) // (60 * 1000)
            if current_time_mins == self.SEND_TIME:
                if self.current_state == self.OrchestratorState.AWAITING:
                    # do stuff
                    self.stats_to_post = {"timestamp": datetime.datetime.now(), "stats": {}}
                    collection_start = datetime.datetime.now().timestamp()
                    self.stomp_connection.send("/collection", self.COLLECTION_REQUEST.format(int(collection_start)))
                    self.stats_to_post["stats"]["collection_start"] = collection_start
                    self.current_state = self.OrchestratorState.AMID_COLLECTION
                else:
                    self.logger.info("something could be wrong..")
            else:
                self.logger.info("The time is recorded as {:02}:{}z - awaiting {:02}:{}z".format(current_time_mins // 60, current_time_mins % 60, self.SEND_TIME // 60, self.SEND_TIME % 60))
            # await the "wait time"
            time.sleep(self.WAIT_TIME)
            self.logger.info("I am alive")


ORCHESTRATOR_CONFIG = "orchestrator-config-private.yaml"
MATCHA_DB_URL = "matcha_db_url"
ORCHESTRATOR_ID = 12345

# Orchestrator Setup
with open(ORCHESTRATOR_CONFIG, "r") as orchestrator_config_file:
    orchestrator_config = yaml.safe_load(orchestrator_config_file)
    orchestrator = Orchestrator(orchestrator_config[MATCHA_DB_URL])
    stomp_factory(orchestrator, ORCHESTRATOR_ID, orchestrator_config["stomp_config"])
    orchestrator_thread = threading.Thread(target=orchestrator.main_loop)

    # Starting Orchestrator
    orchestrator_thread.start()
