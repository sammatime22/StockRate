# An end-to-end test of Distributor.conduct_distribution with no MariaDB, STOMP broker, Gemini or email account.
# sammatime22, 2026
#
# MariaDB is replaced by an in-memory SQLite database that runs the Distributor's real SQL,
# STOMP and yagmail are replaced by recorders (no email is ever sent), and Gemini gives a
# canned answer unless STOCKRATE_GEMINI_KEY is set. Each test writes to its own folder:
#
#   test-output/<test name>/gemini_<n>.txt   the question asked of Gemini and its answer
#   test-output/<test name>/email_<n>.txt    who the email would go to, subject, body and attachments
#   test-output/<test name>/email_<n>.html   the email body, to preview in a browser (try your phone's screen size)
#   test-output/<test name>/report.xlsx      the xlsx attachment the Distributor wrote (open it in Excel/Numbers)
#   test-output/<test name>/distributor.log  the Distributor's own log
#   test-output/<test name>/stockrate.db     the SQLite database after the run (open it with `sqlite3 stockrate.db`)
#
# Setup on iSH (Alpine):
#   apk add python3 py3-pytest py3-requests py3-yaml py3-openpyxl
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
import time
import types

import openpyxl
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))

GEMINI_KEY = os.environ.get("STOCKRATE_GEMINI_KEY")
GEMINI_MODEL = os.environ.get("STOCKRATE_GEMINI_MODEL")
OUT_DIR = os.path.abspath(os.environ.get("STOCKRATE_OUT", os.path.join(HERE, "test-output")))

CANNED_AI_ANSWER = "Canned AI answer (set STOCKRATE_GEMINI_KEY to ask Gemini for real)."
# A canned Gemini answer for the 20 test stocks. The articles and links are made up (example.com), not real news.
CANNED_INSIGHT = """Today's biggest movers (canned test insight - these articles are made up)

Top gainers
- Uber Technologies Inc (UBER:NYSE) +20.00%: [Product / orders] Shares jumped after Uber announced its robotaxi service is expanding to ten more cities.
  Article: "Uber Takes Robotaxis Nationwide" - https://news.example.com/2026/10/uber-robotaxi-expansion
- NVIDIA Corp (NVDA:NASDAQ) +15.00%: [Product / orders] A new data center chip order from several cloud providers lifted the stock.
  Article: "Cloud Giants Line Up for NVIDIA's Next Chip" - https://news.example.com/2026/10/nvidia-data-center-orders
- Alphabet Inc Class A (GOOGL:NASDAQ) +10.00%: [Earnings / results] Strong cloud and ad revenue in its quarterly report beat expectations.
  Article: "Alphabet Earnings Beat on Cloud Growth" - https://news.example.com/2026/10/alphabet-earnings-beat

Top losers
- Apple Inc (AAPL:NASDAQ) -25.00%: [Product / orders] Reports of weaker phone demand and a delayed product launch weighed on the stock.
  Article: "Apple Delays Launch Amid Soft Demand" - https://news.example.com/2026/10/apple-launch-delay
- Tesla Inc (TSLA:NASDAQ) -20.00%: [Earnings / results] Quarterly deliveries came in well below analyst forecasts.
  Article: "Tesla Deliveries Miss Estimates" - https://news.example.com/2026/10/tesla-deliveries-miss
- Intel Corp (INTC:NASDAQ) -10.00%: [Guidance / outlook] Intel cut its full-year outlook, citing slower PC sales.
  Article: "Intel Lowers Guidance on PC Slump" - https://news.example.com/2026/10/intel-guidance-cut
"""
AI_ERROR_ANSWER = "An error occurred in querying the AI agent."
XLSX_HEADER = ("Stock Name", "Ticker", "Market", "Yesterday's Price", "Today's Price", "Total Difference", "Percent Difference")

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

