# An end-to-end test of Distributor.conduct_distribution with no MariaDB, STOMP broker, Gemini or email account.
# sammatime22, 2026
#
# MariaDB is replaced by an in-memory SQLite database that runs the Distributor's real SQL,
# STOMP and yagmail are replaced by recorders (no email is ever sent), and Gemini gives a
# canned answer unless STOCKRATE_GEMINI_KEY is set. Each test writes to its own folder:
#
#   test-output/<test name>/gemini_<n>.txt   the question asked of Gemini and its answer
#   test-output/<test name>/email_<n>.txt    who the email would go to, subject, body and attachments
#   test-output/<test name>/report.csv       the CSV attachment the Distributor wrote
#   test-output/<test name>/distributor.log  the Distributor's own log
#   test-output/<test name>/stockrate.db     the SQLite database after the run (open it with `sqlite3 stockrate.db`)
#
# Setup on iSH (Alpine):
#   apk add python3 py3-pytest py3-requests py3-yaml
#
# Run from the Distributor directory:
#   python3 -m pytest -s test_distributor.py
#
# Optional environment variables:
#   STOCKRATE_GEMINI_KEY    ask the real Gemini (via its REST API) instead of using canned answers
#   STOCKRATE_GEMINI_MODEL  model to ask when STOCKRATE_GEMINI_KEY is set (default: the one distributor.py uses)
#   STOCKRATE_OUT           output directory (default: ./test-output)
import asyncio
import datetime
import importlib
import json
import logging
import os
import re
import sqlite3
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))

GEMINI_KEY = os.environ.get("STOCKRATE_GEMINI_KEY")
GEMINI_MODEL = os.environ.get("STOCKRATE_GEMINI_MODEL")
OUT_DIR = os.path.abspath(os.environ.get("STOCKRATE_OUT", os.path.join(HERE, "test-output")))

CANNED_AI_ANSWER = "Canned AI answer (set STOCKRATE_GEMINI_KEY to ask Gemini for real)."
AI_ERROR_ANSWER = "An error occurred in querying the AI agent."
CSV_HEADER = "Stock Name,Stock Acronym,Yesterday's Price,Today's Price,Total Difference,Percent Difference"

SCHEMA = """
CREATE TABLE STOCK (
    stock_id    INTEGER PRIMARY KEY,
    stock_name  TEXT NOT NULL,
    acronym     TEXT
);
CREATE TABLE CLEANED_DATA (
    data_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id        INTEGER NOT NULL,
    pull_id         INTEGER NOT NULL,
    pull_date       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_id       INTEGER NOT NULL,
    price           REAL NOT NULL,
    rate_of_change  REAL NOT NULL
);
CREATE TABLE USER (
    email  TEXT PRIMARY KEY
);
"""

STOCKS = [
    (1, "Alphabet Inc Class A", "GOOGL:NASDAQ"),
    (2, "Apple Inc", "AAPL:NASDAQ"),
    (3, "Microsoft Corp", "MSFT:NASDAQ"),
]
USERS = ["first@example.com", "second@example.com"]

DB_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

class FakeMariaDBCursor:
    '''
    Runs the Distributor's MariaDB SQL against SQLite.
    '''

    DOUBLE_QUOTED_LITERAL = re.compile(r'"([^"]*)"')

    def __init__(self, sqlite_connection):
        self.cursor = sqlite_connection.cursor()

    def execute(self, sql):
        # MariaDB accepts "..." string literals, SQLite wants '...'
        self.cursor.execute(self.DOUBLE_QUOTED_LITERAL.sub(lambda m: "'" + m.group(1).replace("'", "''") + "'", sql))

    def fetchall(self):
        return self.cursor.fetchall()


class FakeMariaDBConnection:
    def __init__(self, sqlite_connection):
        self.sqlite_connection = sqlite_connection
        self.autocommit = False

    def cursor(self):
        return FakeMariaDBCursor(self.sqlite_connection)


class FakeStompConnection:
    def __init__(self):
        self.sent = []

    def send(self, destination, body):
        self.sent.append((destination, body))


