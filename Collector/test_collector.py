# An end-to-end test of Collector.conduct_collection with no MariaDB or STOMP broker.
# sammatime22, 2026
#
# MariaDB is replaced by an in-memory SQLite database that runs the Collector's real SQL,
# and STOMP is replaced by a recorder. The HTTP request is made for real (or replayed from
# a saved file), and everything about it is written to an output directory:
#
#   exchange_<n>.txt   request URL and headers sent, every redirect hop, final status and response headers
#   response_<n>.html  the body that came back
#   results.txt        what was stored in COLLECTED_DATA / CLEANED_DATA, plus STOMP messages sent
#   collector.log      the Collector's own log
#   stockrate.db       the SQLite database after the run (open it with `sqlite3 stockrate.db`)
#
# Setup on iSH (Alpine):
#   apk add python3 py3-pytest py3-requests py3-beautifulsoup4 py3-lxml py3-yaml
#
# Run from the Collector directory:
#   python3 -m pytest -s test_collector.py
#
# Optional environment variables:
#   STOCKRATE_SOURCE       source_location          (default: www.google.com)
#   STOCKRATE_EXTENSION    extension                (default: finance/quote)
#   STOCKRATE_TICKERS      comma separated terms    (default: GOOGL:NASDAQ)
#   STOCKRATE_USER_AGENT   override the User-Agent the Collector sends
#   STOCKRATE_REPLAY_FILE  serve this saved HTML instead of making a network request
#   STOCKRATE_OUT          output directory         (default: ./test-output)
import asyncio
import datetime
import importlib
import json
import os
import re
import sqlite3
import sys
import types

import pytest
import requests

HERE = os.path.dirname(os.path.abspath(__file__))

SOURCE = os.environ.get("STOCKRATE_SOURCE", "www.google.com")
EXTENSION = os.environ.get("STOCKRATE_EXTENSION", "finance/quote")
TICKERS = [t.strip() for t in os.environ.get("STOCKRATE_TICKERS", "GOOGL:NASDAQ").split(",") if t.strip()]
USER_AGENT = os.environ.get("STOCKRATE_USER_AGENT")
REPLAY_FILE = os.environ.get("STOCKRATE_REPLAY_FILE")
OUT_DIR = os.path.abspath(os.environ.get("STOCKRATE_OUT", os.path.join(HERE, "test-output")))

SCHEMA = """
CREATE TABLE STOCK (
    stock_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    acronym   TEXT
);
CREATE TABLE DATA_SOURCES (
    source_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    source_location  TEXT NOT NULL,
    extension        TEXT,
    search_terms     TEXT,
    notes            TEXT
);
CREATE TABLE COLLECTED_DATA (
    pull_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    pull_date   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_id   INTEGER NOT NULL,
    stock_id    INTEGER NOT NULL,
    dirty_data  TEXT
);
CREATE TABLE CLEANED_DATA (
    data_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id        INTEGER NOT NULL,
    pull_id         INTEGER NOT NULL,
    source_id       INTEGER NOT NULL,
    price           REAL NOT NULL,
    rate_of_change  REAL NOT NULL
);
"""

DB_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class FakeMariaDBCursor:
    '''
    Runs the Collector's MariaDB SQL against SQLite, translating the few MariaDB-only bits.
    '''

    DOUBLE_QUOTED_LITERAL = re.compile(r'"([^"]*)"')

    def __init__(self, sqlite_connection):
        self.cursor = sqlite_connection.cursor()
        self.executed = []

    def execute(self, sql):
        self.executed.append(sql)
        # MariaDB accepts "..." string literals, SQLite wants '...'
        sql = self.DOUBLE_QUOTED_LITERAL.sub(lambda m: "'" + m.group(1).replace("'", "''") + "'", sql)
        self.cursor.execute(sql)

    def fetchall(self):
        return self.cursor.fetchall()


class FakeMariaDBConnection:
    def __init__(self, sqlite_connection):
        self.sqlite_connection = sqlite_connection
        self.autocommit = False
        self.cursors = []

    def cursor(self):
        cursor = FakeMariaDBCursor(self.sqlite_connection)
        self.cursors.append(cursor)
        return cursor


class FakeStompConnection:
    def __init__(self):
        self.sent = []

    def send(self, destination, body):
        self.sent.append((destination, body))


def make_database():
    db_path = os.path.join(OUT_DIR, "stockrate.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    connection = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    connection.create_function("NOW", 0, lambda: datetime.datetime.now(datetime.timezone.utc).strftime(DB_TIME_FORMAT))
    connection.create_function("SUBDATE", 2, lambda date, days: (
        datetime.datetime.strptime(date, DB_TIME_FORMAT) - datetime.timedelta(days=days)).strftime(DB_TIME_FORMAT))
    connection.executescript(SCHEMA)
    connection.execute("INSERT INTO DATA_SOURCES (source_location, extension, search_terms) VALUES (?, ?, ?)",
                       (SOURCE, EXTENSION, ",".join(TICKERS)))
    for ticker in TICKERS:
        connection.execute("INSERT INTO STOCK (acronym) VALUES (?)", (ticker,))
    return connection


@pytest.fixture
def collector_module(monkeypatch):
    '''
    Imports collector.py with mariadb, stomp and factory stubbed out, inside the output directory
    so collector.log lands there.
    '''
    os.makedirs(OUT_DIR, exist_ok=True)
    monkeypatch.chdir(OUT_DIR)
    monkeypatch.syspath_prepend(HERE)

    fake_mariadb = types.ModuleType("mariadb")
    fake_mariadb.connect = None  # set per test
    fake_stomp = types.ModuleType("stomp")
    fake_stomp.ConnectionListener = object
    fake_factory = types.ModuleType("factory")
    fake_factory.stomp_factory = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "mariadb", fake_mariadb)
    monkeypatch.setitem(sys.modules, "stomp", fake_stomp)
    monkeypatch.setitem(sys.modules, "factory", fake_factory)
    monkeypatch.delitem(sys.modules, "collector", raising=False)

    module = importlib.import_module("collector")
    yield module
    module.Collector.handler.close()


