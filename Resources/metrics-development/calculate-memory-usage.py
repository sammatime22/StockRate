# from collections import namedtuple
from dataclasses import dataclass
import datetime
import traceback

MAX_MEMORY_AVAILABLE_KB=.5*1000*1000 # .5GB
PYTHON_3_X_SLIM_FACTOR = .1*1000*1000 # est 100MB of memory usage w/container alone
STOCK_QUANTITY_PULLED_TODAY=10
# just a script to use the metrics output to determine the amount of memory in use by the collector
data = open("Resources/metrics-development/stockratestats.txt", "r")
data_lines = data.readlines()

@dataclass
class DailyUsageMetric: 
    date: str
    duration: int
    avg_memory_in_use_kb: float

daily_usage_metrics = {}

potential_date_line = None

for line in data_lines:
    try: 
        if "Collector" in line:
            ourdate = str(datetime.datetime.strptime(potential_date_line[4:].replace("\n",""), "%b %d %H:%M:%S %Z %Y")).split()[0]
            # we want to pull the time and memory
            memory_usage = int(line.split()[0])
            daily_usage_metric_of_use = None
            if ourdate in daily_usage_metrics:
                daily_usage_metric_of_use = daily_usage_metrics[ourdate]
                daily_usage_metric_of_use.avg_memory_in_use_kb = ((daily_usage_metric_of_use.avg_memory_in_use_kb * daily_usage_metric_of_use.duration) + memory_usage) / (daily_usage_metric_of_use.duration + 1)
                daily_usage_metric_of_use.duration = daily_usage_metric_of_use.duration + 1
            else:
                daily_usage_metric_of_use = DailyUsageMetric(date=ourdate, duration=1, avg_memory_in_use_kb=memory_usage)
                daily_usage_metrics[ourdate] = daily_usage_metric_of_use
        else:
            potential_date_line = line
    except Exception as e:
        traceback.print_exc()
        

# Next, do a runthrough of the maximum number of stocks we can pull within 1hr
# Also, calculate the amount of memory in use on average per one stock
average_duration_lambda = lambda x: sum(obj.duration for obj in x.values()) / len(x)
num_stocks_per_collector = (average_duration_lambda(daily_usage_metrics) / 10) * 60
amount_of_memory_in_use_per_stock_lambda = lambda x: (sum(obj.avg_memory_in_use_kb for obj in x.values()) + (len(x) * PYTHON_3_X_SLIM_FACTOR)) / len(x)
amount_of_memory_in_use_per_stock = amount_of_memory_in_use_per_stock_lambda(daily_usage_metrics)

# Finally, take that average memory, and divide the total memory available by this to determine the nubmer of collectors we can run
num_of_collectors = MAX_MEMORY_AVAILABLE_KB / amount_of_memory_in_use_per_stock 

# We should now have the number of collectors we can be running at one time, and in one hour how many stocks we should be able to pull
print("Number of Collectors per Current Infrastructure: " + str(int(num_of_collectors)))
print("Number of Stocks to Pull per Collector: " + str(int(num_stocks_per_collector)))