class FakeGenAI:
    '''
    Stands in for google.generativeai. Answers are canned, or come from the Gemini REST API
    when STOCKRATE_GEMINI_KEY is set; fail=True makes every question raise.
    '''

    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.api_key = None
        self.fail = False
        self.questions = []

    def configure(self, api_key=None):
        self.api_key = api_key

    def GenerativeModel(self, model_name):
        fake = self

        class Model:
            def generate_content(self, query):
                return fake.answer(model_name, query)

        return Model()

    def answer(self, model_name, query):
        self.questions.append(query)
        number = len(self.questions)
        try:
            if self.fail:
                raise RuntimeError("Gemini made to fail by the test")
            text = self.ask_gemini(GEMINI_MODEL or model_name, query) if GEMINI_KEY else CANNED_AI_ANSWER
        except Exception as e:
            text = "<raised {!r}>".format(e)
            raise
        finally:
            with open(os.path.join(self.out_dir, "gemini_{}.txt".format(number)), "w") as out:
                out.write("=== question (model {}) ===\n{}\n\n=== answer ===\n{}\n".format(GEMINI_MODEL or model_name, query, text))
        return types.SimpleNamespace(text=text)

    @staticmethod
    def ask_gemini(model_name, query):
        import requests
        resp = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent".format(model_name),
            headers={"x-goog-api-key": GEMINI_KEY},
            json={"contents": [{"parts": [{"text": query}]}]},
            timeout=60)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


class FakeYagmail:
    '''
    Stands in for yagmail, recording each email (and its attachments' contents) instead of sending it.
    '''

    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.logins = []
        self.sent = []

    def SMTP(self, user, oauth2_file=None):
        fake = self
        fake.logins.append((user, oauth2_file))

        class SMTP:
            def send(self, to=None, subject=None, contents=None, attachments=None):
                attached = {}
                for path in attachments or []:
                    with open(path) as attachment:
                        attached[path] = attachment.read()
                email = {"from": user, "to": to, "subject": subject, "contents": contents, "attachments": attached}
                fake.sent.append(email)
                with open(os.path.join(fake.out_dir, "email_{}.txt".format(len(fake.sent))), "w") as out:
                    out.write("From: {}\nTo: {}\nSubject: {}\n\n{}\n".format(user, ", ".join(to or []), subject, contents))
                    for path, content in attached.items():
                        out.write("\n=== attachment {} ===\n{}".format(path, content))

        return SMTP()


@pytest.fixture
def harness(monkeypatch, request):
    '''
    Imports distributor.py with mariadb, stomp, factory, google.generativeai and yagmail stubbed out,
    inside this test's output directory so distributor.log lands there, and returns a Distributor
    wired to a fresh SQLite database.
    '''
    out_dir = os.path.join(OUT_DIR, request.node.name)
    os.makedirs(out_dir, exist_ok=True)
    for name in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, name))
    monkeypatch.chdir(out_dir)
    monkeypatch.syspath_prepend(HERE)

    sqlite_connection = sqlite3.connect(os.path.join(out_dir, "stockrate.db"), isolation_level=None, check_same_thread=False)
    sqlite_connection.executescript(SCHEMA)
    sqlite_connection.executemany("INSERT INTO STOCK (stock_id, stock_name, acronym) VALUES (?, ?, ?)", STOCKS)
    sqlite_connection.executemany("INSERT INTO USER (email) VALUES (?)", [(user,) for user in USERS])
    sqlite_connection.create_function("NOW", 0, lambda: datetime.datetime.now(datetime.timezone.utc).strftime(DB_TIME_FORMAT))
    sqlite_connection.create_function("SUBDATE", 2, lambda date, days: (
        datetime.datetime.strptime(date, DB_TIME_FORMAT) - datetime.timedelta(days=days)).strftime(DB_TIME_FORMAT))

    fake_mariadb = types.ModuleType("mariadb")
    fake_mariadb.connect = lambda **kwargs: FakeMariaDBConnection(sqlite_connection)
    fake_stomp = types.ModuleType("stomp")
    fake_stomp.ConnectionListener = object
    fake_factory = types.ModuleType("factory")
    fake_factory.stomp_factory = lambda *args, **kwargs: None
    genai = FakeGenAI(out_dir)
    fake_genai = types.ModuleType("google.generativeai")
    fake_genai.configure = genai.configure
    fake_genai.GenerativeModel = genai.GenerativeModel
    fake_google = types.ModuleType("google")
    fake_google.generativeai = fake_genai
    yag = FakeYagmail(out_dir)
    fake_yagmail = types.ModuleType("yagmail")
    fake_yagmail.SMTP = yag.SMTP
    for name, module in [("mariadb", fake_mariadb), ("stomp", fake_stomp), ("factory", fake_factory),
                         ("google", fake_google), ("google.generativeai", fake_genai), ("yagmail", fake_yagmail)]:
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, "distributor", raising=False)

    module = importlib.import_module("distributor")
    config = {
        "maria_db_config": {"user": "test", "password": "test", "host": "localhost", "port": 3306, "database": "stockrate"},
        "google_gemini_config": {"my_key": "test-gemini-key"},
        "email_config": {"attachment": os.path.join(out_dir, "report.csv"), "email_address": "stockrate@example.com",
                         "oauth2_file": "oauth2.json"},
    }
    distributor = module.Distributor(config)
    stomp_connection = FakeStompConnection()
    distributor.set_stomp_connection(stomp_connection)

    harness = types.SimpleNamespace(distributor=distributor, db=sqlite_connection, genai=genai, yag=yag,
                                    stomp=stomp_connection, out_dir=out_dir, config=config)
    yield harness

    logging.getLogger().removeHandler(module.Distributor.handler)
    module.Distributor.handler.close()
    sqlite_connection.close()


