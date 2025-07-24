# from collections import namedtuple
from dataclasses import dataclass
import datetime
import traceback

MAX_MEMORY_AVAILABLE_KB=4*1000*1000 # 4GB
STOCK_QUANTITY_PULLED_TODAY=10
# just a script to use the metrics output to determine the amount of memory in use by the collector
tissue = open("Resources/metrics-development/stockratestats.txt", "r")
tissue_lines = tissue.readlines()

@dataclass
class DailyUsageMetric: 
    date: str
    duration: int
    avg_memory_in_use_kb: float

daily_usage_metrics = {}

potential_date_line = None
# print(len(tissue_lines))
for line in tissue_lines:
    try: 
        if "Collector" in line:
            # print(line + " " + potential_date_line)
            # get date Sun Mar 23 23:00:01 EDT 2025
            ourdate = str(datetime.datetime.strptime(potential_date_line[4:].replace("\n",""), "%b %d %H:%M:%S %Z %Y")).split()[0]
            # print(ourdate)
            # print("abcd")
            # we want to pull the time and memory
            memory_usage = int(line.split()[0])
            # print(memory_usage)
            daily_usage_metric_of_use = None
            # if daily_usage_metrics[ourdate] is not None:
            if ourdate in daily_usage_metrics:
                # print("there")
                daily_usage_metric_of_use = daily_usage_metrics[ourdate]
                # print("wahoo")
                daily_usage_metric_of_use.avg_memory_in_use_kb = ((daily_usage_metric_of_use.avg_memory_in_use_kb * daily_usage_metric_of_use.duration) + memory_usage) / (daily_usage_metric_of_use.duration + 1)
                # print("alright homies")
                daily_usage_metric_of_use.duration = daily_usage_metric_of_use.duration + 1
                # print(daily_usage_metric_of_use.duration)
            else:
                daily_usage_metric_of_use = DailyUsageMetric(date=ourdate, duration=1, avg_memory_in_use_kb=memory_usage)
                daily_usage_metrics[ourdate] = daily_usage_metric_of_use
                # print(daily_usage_metrics)
            # print(daily_usage_metrics)
        else:
            potential_date_line = line
            # print(line)
    except Exception as e:
        # continue
        # print("ok")
        # continue
        # if potential_date_line is not None:
        #     print(str(e))
        #     traceback.print_exc()
        #     break
        traceback.print_exc()
        # potential_date_line = line
        

# Next, do a runthrough of the maximum number of stocks we can pull within 1hr
# Also, calculate the amount of memory in use on average per one stock
average_duration_lambda = lambda x: sum(obj.duration for obj in x.values()) / len(x)
# print(str(daily_usage_metrics))
num_stocks_per_collector = (average_duration_lambda(daily_usage_metrics) / 10) * 60
amount_of_memory_in_use_per_stock_lambda = lambda x: sum(obj.avg_memory_in_use_kb for obj in x.values()) / len(x)
amount_of_memory_in_use_per_stock = amount_of_memory_in_use_per_stock_lambda(daily_usage_metrics)

# Finally, take that average memory, and divide the total memory available by this to determine the nubmer of collectors we can run
num_of_collectors = MAX_MEMORY_AVAILABLE_KB / amount_of_memory_in_use_per_stock 

# We should now have the number of collectors we can be running at one time, and in one hour how many stocks we should be able to pull
print("Number of Collectors per Current Infrastructure: " + str(num_of_collectors))
print("Number of Stocks to Pull per Collector: " + str(num_stocks_per_collector))
