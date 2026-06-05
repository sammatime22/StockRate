# A program used to orchestrate the backend automation of Stockrate.
# sammatime22, 2026
from enum import Enum
from factory import stomp_factory
from logging.handlers import RotatingFileHandler
import asyncio
import datetime
import json
import logging
import math
import requests
import stomp
import sys
import time
import threading
import yaml


class Orchestrator(stomp.ConnectionListener):
    '''
    The Orchestrator class, which is responsible for orchestrating the Collector and Distributor.
    '''

    class OrchestratorState(Enum):
        AWAITING = 0
        AMID_COLLECTION = 1
        AMID_DISTRIBUTION = 2

    # Constants for Orchestrator
    # Constants for timing and requests
    COLLECTION_REQUEST = '{{"time": {}}}'
    DISTRIBUTION_REQUEST = COLLECTION_REQUEST
    SEND_TIME = 283 # When we get past 00:00z, and provided we are not still in Collection, we will kick off Collection
    WAIT_TIME = 60 # Seconds

    # Variables for MatchaDB related things
    matchadb_url = None
    stats_to_post = None

    # Logging
    logger = None
    handler = RotatingFileHandler(
        'orchestrator.log',
        maxBytes = 2_000_000,
        backupCount = 1
    )

    # STOMP stuff
    stomp_connection = None

    # Current state
    current_state = None

    # For the asyncio loop
    loop = None
    thread = None

    def __init__(self, matchadb_url):
        '''
        The initializer for the Orchestrator.

        Parameters:
        -----------
        matchadb_url: the URL of the MatchaDB instance to post updates to
        '''
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

        self.logger = logging.getLogger()
        self.handler.stream.flush()
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.INFO)

        self.matchadb_url = matchadb_url


    def matcha_db_post(self, updates_to_post):
        '''
        Posts daily status to the MatchaDB instance.

        Parameters:
        -----------
        updates_to_post: the updates to post to the MatchaDB instance

        Returns:
        -----------
        - whether the post was successful as a boolean
        '''
        try:
            requests.post(self.matchadb_url, data = repr(updates_to_post))
            self.logger.info("Successfully posted to MatchaDB at {}: {}".format(datetime.datetime.now().timestamp(), updates_to_post))
            return True
        except Exception as e:
            self.logger.error("An error has occurred in posting to MatchaDB at {}: {}".format(datetime.datetime.now().timestamp(), str(e)))
            return False


    async def handle_collector_response(self, message_body):
        '''
        Handles the response from the Collector.

        Parameters:
        -----------
        message_body: the body of the message received from the Collector
        '''
        # send message to kick off distributor
        self.logger.info("Received Collector response (at {:02}:{:02}z): {}".format(datetime.datetime.now().hour, datetime.datetime.now().minute, message_body))
        self.stats_to_post["stats"]["collection_stop"] = message_body["collection_stop"]
        distribution_start = datetime.datetime.now().timestamp()
        self.stomp_connection.send("/topic/distribution-request", self.DISTRIBUTION_REQUEST.format(int(distribution_start)))
        self.stats_to_post["stats"]["distribution_start"] = distribution_start
        self.current_state = self.OrchestratorState.AMID_DISTRIBUTION
        self.logger.info("Moving from Collection to Distribution at {}".format(datetime.datetime.now().timestamp()))


    async def handle_distributor_response(self, message_body):
        '''
        Handles the response from the Distributor.

        Parameters:
        -----------
        message_body: the body of the message received from the Distributor
        '''
        # insert metadata on job in DB
        self.logger.info("Received Distributor response (at {:02}:{:02}z): {}".format(datetime.datetime.now().hour, datetime.datetime.now().minute, message_body))
        self.stats_to_post["stats"]["distribution_stop"] = message_body["distribution_stop"]
        self.current_state = self.OrchestratorState.AWAITING
        self.logger.info("Received Distributor response (at {:02}:{:02}z): {}".format(datetime.datetime.now().hour, datetime.datetime.now().minute, message_body))
        self.matcha_db_post(self.stats_to_post)
        self.stats_to_post = None
        self.current_state = self.OrchestratorState.AWAITING


    def on_message(self, message):
        '''
        Collects messages for the Orchestrator.

        Parameters:
        -----------
        message: the message received
        '''
        message_body = json.loads(message.body)
        if message.headers['destination'] == '/topic/collection-reply':
            asyncio.run_coroutine_threadsafe(self.handle_collector_response(message_body), self.loop)
        elif message.headers['destination'] == '/topic/distribution-reply':
            asyncio.run_coroutine_threadsafe(self.handle_distributor_response(message_body), self.loop)
    

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
            #if current_time_mins == self.SEND_TIME:
            if current_time_mins == self.SEND_TIME:
                if self.current_state == self.OrchestratorState.AWAITING:
                    # do stuff
                    self.stats_to_post = {"timestamp": datetime.datetime.now(), "stats": {}}
                    self.logger.info(""self.stats_to_post)
                    collection_start = datetime.datetime.now().timestamp()
                    self.logger.info(collection_start)
                    self.stomp_connection.send("/topic/collection-request", self.COLLECTION_REQUEST.format(int(collection_start)))
                    self.logger.info("Sent Collection Request at {}".format(datetime.datetime.now().timestamp()))
                    self.stats_to_post["stats"]["collection_start"] = collection_start
                    self.current_state = self.OrchestratorState.AMID_COLLECTION
                else:
                    self.logger.info("something could be wrong..")
            else:
                self.logger.info("The time is recorded as {:02}:{}z - awaiting {:02}:{}z".format(current_time_mins // 60, current_time_mins % 60, self.SEND_TIME // 60, self.SEND_TIME % 60))
            # await the "wait time"
            time.sleep(self.WAIT_TIME)
            self.logger.info("I am alive")


# Orchestrator Setup
ORCHESTRATOR_ID = 12345
ORCHESTRATOR_CONFIG = "/config-dir/orchestrator-config-private.yaml"
with open(ORCHESTRATOR_CONFIG, "r") as orchestrator_config_file:
    orchestrator_config = yaml.safe_load(orchestrator_config_file)
    orchestrator = Orchestrator(orchestrator_config["matcha_db_url"])
    stomp_factory(orchestrator, ORCHESTRATOR_ID, orchestrator_config["stomp_config"])
    orchestrator_thread = threading.Thread(target=orchestrator.main_loop)

    # Starting Orchestrator
    orchestrator_thread.start()
