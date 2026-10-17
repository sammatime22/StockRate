# Unit tests for the Orchestrator with no STOMP broker, MatchaDB or config file.
# sammatime22, 2026
#
# orchestrator.py is loaded with stomp, factory, yaml and requests stubbed out, the config file
# replaced by an in-memory dict, and the module-level main loop thread held back so nothing runs
# on import. Each test gets its own Orchestrator with:
#
#   - a fake clock driving the module's `time` and `datetime`, so a whole day of main_loop runs in
#     milliseconds (time.sleep advances the clock instead of waiting)
#   - a recorder in place of the STOMP connection
#   - a mock in place of requests.post (nothing is posted to MatchaDB)
#
# Collector and Distributor replies go through on_message and the Orchestrator's real asyncio
# loop thread, as they do in production.
#
# The tests only need the Python standard library. Run from the Orchestrator directory:
#   python3 -m unittest -v test_orchestrator.py
# or, with pytest installed (apk add py3-pytest on iSH):
#   python3 -m pytest -v test_orchestrator.py
#
# The failover tests (FailoverTests) check the 12 hour failover from PR #66. They run only when
# orchestrator.py has an attribute whose name mentions FAILOVER (FAILOVER, FAILOVER_MINS, ...), and
# are skipped otherwise.
import asyncio
import builtins
import calendar
import copy
import datetime
import importlib.util
import io
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ORCHESTRATOR_PATH = os.path.join(HERE, "orchestrator.py")
CONFIG_PATH = "/config-dir/orchestrator-config-private.yaml"
ORCHESTRATOR_ID = 12345

MATCHA_DB_URL = "http://matchadb.test/stats"
# Deliberately not the class defaults (SEND_TIME 283 = 04:43, total_active_collectors 1), so the
# tests show the configured values are used
KICKOFF_HOUR, KICKOFF_MINUTE = 6, 17
KICKOFF_MINS = KICKOFF_HOUR * 60 + KICKOFF_MINUTE
CONFIG = {
    "matcha_db_url": MATCHA_DB_URL,
    "total_active_collectors": 3,
    "kickoff": {"start_time_hour": KICKOFF_HOUR, "start_time_minute": KICKOFF_MINUTE},
    "stomp_config": {"ip": "activemq.test", "port": 61613, "username": "test", "password": "test",
                     "subscriptions": ["/topic/collection-reply", "/topic/distribution-reply"]},
}

COLLECTION_REQUEST = "/topic/collection-request"
COLLECTION_REPLY = "/topic/collection-reply"
DISTRIBUTION_REQUEST = "/topic/distribution-request"
DISTRIBUTION_REPLY = "/topic/distribution-reply"

MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR
# Midnight UTC at the start of an arbitrary day; the Orchestrator schedules in UTC
DAY_START = calendar.timegm((2026, 10, 19, 0, 0, 0))
KICKOFF = DAY_START + KICKOFF_MINS * MINUTE
FAILOVER_PERIOD = 12 * HOUR


class StopLoop(Exception):
    '''
    Raised by FakeClock.sleep to break out of Orchestrator.main_loop, which never returns.
    '''


