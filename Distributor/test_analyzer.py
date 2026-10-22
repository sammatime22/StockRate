# Unit tests for analyzer.py, one per function. No MariaDB or Gemini is needed.
# sammatime22, 2026
#
# Setup on iSH (Alpine):
#   apk add python3 py3-pytest py3-openpyxl
#
# Run from the Distributor directory:
#   python3 -m pytest test_analyzer.py
import os
import sys
import types

import openpyxl
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# analyzer imports google.generativeai at the top, so stand it in before importing analyzer
if "google.generativeai" not in sys.modules:
    fake_genai = types.ModuleType("google.generativeai")
    fake_genai.GenerativeModel = None
    fake_google = types.ModuleType("google")
    fake_google.generativeai = fake_genai
    sys.modules["google"] = fake_google
    sys.modules["google.generativeai"] = fake_genai

import analyzer

STOCK_NAMES = {
    1: ("Alphabet Inc Class A", "GOOGL:NASDAQ"),
    2: ("Apple Inc", "AAPL:NASDAQ"),
    3: ("Microsoft Corp", "MSFT:NASDAQ"),
}

# Newest pull first, as the distributor's query returns it: today's pull (4-6) then yesterday's (1-3)
MARIADB_DATA = [(3, 50.0), (2, 150.0), (1, 110.0), (3, 50.0), (2, 200.0), (1, 100.0)]


class FakeCursor:
    '''
    Answers the analyzer's stock name query from STOCK_NAMES.
    '''

    def __init__(self):
        self.stock_id = None

    def execute(self, sql):
        self.stock_id = int(sql.rsplit("=", 1)[1].rstrip(";"))

    def fetchall(self):
        return [STOCK_NAMES[self.stock_id]] if self.stock_id in STOCK_NAMES else []


class FakeGenAI:
    '''
    Records the question asked and gives a canned answer.
    '''

    def __init__(self, answer):
        self.answer = answer
        self.questions = []

    def GenerativeModel(self, model_name):
        fake = self

        class Model:
            def generate_content(self, query):
                fake.questions.append(query)
                return types.SimpleNamespace(text=fake.answer)

        return Model()


def finding(stock_id, yesterday_price, today_price):
    name, acronym = STOCK_NAMES[stock_id]
    return {"stock_id": stock_id, "stock_name": name, "acronym": acronym, "yesterday_price": yesterday_price,
            "today_price": today_price, "difference": today_price - yesterday_price,
            "rate_of_change": (today_price - yesterday_price) / yesterday_price}


def test_run_analyze(monkeypatch, tmp_path):
    fake_genai = FakeGenAI("Alphabet rose and Apple fell.")
    monkeypatch.setattr(analyzer, "genai", fake_genai)
    xlsx_location = str(tmp_path / "report.xlsx")
    config = {"email_config": {"attachment": xlsx_location}}

    blurb = analyzer.run_analyze(MARIADB_DATA, FakeCursor(), config)

    assert blurb == "Alphabet rose and Apple fell."
    assert len(fake_genai.questions) == 1
    rows = list(openpyxl.load_workbook(xlsx_location)["Stock Data"].iter_rows(values_only=True))
    assert rows == [
        tuple(analyzer.XLSX_HEADER),
        ("Alphabet Inc Class A", "GOOGL:NASDAQ", 100.0, 110.0, 10.0, 0.1),
        ("Microsoft Corp", "MSFT:NASDAQ", 50.0, 50.0, 0.0, 0.0),
        ("Apple Inc", "AAPL:NASDAQ", 200.0, 150.0, -50.0, -0.25),
    ]


def test_format_findings():
    # Stock 4 has only one price and stock 5 had a price of 0, so neither can have a rate of change.
    # Stocks 6 and 7 have a missing (-1) old or new price, and stock 8 uses -1 as an int, so all are left out.
    findings = analyzer.format_findings(MARIADB_DATA + [(4, 10.0), (5, 3.0), (5, 0.0), (6, -1.0), (6, 20.0),
                                                        (7, 30.0), (7, -1.0), (8, -1), (8, 40.0)])

    assert findings == [
        {"stock_id": 3, "stock_name": None, "acronym": None, "yesterday_price": 50.0, "today_price": 50.0,
         "difference": 0.0, "rate_of_change": 0.0},
        {"stock_id": 2, "stock_name": None, "acronym": None, "yesterday_price": 200.0, "today_price": 150.0,
         "difference": -50.0, "rate_of_change": -0.25},
        {"stock_id": 1, "stock_name": None, "acronym": None, "yesterday_price": 100.0, "today_price": 110.0,
         "difference": 10.0, "rate_of_change": 0.1},
    ]


def test_sort_findings():
    findings = [finding(3, 50.0, 50.0), finding(2, 200.0, 150.0), finding(1, 100.0, 110.0)]

    sorted_findings = analyzer.sort_findings(findings)

    assert [f["stock_id"] for f in sorted_findings] == [1, 3, 2]


def test_get_insight(monkeypatch):
    fake_genai = FakeGenAI("Here is today's insight.")
    monkeypatch.setattr(analyzer, "genai", fake_genai)
    sorted_data = [finding(1, 100.0, 110.0), finding(3, 50.0, 50.0), finding(2, 200.0, 150.0)]

    blurb = analyzer.get_insight(sorted_data)

    assert blurb == "Here is today's insight."
    question = fake_genai.questions[0]
    gainers, losers = question.split("Top losers:")
    assert "Alphabet Inc Class A (GOOGL:NASDAQ): 100.0 -> 110.0 (+10.00%)" in gainers
    assert "Apple Inc (AAPL:NASDAQ): 200.0 -> 150.0 (-25.00%)" in losers
    # an unchanged stock is neither a gainer nor a loser
    assert "Microsoft" not in question


def test_develop_xlsx(tmp_path):
    xlsx_location = str(tmp_path / "report.xlsx")
    sorted_data = [finding(1, 100.0, 110.0), finding(2, 200.0, 150.0)]

    analyzer.develop_xlsx(sorted_data, "First line.\nSecond line.", xlsx_location)

    workbook = openpyxl.load_workbook(xlsx_location)
    assert workbook.sheetnames == ["Stock Data", "Insight"]
    data_sheet = workbook["Stock Data"]
    assert list(data_sheet.iter_rows(values_only=True)) == [
        tuple(analyzer.XLSX_HEADER),
        ("Alphabet Inc Class A", "GOOGL:NASDAQ", 100.0, 110.0, 10.0, 0.1),
        ("Apple Inc", "AAPL:NASDAQ", 200.0, 150.0, -50.0, -0.25),
    ]
    assert data_sheet["F2"].number_format == "0.00%"
    assert list(workbook["Insight"].iter_rows(values_only=True)) == [("First line.",), ("Second line.",)]
