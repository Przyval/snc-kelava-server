import importlib
import sys

packages = [
    "pandas",
    "numpy",
    "matplotlib",
    "seaborn",
    "plotly",
    "streamlit",
    "altair",
    "scipy",
    "statsmodels",
    "great_tables",
    "jinja2",
    "reportlab",
    "weasyprint",
    "kaleido",
    "sqlalchemy",
    "psycopg",
    "duckdb",
    "polars",
    "dotenv",
]

print(f"Python version: {sys.version}")
print("-" * 40)

failed = []
for package in packages:
    try:
        module = importlib.import_module(package)
        version = getattr(module, "__version__", "unknown")
        print(f"✅ {package:<15} : {version}")
    except ImportError as e:
        print(f"❌ {package:<15} : NOT FOUND ({e})")
        failed.append(package)

print("-" * 40)
if failed:
    print(f"Failed to import: {', '.join(failed)}")
    sys.exit(1)
else:
    print("All packages installed successfully!")