class FakeClock:
    '''
    Stands in for the clock inside orchestrator.py: time.time/monotonic/perf_counter (and their _ns
    forms), time.gmtime/localtime/strftime with no time given, time.sleep, and
    datetime.datetime.now/today/utcnow and datetime.date.today.

    sleep() advances the clock (by `step` seconds if set, otherwise by the amount asked for),
    runs any callbacks scheduled with at() whose time has come, and raises StopLoop once the
    clock passes `stop_after`.
    '''

    def __init__(self, start, step=None):
        self.now = float(start)
        self.step = step
        self.stop_after = None
        self.scheduled = []

    def time(self):
        return self.now

    def time_ns(self):
        return int(self.now * 1_000_000_000)

    def at(self, when, callback):
        self.scheduled.append((when, callback))
        self.scheduled.sort(key=lambda item: item[0])

    def sleep(self, seconds):
        self.now += seconds if self.step is None else self.step
        while self.scheduled and self.scheduled[0][0] <= self.now:
            _, callback = self.scheduled.pop(0)
            callback()
        if self.stop_after is not None and self.now > self.stop_after:
            raise StopLoop()

    def time_module(self):
        fake = types.ModuleType("time")
        fake.__dict__.update(vars(time))
        fake.time = fake.monotonic = fake.perf_counter = self.time
        fake.time_ns = fake.monotonic_ns = fake.perf_counter_ns = self.time_ns
        # Called with no time given, these read the current time
        fake.gmtime = lambda secs=None: time.gmtime(self.now if secs is None else secs)
        fake.localtime = lambda secs=None: time.localtime(self.now if secs is None else secs)
        fake.strftime = lambda format, t=None: time.strftime(format, time.localtime(self.now) if t is None else t)
        fake.sleep = self.sleep
        return fake

    def datetime_module(self):
        clock = self

        class FakeDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.datetime.fromtimestamp(clock.now, tz)

            @classmethod
            def today(cls):
                return cls.now()

            @classmethod
            def utcnow(cls):
                return cls.now(datetime.timezone.utc).replace(tzinfo=None)

        class FakeDate(datetime.date):
            @classmethod
            def today(cls):
                return datetime.date.fromtimestamp(clock.now)

        fake = types.ModuleType("datetime")
        fake.__dict__.update(vars(datetime))
        fake.datetime = FakeDateTime
        fake.date = FakeDate
        return fake


class FakeStompConnection:
    def __init__(self):
        self.sent = []

    def send(self, destination, body):
        self.sent.append((destination, body))

    def bodies(self, destination):
        return [json.loads(body) for (sent_to, body) in self.sent if sent_to == destination]


class FakeMessage:
    def __init__(self, destination, body):
        self.headers = {"destination": destination}
        self.body = json.dumps(body)


def load_orchestrator():
    '''
    Loads orchestrator.py as a fresh module with its dependencies stubbed out. Returns a namespace
    holding the module, the stomp_factory calls made at import, and the main loops that the
    module-level setup tried to start (held back so they never run).
    '''
    stomp_stub = types.ModuleType("stomp")
    stomp_stub.ConnectionListener = object
    stomp_factory_calls = []
    factory_stub = types.ModuleType("factory")
    factory_stub.stomp_factory = lambda *args: stomp_factory_calls.append(args)
    yaml_stub = types.ModuleType("yaml")
    yaml_stub.safe_load = lambda stream: json.loads(json.dumps(CONFIG))
    requests_stub = types.ModuleType("requests")
    requests_stub.post = mock.Mock(side_effect=AssertionError("requests.post was not mocked"))

    real_open = builtins.open

    def fake_open(file, *args, **kwargs):
        if file == CONFIG_PATH:
            return io.StringIO("")
        return real_open(file, *args, **kwargs)

    held_back = []

    class HoldBackMainLoop(threading.Thread):
        def __init__(self, *args, target=None, **kwargs):
            super().__init__(*args, target=target, **kwargs)
            self.held_target = target

        def start(self):
            if getattr(self.held_target, "__name__", None) == "main_loop":
                held_back.append(self.held_target)
                return
            super().start()

    # orchestrator.log is created when the class is defined, so load from a scratch directory
    log_dir = tempfile.mkdtemp(prefix="orchestrator-test-")
    cwd = os.getcwd()
    spec = importlib.util.spec_from_file_location("orchestrator", ORCHESTRATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    stubs = {"stomp": stomp_stub, "factory": factory_stub, "yaml": yaml_stub, "requests": requests_stub}
    with mock.patch.dict(sys.modules, stubs), \
            mock.patch.object(builtins, "open", fake_open), \
            mock.patch.object(threading, "Thread", HoldBackMainLoop):
        os.chdir(log_dir)
        try:
            spec.loader.exec_module(module)
        finally:
            os.chdir(cwd)
    return types.SimpleNamespace(module=module, log_dir=log_dir, stomp_factory_calls=stomp_factory_calls,
                                 held_back=held_back)


def stop_event_loop(orchestrator):
    orchestrator.loop.call_soon_threadsafe(orchestrator.loop.stop)
    orchestrator.thread.join(timeout=5)
    if not orchestrator.thread.is_alive():
        orchestrator.loop.close()


def run_on_loop(orchestrator, coroutine):
    '''
    Runs a coroutine on the Orchestrator's own asyncio loop thread and returns its result.
    '''
    return asyncio.run_coroutine_threadsafe(coroutine, orchestrator.loop).result(timeout=5)


def flush(orchestrator):
    '''
    Waits for every task still pending on the Orchestrator's asyncio loop to finish.
    '''
    async def wait_for_other_tasks():
        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current]
        if pending:
            await asyncio.gather(*pending)

    run_on_loop(orchestrator, wait_for_other_tasks())