# (stock_id, stock_name, acronym, yesterday's price, today's price); every rate of change is different
PRICED_STOCKS = [
    (1, "Alphabet Inc Class A", "GOOGL:NASDAQ", 100.0, 110.0),      # +10%
    (2, "Apple Inc", "AAPL:NASDAQ", 200.0, 150.0),                  # -25%
    (3, "Microsoft Corp", "MSFT:NASDAQ", 50.0, 50.0),               # 0%
    (4, "Amazon.com Inc", "AMZN:NASDAQ", 180.0, 189.0),             # +5%
    (5, "NVIDIA Corp", "NVDA:NASDAQ", 120.0, 138.0),                # +15%
    (6, "Meta Platforms Inc", "META:NASDAQ", 500.0, 490.0),         # -2%
    (7, "Tesla Inc", "TSLA:NASDAQ", 250.0, 200.0),                  # -20%
    (8, "Netflix Inc", "NFLX:NASDAQ", 600.0, 612.0),                # +2%
    (9, "Advanced Micro Devices Inc", "AMD:NASDAQ", 160.0, 164.0),  # +2.5%
    (10, "Intel Corp", "INTC:NASDAQ", 30.0, 27.0),                  # -10%
    (11, "International Business Machines Corp", "IBM:NYSE", 200.0, 207.0),  # +3.5%
    (12, "Oracle Corp", "ORCL:NYSE", 140.0, 133.0),                 # -5%
    (13, "Salesforce Inc", "CRM:NYSE", 300.0, 324.0),               # +8%
    (14, "Adobe Inc", "ADBE:NASDAQ", 500.0, 470.0),                 # -6%
    (15, "PayPal Holdings Inc", "PYPL:NASDAQ", 80.0, 79.0),         # -1.25%
    (16, "Uber Technologies Inc", "UBER:NYSE", 70.0, 84.0),         # +20%
    (17, "Walt Disney Co", "DIS:NYSE", 100.0, 97.0),                # -3%
    (18, "Coca-Cola Co", "KO:NYSE", 200.0, 202.0),                  # +1%
    (19, "JPMorgan Chase & Co", "JPM:NYSE", 150.0, 138.0),          # -8%
    (20, "Walmart Inc", "WMT:NYSE", 100.0, 104.0),                  # +4%
]
STOCKS = [(stock_id, name, acronym) for (stock_id, name, acronym, _, _) in PRICED_STOCKS]
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
            def generate_content(self, query, request_options=None):
                return fake.answer(model_name, query)

        return Model()

    def answer(self, model_name, query):
        self.questions.append(query)
        number = len(self.questions)
        try:
            if self.fail:
                raise RuntimeError("Gemini made to fail by the test")
            text = self.ask_gemini(GEMINI_MODEL or model_name, query) if GEMINI_KEY else self.canned_answer(query)
        except Exception as e:
            text = "<raised {!r}>".format(e)
            raise
        finally:
            with open(os.path.join(self.out_dir, "gemini_{}.txt".format(number)), "w") as out:
                out.write("=== question (model {}) ===\n{}\n\n=== answer ===\n{}\n".format(GEMINI_MODEL or model_name, query, text))
        return types.SimpleNamespace(text=text)

    @staticmethod
    def canned_answer(query):
        # the analyzer's insight question gets the canned insight, anything else (like the apology) the plain answer
        return CANNED_INSIGHT if "top three gainers" in query else CANNED_AI_ANSWER

    @staticmethod
    def ask_gemini(model_name, query):
        import requests
        # accept "gemini-2.5-flash" or "models/gemini-2.5-flash", and ignore stray spaces around the key
        model_name = model_name[len("models/"):] if model_name.startswith("models/") else model_name
        resp = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent".format(model_name),
            headers={"x-goog-api-key": GEMINI_KEY.strip()},
            json={"contents": [{"parts": [{"text": query}]}]},
            timeout=600)  # same as analyzer.AI_TIMEOUT_SECONDS
        if not resp.ok:
            # show Google's own explanation (e.g. which model or key was rejected), not just the status code
            try:
                reason = resp.json()["error"]["message"]
            except Exception:
                reason = resp.text[:500]
            raise RuntimeError("Gemini returned {} for model {}: {}".format(resp.status_code, model_name, reason))
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


