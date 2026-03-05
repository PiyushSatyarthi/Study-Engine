from pymongo import MongoClient

client = MongoClient("mongodb+srv://2025191453piyush_db_user:Nwle96FedSr6TGEV@cluster0.smtpjro.mongodb.net/?appName=Cluster0")

db = client["study_engine"]

resources = db["resources"]