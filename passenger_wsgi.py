# passenger_wsgi.py
import os, sys
BASE_DIR = os.path.dirname(__file__)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import app as application  # Passenger looks for `application`
