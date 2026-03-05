import os
from pymongo import MongoClient
from dotenv import load_dotenv
load_dotenv()
client = MongoClient(os.getenv("MONGO_URI"))

db = client["study_engine"]

resources = db["resources"]
payments = db["payments"]
users = db["users"]