class FakeYagmail:
    '''
    Stands in for yagmail, recording each email (and its xlsx attachments' sheets) instead of sending it.
    Each attachment is recorded as {sheet name: [row tuples]}.
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
                    workbook = openpyxl.load_workbook(path)
                    attached[path] = {sheet.title: list(sheet.iter_rows(values_only=True)) for sheet in workbook}
                email = {"from": user, "to": to, "subject": subject, "contents": contents, "attachments": attached}
                fake.sent.append(email)
                with open(os.path.join(fake.out_dir, "email_{}.html".format(len(fake.sent))), "w") as out:
                    out.write('<meta charset="utf-8"><meta name="viewport" content="width=device-width">{}'.format(contents))
                with open(os.path.join(fake.out_dir, "email_{}.txt".format(len(fake.sent))), "w") as out:
                    out.write("From: {}\nTo: {}\nSubject: {}\n\n{}\n".format(user, ", ".join(to or []), subject, contents))
                    for path, sheets in attached.items():
                        out.write("\n=== attachment {} ===\n".format(path))
                        for title, rows in sheets.items():
                            out.write("--- sheet {} ---\n{}\n".format(title, "\n".join(str(row) for row in rows)))

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
    # re-import analyzer too, so it picks up this test's fake Gemini
    monkeypatch.delitem(sys.modules, "distributor", raising=False)
    monkeypatch.delitem(sys.modules, "analyzer", raising=False)

    module = importlib.import_module("distributor")
    # record the analyzer's waits between AI retries; only really wait when asking the real Gemini
    waits = []
    def record_wait(seconds):
        waits.append(seconds)
        if GEMINI_KEY and not genai.fail:
            time.sleep(seconds)
    monkeypatch.setattr(sys.modules["analyzer"], "sleep", record_wait)
    config = {
        "maria_db_config": {"user": "test", "password": "test", "host": "localhost", "port": 3306, "database": "stockrate"},
        "google_gemini_config": {"my_key": "test-gemini-key"},
        "email_config": {"attachment": os.path.join(out_dir, "report.xlsx"), "email_address": "stockrate@example.com",
                         "oauth2_file": "oauth2.json"},
    }
    distributor = module.Distributor(config)
    stomp_connection = FakeStompConnection()
    distributor.set_stomp_connection(stomp_connection)

    harness = types.SimpleNamespace(distributor=distributor, db=sqlite_connection, genai=genai, yag=yag,
                                    stomp=stomp_connection, out_dir=out_dir, config=config, waits=waits)
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
    # Yesterday's pull (1-20) then today's pull (21-40)
    count = len(PRICED_STOCKS)
    add_pulls(harness.db, [(stock_id, stock_id, get_time(1), yesterday) for (stock_id, _, _, yesterday, _) in PRICED_STOCKS] +
                          [(count + stock_id, stock_id, get_time(0), today) for (stock_id, _, _, _, today) in PRICED_STOCKS])

    email = run_distribution(harness)

    # Alphabetical by market, then by name
    expected_rows = [
        XLSX_HEADER,
        ("Adobe Inc", "ADBE", "NASDAQ", 500.0, 470.0, -30.0, -0.06),
        ("Advanced Micro Devices Inc", "AMD", "NASDAQ", 160.0, 164.0, 4.0, 0.025),
        ("Alphabet Inc Class A", "GOOGL", "NASDAQ", 100.0, 110.0, 10.0, 0.1),
        ("Amazon.com Inc", "AMZN", "NASDAQ", 180.0, 189.0, 9.0, 0.05),
        ("Apple Inc", "AAPL", "NASDAQ", 200.0, 150.0, -50.0, -0.25),
        ("Intel Corp", "INTC", "NASDAQ", 30.0, 27.0, -3.0, -0.1),
        ("Meta Platforms Inc", "META", "NASDAQ", 500.0, 490.0, -10.0, -0.02),
        ("Microsoft Corp", "MSFT", "NASDAQ", 50.0, 50.0, 0.0, 0.0),
        ("Netflix Inc", "NFLX", "NASDAQ", 600.0, 612.0, 12.0, 0.02),
        ("NVIDIA Corp", "NVDA", "NASDAQ", 120.0, 138.0, 18.0, 0.15),
        ("PayPal Holdings Inc", "PYPL", "NASDAQ", 80.0, 79.0, -1.0, -0.0125),
        ("Tesla Inc", "TSLA", "NASDAQ", 250.0, 200.0, -50.0, -0.2),
        ("Coca-Cola Co", "KO", "NYSE", 200.0, 202.0, 2.0, 0.01),
        ("International Business Machines Corp", "IBM", "NYSE", 200.0, 207.0, 7.0, 0.035),
        ("JPMorgan Chase & Co", "JPM", "NYSE", 150.0, 138.0, -12.0, -0.08),
        ("Oracle Corp", "ORCL", "NYSE", 140.0, 133.0, -7.0, -0.05),
        ("Salesforce Inc", "CRM", "NYSE", 300.0, 324.0, 24.0, 0.08),
        ("Uber Technologies Inc", "UBER", "NYSE", 70.0, 84.0, 14.0, 0.2),
        ("Walmart Inc", "WMT", "NYSE", 100.0, 104.0, 4.0, 0.04),
        ("Walt Disney Co", "DIS", "NYSE", 100.0, 97.0, -3.0, -0.03),
    ]
    workbook = openpyxl.load_workbook(harness.config["email_config"]["attachment"])
    assert workbook.sheetnames == ["Dashboard", "Stock Data"]
    assert list(workbook["Stock Data"].iter_rows(values_only=True))[:len(expected_rows)] == expected_rows
    # gains are shaded green and losses red; no change is a plain black 0
    data_sheet = workbook["Stock Data"]
    uber, microsoft, apple = data_sheet["G19"], data_sheet["G9"], data_sheet["G6"]
    assert uber.fill.fill_type == "solid" and uber.fill.start_color.rgb[-6:] == "469358"
    assert apple.fill.fill_type == "solid" and apple.fill.start_color.rgb[-6:] == "B3261E"
    assert microsoft.fill.fill_type is None and microsoft.font.color.rgb[-6:] == "000000"

    assert len(harness.genai.questions) == 1
    question = harness.genai.questions[0]
    assert "top three gainers and top three losers" in question
    gainers, losers = question.split("Top losers:")
    assert all(name in gainers for name in ["Uber Technologies Inc", "NVIDIA Corp", "Alphabet Inc Class A"])
    assert all(name in losers for name in ["Apple Inc", "Tesla Inc", "Intel Corp"])
    # only the top three of each are asked about
    assert "Salesforce" not in question and "JPMorgan" not in question

    assert len(harness.yag.sent) == 1
    assert email["to"] == USERS
    assert email["subject"].startswith("Todays Stock Data ")
    # the email body is the Dashboard as one line of HTML (yagmail would turn line breaks into <br>)
    body = email["contents"]
    assert "\n" not in body and AI_ERROR_ANSWER not in body
    assert "⛅ Mixed day — 10 up · 9 down · 1 flat · watchlist average ▼ 0.46%" in body
    assert "Biggest gain UBER ▲ 20.00% · biggest drop AAPL ▼ 25.00%" in body
    positions = [body.index("<b>{}</b>".format(ticker)) for ticker in ["UBER", "NVDA", "GOOGL", "AAPL", "TSLA", "INTC"]]
    assert positions == sorted(positions)
    assert "Salesforce" not in body and "All 20 stocks are in the attached spreadsheet." in body
    if not GEMINI_KEY:
        assert '<a href="https://news.example.com/2026/10/uber-robotaxi-expansion">Uber Takes Robotaxis Nationwide</a>' in body
    sheets = list(email["attachments"].values())[0]
    assert sheets["Stock Data"][:len(expected_rows)] == expected_rows
    # the Dashboard summarises the day and lists the top gainers and losers (rows 8-13)
    dashboard = sheets["Dashboard"]
    assert dashboard[2][0] == "\u26c5 Mixed day — 10 up · 9 down · 1 flat · watchlist average ▼ 0.46%"
    assert dashboard[3][0] == "Biggest gain UBER ▲ 20.00% · biggest drop AAPL ▼ 25.00%"
    table = dashboard[7:13]
    assert [row[:3] for row in table] == [
        ("\U0001F42E Gainer", "UBER", 0.2), ("\U0001F42E Gainer", "NVDA", 0.15), ("\U0001F42E Gainer", "GOOGL", 0.1),
        ("\U0001F43B Loser", "AAPL", -0.25), ("\U0001F43B Loser", "TSLA", -0.2), ("\U0001F43B Loser", "INTC", -0.1)]
    if not GEMINI_KEY:
        assert [row[3] for row in table] == ["Product / orders", "Product / orders", "Earnings / results",
                                             "Product / orders", "Earnings / results", "Guidance / outlook"]
        assert table[0][4] == "Shares jumped after Uber announced its robotaxi service is expanding to ten more cities."
        assert table[0][5] == "Uber Takes Robotaxis Nationwide"
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
    # Gemini was asked three times (waiting 30 then 60 seconds in between), then the email still has the
    # Dashboard, with a note that the AI's insight is missing
    assert len(harness.genai.questions) == 3 and harness.waits == [30, 60]
    assert AI_ERROR_ANSWER in email["contents"] and "GOOGL" in email["contents"]
    assert "No article found for this stock." in email["contents"]
    sheets = list(email["attachments"].values())[0]
    assert sheets["Stock Data"][:2] == [XLSX_HEADER, ("Alphabet Inc Class A", "GOOGL", "NASDAQ", 100.0, 110.0, 10.0, 0.1)]
    # without the AI's answer the Dashboard still lists the gainer, just without details
    assert sheets["Dashboard"][7] == ("\U0001F42E Gainer", "GOOGL", 0.1, "—", "No article found for this stock.", "—")
    assert_finished(harness)
