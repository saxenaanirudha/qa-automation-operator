"""Load all sample CSV files into the database."""
import os
from src.parser.csv_parser import parse_csv
from src.database.database import init_db
from src.database.repository import save_build_result, DuplicateBuildError

init_db()

for csv_file in [
    "test_results_243.csv",
    "test_results_244.csv",
    "test_results.csv",       # build 245
    "test_results_246.csv",
    "test_results_247.csv",
]:
    path = os.path.join("sample_data", csv_file)
    try:
        result = parse_csv(path)
        save_build_result(result, result["data"])
        print("Loaded build", result["build"])
    except DuplicateBuildError:
        print("Already stored:", csv_file)
    except Exception as e:
        print("Error loading", csv_file, ":", e)
