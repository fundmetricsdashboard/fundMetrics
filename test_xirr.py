from utils import calculate_xirr
import datetime

# Axis Liquid Fund flows
flows = [
    (datetime.date(2024, 2, 26), -499975.00),
    (datetime.date(2024, 3, 18), -199990.00),
    (datetime.date(2024, 11, 25), 200000.00),
    (datetime.date.today(), 781745.6560032)
]

xirr_result = calculate_xirr(flows)
print("XIRR result:", xirr_result, "%")