def describe_exchange(resp):
    lines = []
    for number, hop in enumerate(list(resp.history) + [resp]):
        lines.append("=== hop {} ===".format(number))
        lines.append("REQUEST  {} {}".format(hop.request.method, hop.request.url))
        for key, value in hop.request.headers.items():
            lines.append("  > {}: {}".format(key, value))
        lines.append("RESPONSE {} {} ({} bytes)".format(hop.status_code, hop.reason, len(hop.content)))
        for key, value in hop.headers.items():
            lines.append("  < {}: {}".format(key, value))
        lines.append("")
    lines.append("FINAL URL: {}".format(resp.url))
    return "\n".join(lines)


def replayed_response(url, headers):
    resp = requests.Response()
    resp.status_code = 200
    resp.reason = "OK (replayed from {})".format(REPLAY_FILE)
    resp.url = url
    with open(REPLAY_FILE, "rb") as replay:
        resp._content = replay.read()
    resp.request = requests.Request("GET", url, headers=headers).prepare()
    return resp


def test_conduct_collection(collector_module, monkeypatch):
    sqlite_connection = make_database()
    fake_connection = FakeMariaDBConnection(sqlite_connection)
    collector_module.mariadb.connect = lambda **kwargs: fake_connection

    exchanges = []
    real_get = requests.get

    def recording_get(url, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        if USER_AGENT:
            headers["User-Agent"] = USER_AGENT
            kwargs["headers"] = headers
        resp = replayed_response(url, headers) if REPLAY_FILE else real_get(url, timeout=30, **kwargs)
        exchanges.append(resp)
        number = len(exchanges)
        with open(os.path.join(OUT_DIR, "exchange_{}.txt".format(number)), "w") as out:
            out.write(describe_exchange(resp))
        with open(os.path.join(OUT_DIR, "response_{}.html".format(number)), "wb") as out:
            out.write(resp.content)
        return resp

    monkeypatch.setattr(collector_module.requests, "get", recording_get)

    config = {"maria_db_config": {"user": "test", "password": "test", "host": "localhost", "port": 3306, "database": "stockrate"}}
    collector = collector_module.Collector(config)
    collector.AWAIT_TIME = 0
    stomp_connection = FakeStompConnection()
    collector.set_stomp_connection(stomp_connection)

    asyncio.run(collector.conduct_collection())

    collected = sqlite_connection.execute(
        "SELECT pull_id, source_id, stock_id, pull_date, length(dirty_data) FROM COLLECTED_DATA").fetchall()
    cleaned = sqlite_connection.execute(
        "SELECT data_id, stock_id, pull_id, source_id, price, rate_of_change FROM CLEANED_DATA").fetchall()

    report = ["Source: https://{}/{}/<ticker>   tickers: {}".format(SOURCE, EXTENSION, TICKERS), ""]
    for number, resp in enumerate(exchanges, start=1):
        report.append("Request {}: {} -> {} {} (final url {}, {} bytes, redirects: {})".format(
            number, resp.history[0].url if resp.history else resp.url, resp.status_code, resp.reason,
            resp.url, len(resp.content), [hop.headers.get("Location") for hop in resp.history]))
    report.append("")
    report.append("COLLECTED_DATA (pull_id, source_id, stock_id, pull_date, dirty_data length):")
    report.extend("  {}".format(row) for row in collected or ["<none>"])
    report.append("CLEANED_DATA (data_id, stock_id, pull_id, source_id, price, rate_of_change):")
    report.extend("  {}".format(row) for row in cleaned or ["<none>"])
    report.append("Learned tag classes: value={!r} rate_of_change={!r}".format(
        collector.value_tag_class, collector.rate_of_change_class))
    report.append("STOMP messages: {}".format(stomp_connection.sent))
    report.append("")
    report.append("Output written to {}".format(OUT_DIR))
    report_text = "\n".join(report)
    with open(os.path.join(OUT_DIR, "results.txt"), "w") as out:
        out.write(report_text + "\n")
    print("\n" + report_text)

    assert len(exchanges) == len(TICKERS), "expected one request per ticker"
    assert stomp_connection.sent and json.loads(stomp_connection.sent[-1][1]).get("collection_stop"), \
        "collector should report collection_stop over STOMP"
    assert collected, "nothing was stored in COLLECTED_DATA; see exchange_*.txt and response_*.html"
    assert cleaned, "nothing was cleaned; see collector.log"
    assert all(price > 0 for (_, _, _, _, price, _) in cleaned), "cleaning did not find a price; see collector.log"