def add_pulls(db, pulls):
    '''
    Inserts CLEANED_DATA rows; pulls is a list of (pull_id, stock_id, price).
    '''
    db.executemany("INSERT INTO CLEANED_DATA (stock_id, pull_id, pull_date, source_id, price, rate_of_change) VALUES (?, ?, ?, 1, ?, 0)",
                   [(stock_id, pull_id, pull_date, price) for (pull_id, stock_id, pull_date, price) in pulls])


def run_distribution(harness):
    asyncio.run(harness.distributor.conduct_distribution())
    email = harness.yag.sent[-1] if harness.yag.sent else None
    print("\n[{}]".format(os.path.basename(harness.out_dir)))
    for number, question in enumerate(harness.genai.questions, start=1):
        print("Gemini question {}:\n{}".format(number, question))
    if email:
        print("Email to {} | {}\n{}".format(email["to"], email["subject"], email["contents"]))
    print("STOMP messages: {}\nOutput written to {}".format(harness.stomp.sent, harness.out_dir))
    return email


def assert_finished(harness):
    assert harness.stomp.sent[-1][0] == "/topic/distribution-reply"
    assert json.loads(harness.stomp.sent[-1][1]).get("distribution_stop")
    assert harness.distributor.active is False
    assert harness.yag.logins == [("stockrate@example.com", "oauth2.json")]
    assert harness.genai.api_key == "test-gemini-key"


def get_time(delta):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=delta)).strftime("%Y-%m-%d %H:%M:%S")


def test_distribution_sends_report(harness):
    # Yesterday's pull (1-3) then today's pull (4-6)
    add_pulls(harness.db, [(1, 1, get_time(1), 100.0), (2, 2, get_time(1), 200.0), (3, 3, get_time(1), 50.0),
                           (4, 1, get_time(0), 110.0), (5, 2, get_time(0), 150.0), (6, 3, get_time(0), 50.0)])

    email = run_distribution(harness)

    expected_rows = {
        "Alphabet Inc Class A,GOOGL:NASDAQ,100.0,110.0,10.0,0.1",
        "Apple Inc,AAPL:NASDAQ,200.0,150.0,-50.0,-0.25",
        "Microsoft Corp,MSFT:NASDAQ,50.0,50.0,0.0,0.0",
    }
    with open(harness.config["email_config"]["attachment"]) as report:
        csv_lines = report.read().splitlines()
    assert csv_lines[0] == CSV_HEADER
    assert set(csv_lines[1:]) == expected_rows

    assert len(harness.genai.questions) == 1
    assert "which three stocks had the biggest change" in harness.genai.questions[0]
    assert all(row in harness.genai.questions[0] for row in expected_rows)

    assert len(harness.yag.sent) == 1
    assert email["to"] == USERS
    assert email["subject"].startswith("Todays Stock Data ")
    assert email["contents"] and email["contents"] != AI_ERROR_ANSWER
    if not GEMINI_KEY:
        assert email["contents"] == CANNED_AI_ANSWER
    assert list(email["attachments"].values()) == ["\n".join(csv_lines) + "\n"]
    assert_finished(harness)


def test_distribution_sends_apology_when_data_is_incomplete(harness):
    # Only one pull for GOOGL, so there is no yesterday's price to compare against
    add_pulls(harness.db, [(1, 1, get_time(0),100.0)])

    email = run_distribution(harness)

    assert len(harness.genai.questions) == 1
    assert "apology statement" in harness.genai.questions[0]
    assert len(harness.yag.sent) == 1
    assert email["to"] == USERS
    assert email["subject"].startswith("StockRate Pipeline Issue ")
    assert email["attachments"] == {}
    assert_finished(harness)


def test_distribution_still_emails_when_ai_fails(harness):
    add_pulls(harness.db, [(1, 1, get_time(0), 100.0), (2, 1, get_time(0), 110.0)])
    harness.genai.fail = True

    email = run_distribution(harness)

    assert email["subject"].startswith("Todays Stock Data ")
    assert email["contents"] == AI_ERROR_ANSWER
    assert list(email["attachments"].values())[0].startswith(CSV_HEADER)
    assert_finished(harness)