LOADED = None


def setUpModule():
    global LOADED
    LOADED = load_orchestrator()


def tearDownModule():
    module = LOADED.module
    if hasattr(module, "orchestrator"):
        stop_event_loop(module.orchestrator)
    logging.getLogger().removeHandler(module.Orchestrator.handler)
    module.Orchestrator.handler.close()
    shutil.rmtree(LOADED.log_dir, ignore_errors=True)


def has_failover():
    '''
    Whether orchestrator.py has a failover: any attribute whose name mentions FAILOVER, on the module
    or on an Orchestrator (so one set in __init__, e.g. from the config, counts too).
    '''
    module = LOADED.module
    probe = module.Orchestrator(MATCHA_DB_URL, 1)
    try:
        names = dir(module) + dir(probe)
    finally:
        stop_event_loop(probe)
    return any("FAILOVER" in name.upper() for name in names)


class OrchestratorTestCase(unittest.TestCase):
    '''
    Gives each test a fresh Orchestrator wired to a fake clock, a STOMP recorder and a mocked
    requests.post.
    '''

    def setUp(self):
        self.module = LOADED.module
        self.post = mock.Mock(return_value=mock.Mock(status_code=200))
        patcher = mock.patch.object(self.module.requests, "post", self.post)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_orchestrator(self, total_active_collectors=1, hour=KICKOFF_HOUR, minute=KICKOFF_MINUTE,
                          start=KICKOFF, step=None):
        self.clock = FakeClock(start, step)
        for name, fake in [("time", self.clock.time_module()), ("datetime", self.clock.datetime_module())]:
            patcher = mock.patch.object(self.module, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.orchestrator = self.module.Orchestrator(MATCHA_DB_URL, total_active_collectors, hour, minute)
        self.addCleanup(stop_event_loop, self.orchestrator)
        self.stomp = FakeStompConnection()
        self.orchestrator.set_stomp_connection(self.stomp)
        return self.orchestrator

    def run_main_loop_until(self, when):
        '''
        Runs main_loop for every minute up to and including `when` (epoch seconds).
        main_loop resets the state to AWAITING on entry, so only call this once per test.
        '''
        self.clock.stop_after = when
        with self.assertRaises(StopLoop):
            self.orchestrator.main_loop()

    def deliver(self, destination, body):
        '''
        Hands a message to on_message and waits for the handler it starts. An exception raised by
        the handler is re-raised here: on_message throws away the future that would carry it, and a
        handler that never awaits has already finished before flush() can see its task.
        '''
        futures = []

        def submit(coroutine, loop):
            futures.append(asyncio.run_coroutine_threadsafe(coroutine, loop))
            return futures[-1]

        module_asyncio = types.ModuleType("asyncio")
        module_asyncio.__dict__.update(vars(asyncio))
        module_asyncio.run_coroutine_threadsafe = submit
        with mock.patch.object(self.module, "asyncio", module_asyncio):
            self.orchestrator.on_message(FakeMessage(destination, body))
        flush(self.orchestrator)
        for future in futures:
            future.result(timeout=5)

    def collector_replies(self):
        self.deliver(COLLECTION_REPLY, {"collection_stop": self.clock.now})

    def distributor_replies(self):
        self.deliver(DISTRIBUTION_REPLY, {"distribution_stop": self.clock.now})

    @property
    def state(self):
        return self.module.Orchestrator.OrchestratorState


class ModuleSetupTests(OrchestratorTestCase):
    '''
    The module-level code that reads the config file and starts the Orchestrator.
    '''

    def setUp(self):
        super().setUp()
        if not hasattr(self.module, "orchestrator"):
            self.skipTest("orchestrator.py does not start an Orchestrator when imported")

    def test_reads_config_file(self):
        orchestrator = self.module.orchestrator
        self.assertEqual(orchestrator.matchadb_url, MATCHA_DB_URL)
        self.assertEqual(orchestrator.total_active_collectors, CONFIG["total_active_collectors"])
        self.assertEqual(orchestrator.SEND_TIME, KICKOFF_MINS)

    def test_connects_to_stomp_with_config(self):
        self.assertEqual(LOADED.stomp_factory_calls,
                         [(self.module.orchestrator, ORCHESTRATOR_ID, CONFIG["stomp_config"])])

    def test_starts_main_loop_thread(self):
        self.assertEqual(LOADED.held_back, [self.module.orchestrator.main_loop])


class InitTests(OrchestratorTestCase):

    def test_send_time_is_minutes_past_midnight(self):
        orchestrator = self.make_orchestrator(total_active_collectors=3, hour=4, minute=43)
        self.assertEqual(orchestrator.SEND_TIME, 283)
        self.assertEqual(orchestrator.total_active_collectors, 3)
        self.assertEqual(orchestrator.matchadb_url, MATCHA_DB_URL)

    def test_send_time_defaults_to_midnight(self):
        orchestrator = self.module.Orchestrator(MATCHA_DB_URL, 1)
        self.addCleanup(stop_event_loop, orchestrator)
        self.assertEqual(orchestrator.SEND_TIME, 0)

    def test_starts_background_event_loop(self):
        orchestrator = self.make_orchestrator()

        async def answer():
            return threading.current_thread()

        self.assertIs(run_on_loop(orchestrator, answer()), orchestrator.thread)
        self.assertTrue(orchestrator.thread.daemon)


class MatchaDBPostTests(OrchestratorTestCase):

    def test_posts_stats(self):
        orchestrator = self.make_orchestrator()
        stats = {"timestamp": "today", "stats": {"collection_start": 1.0}}
        self.assertTrue(orchestrator.matcha_db_post(stats))
        self.post.assert_called_once_with(MATCHA_DB_URL, data=repr(stats))

    def test_returns_false_and_logs_when_post_fails(self):
        orchestrator = self.make_orchestrator()
        self.post.side_effect = ConnectionError("MatchaDB is down")
        with self.assertLogs(level=logging.ERROR) as logs:
            self.assertFalse(orchestrator.matcha_db_post({"stats": {}}))
        self.assertIn("MatchaDB is down", "\n".join(logs.output))


class OnMessageTests(OrchestratorTestCase):

    def setUp(self):
        super().setUp()
        orchestrator = self.make_orchestrator()
        self.collector_handler = mock.AsyncMock()
        self.distributor_handler = mock.AsyncMock()
        for name, handler in [("handle_collector_response", self.collector_handler),
                              ("handle_distributor_response", self.distributor_handler)]:
            patcher = mock.patch.object(orchestrator, name, handler)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_routes_collection_reply_to_collector_handler(self):
        self.deliver(COLLECTION_REPLY, {"collection_stop": 1.5})
        self.collector_handler.assert_awaited_once_with({"collection_stop": 1.5})
        self.distributor_handler.assert_not_awaited()

    def test_routes_distribution_reply_to_distributor_handler(self):
        self.deliver(DISTRIBUTION_REPLY, {"distribution_stop": 2.5})
        self.distributor_handler.assert_awaited_once_with({"distribution_stop": 2.5})
        self.collector_handler.assert_not_awaited()

    def test_ignores_other_destinations(self):
        self.deliver("/topic/something-else", {"hello": "world"})
        self.collector_handler.assert_not_awaited()
        self.distributor_handler.assert_not_awaited()


class CollectorResponseTests(OrchestratorTestCase):

    def start_collection(self, total_active_collectors):
        # Kick off for real rather than setting attributes, so any other per-run state is set up too
        orchestrator = self.make_orchestrator(total_active_collectors=total_active_collectors)
        self.run_main_loop_until(KICKOFF)
        self.stomp.sent.clear()
        return orchestrator

    def test_starts_distribution_when_collector_replies(self):
        orchestrator = self.start_collection(total_active_collectors=1)
        self.clock.now = KICKOFF + 30 * MINUTE
        run_on_loop(orchestrator, orchestrator.handle_collector_response({"collection_stop": KICKOFF + 29 * MINUTE}))

        self.assertEqual(self.stomp.sent, [(DISTRIBUTION_REQUEST, '{"time": %d}' % (KICKOFF + 30 * MINUTE))])
        self.assertEqual(orchestrator.current_state, self.state.AMID_DISTRIBUTION)
        self.assertEqual(orchestrator.stats_to_post["stats"], {
            "collection_start": KICKOFF,
            "collection_stop": KICKOFF + 29 * MINUTE,
            "distribution_start": KICKOFF + 30 * MINUTE,
        })
        self.assertEqual(orchestrator.collector_responses_returned, 0)

    def test_waits_for_every_collector(self):
        orchestrator = self.start_collection(total_active_collectors=3)
        for replies in (1, 2):
            run_on_loop(orchestrator, orchestrator.handle_collector_response({"collection_stop": KICKOFF + replies}))
            self.assertEqual(self.stomp.sent, [])
            self.assertEqual(orchestrator.current_state, self.state.AMID_COLLECTION)
            self.assertEqual(orchestrator.collector_responses_returned, replies)

        run_on_loop(orchestrator, orchestrator.handle_collector_response({"collection_stop": KICKOFF + 3}))
        self.assertEqual(len(self.stomp.bodies(DISTRIBUTION_REQUEST)), 1)
        self.assertEqual(orchestrator.current_state, self.state.AMID_DISTRIBUTION)
        self.assertEqual(orchestrator.stats_to_post["stats"]["collection_stop"], KICKOFF + 3)
        self.assertEqual(orchestrator.collector_responses_returned, 0)


class DistributorResponseTests(OrchestratorTestCase):

    def test_posts_stats_and_returns_to_awaiting(self):
        # Kick off and collect for real rather than setting attributes
        orchestrator = self.make_orchestrator()
        self.run_main_loop_until(KICKOFF)
        self.clock.now = KICKOFF + 30 * MINUTE
        self.collector_replies()
        self.assertEqual(orchestrator.current_state, self.state.AMID_DISTRIBUTION)
        expected = copy.deepcopy(orchestrator.stats_to_post)
        expected["stats"]["distribution_stop"] = KICKOFF + HOUR

        run_on_loop(orchestrator, orchestrator.handle_distributor_response({"distribution_stop": KICKOFF + HOUR}))

        self.post.assert_called_once_with(MATCHA_DB_URL, data=repr(expected))
        self.assertIsNone(orchestrator.stats_to_post)
        self.assertEqual(orchestrator.current_state, self.state.AWAITING)


class MainLoopTests(OrchestratorTestCase):

    def test_sends_collection_request_at_kickoff_minute(self):
        orchestrator = self.make_orchestrator(start=KICKOFF)
        self.run_main_loop_until(KICKOFF)

        self.assertEqual(self.stomp.sent, [(COLLECTION_REQUEST, '{"time": %d}' % KICKOFF)])
        self.assertEqual(orchestrator.current_state, self.state.AMID_COLLECTION)
        self.assertEqual(orchestrator.stats_to_post, {
            "timestamp": datetime.datetime.fromtimestamp(KICKOFF),
            "stats": {"collection_start": KICKOFF},
        })

    def test_waits_until_kickoff_minute(self):
        # Runs from midnight, so a loop that sleeps for more than a minute steps over the kickoff
        orchestrator = self.make_orchestrator(start=DAY_START)

        def nothing_sent_yet():
            self.assertEqual(self.stomp.sent, [])
            self.assertEqual(orchestrator.current_state, self.state.AWAITING)

        self.clock.at(KICKOFF, nothing_sent_yet)
        self.run_main_loop_until(KICKOFF + MINUTE - 1)
        sent = self.stomp.bodies(COLLECTION_REQUEST)
        self.assertEqual(len(sent), 1)
        self.assertTrue(KICKOFF <= sent[0]["time"] < KICKOFF + MINUTE, sent)

    def test_kickoff_minute_is_utc(self):
        # The kickoff in UTC is a different wall-clock hour in every other zone; only UTC should match.
        # Hosts and containers are often on UTC themselves, so run this one at UTC-7 ("XYZ+7" is a
        # POSIX TZ string, so no tzdata is needed) to tell local time from UTC.
        if not hasattr(time, "tzset"):
            self.skipTest("time.tzset is not available to change the local time zone")
        self.addCleanup(time.tzset)
        environ = mock.patch.dict(os.environ, {"TZ": "XYZ+7"})
        environ.start()
        self.addCleanup(environ.stop)
        time.tzset()
        self.make_orchestrator(start=KICKOFF - HOUR)
        self.run_main_loop_until(KICKOFF)
        self.assertEqual(self.stomp.bodies(COLLECTION_REQUEST), [{"time": KICKOFF}])

    def test_sends_one_request_per_kickoff_even_if_loop_runs_faster(self):
        orchestrator = self.make_orchestrator(start=KICKOFF, step=10)
        self.run_main_loop_until(KICKOFF + 59)
        self.assertEqual(len(self.stomp.bodies(COLLECTION_REQUEST)), 1)
        self.assertEqual(orchestrator.current_state, self.state.AMID_COLLECTION)

    def test_full_cycle_then_next_day_kickoff(self):
        orchestrator = self.make_orchestrator(start=KICKOFF)
        self.clock.at(KICKOFF + 30 * MINUTE, self.collector_replies)
        self.clock.at(KICKOFF + 60 * MINUTE, self.distributor_replies)
        self.clock.at(KICKOFF + 61 * MINUTE,
                      lambda: self.assertEqual(orchestrator.current_state, self.state.AWAITING))
        self.run_main_loop_until(KICKOFF + DAY)

        self.assertEqual(self.stomp.bodies(COLLECTION_REQUEST), [{"time": KICKOFF}, {"time": KICKOFF + DAY}])
        self.assertEqual(self.stomp.bodies(DISTRIBUTION_REQUEST), [{"time": KICKOFF + 30 * MINUTE}])
        self.assertEqual(self.post.call_count, 1)
        posted = self.post.call_args.kwargs["data"]
        for stat in ("collection_start", "collection_stop", "distribution_start", "distribution_stop"):
            self.assertIn(stat, posted)
        self.assertEqual(orchestrator.current_state, self.state.AMID_COLLECTION)


class FailoverTests(OrchestratorTestCase):
    '''
    The 12 hour failover: a run that never finishes should not block the next day's run.
    These only describe behaviour (what is sent, and the state), so they hold whether the
    failover is checked by wall-clock minute or by time elapsed since the kickoff.
    '''

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.failover_present = has_failover()

    def setUp(self):
        super().setUp()
        if not self.failover_present:
            self.skipTest("orchestrator.py has no failover (no attribute named like FAILOVER)")
        self.failover = FAILOVER_PERIOD

    def test_stuck_collection_is_reset_after_failover_period(self):
        orchestrator = self.make_orchestrator(start=KICKOFF)
        self.clock.at(KICKOFF + self.failover - 2 * MINUTE,
                      lambda: self.assertEqual(orchestrator.current_state, self.state.AMID_COLLECTION))
        self.run_main_loop_until(KICKOFF + self.failover + MINUTE)
        self.assertEqual(orchestrator.current_state, self.state.AWAITING)

    def test_stuck_collection_restarts_at_next_kickoff(self):
        self.make_orchestrator(start=KICKOFF)
        self.run_main_loop_until(KICKOFF + DAY)
        self.assertEqual(self.stomp.bodies(COLLECTION_REQUEST), [{"time": KICKOFF}, {"time": KICKOFF + DAY}])

    def test_stuck_distribution_restarts_at_next_kickoff(self):
        self.make_orchestrator(start=KICKOFF)
        self.clock.at(KICKOFF + 30 * MINUTE, self.collector_replies)
        self.run_main_loop_until(KICKOFF + DAY)
        self.assertEqual(self.stomp.bodies(COLLECTION_REQUEST), [{"time": KICKOFF}, {"time": KICKOFF + DAY}])
        self.assertEqual(len(self.stomp.bodies(DISTRIBUTION_REQUEST)), 1)

    def test_failover_works_when_kickoff_plus_failover_passes_midnight(self):
        late_kickoff = DAY_START + 20 * HOUR
        orchestrator = self.make_orchestrator(hour=20, minute=0, start=late_kickoff)
        self.clock.at(late_kickoff + self.failover - 2 * MINUTE,
                      lambda: self.assertEqual(orchestrator.current_state, self.state.AMID_COLLECTION))
        self.clock.at(late_kickoff + self.failover + 2 * MINUTE,
                      lambda: self.assertEqual(orchestrator.current_state, self.state.AWAITING))
        self.run_main_loop_until(late_kickoff + DAY)
        self.assertEqual(self.stomp.bodies(COLLECTION_REQUEST),
                         [{"time": late_kickoff}, {"time": late_kickoff + DAY}])

    def test_failover_forgets_partial_collector_replies(self):
        # One of two collectors replied before the run got stuck. The next run must still
        # wait for both of its own collectors before starting distribution.
        self.make_orchestrator(total_active_collectors=2, start=KICKOFF)
        self.clock.at(KICKOFF + 30 * MINUTE, self.collector_replies)
        self.clock.at(KICKOFF + DAY + 30 * MINUTE, self.collector_replies)
        self.run_main_loop_until(KICKOFF + DAY + 31 * MINUTE)
        self.assertEqual(len(self.stomp.bodies(COLLECTION_REQUEST)), 2)
        self.assertEqual(self.stomp.bodies(DISTRIBUTION_REQUEST), [])

    def test_reply_after_reset_is_ignored(self):
        # A collector from the abandoned run answers after the failover, before the next kickoff.
        # It must not start distribution, nor count towards the next run's collector replies.
        orchestrator = self.make_orchestrator(start=KICKOFF)
        late_reply = KICKOFF + self.failover + 30 * MINUTE

        def nothing_started():
            self.assertEqual(self.stomp.bodies(DISTRIBUTION_REQUEST), [])
            self.assertEqual(orchestrator.current_state, self.state.AWAITING)

        self.clock.at(late_reply, self.collector_replies)
        self.clock.at(late_reply + MINUTE, nothing_started)
        self.clock.at(KICKOFF + DAY + 30 * MINUTE, self.collector_replies)
        self.run_main_loop_until(KICKOFF + DAY + 31 * MINUTE)
        self.assertEqual(self.stomp.bodies(DISTRIBUTION_REQUEST), [{"time": KICKOFF + DAY + 30 * MINUTE}])

    def test_healthy_run_is_left_alone(self):
        orchestrator = self.make_orchestrator(start=KICKOFF)
        self.clock.at(KICKOFF + 30 * MINUTE, self.collector_replies)
        self.clock.at(KICKOFF + 60 * MINUTE, self.distributor_replies)
        self.run_main_loop_until(KICKOFF + self.failover + 5 * MINUTE)
        self.assertEqual(len(self.stomp.bodies(COLLECTION_REQUEST)), 1)
        self.assertEqual(len(self.stomp.bodies(DISTRIBUTION_REQUEST)), 1)
        self.assertEqual(self.post.call_count, 1)
        self.assertEqual(orchestrator.current_state, self.state.AWAITING)


if __name__ == "__main__":
    unittest.main()
