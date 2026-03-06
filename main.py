import threading
import time

from crawler_worker import index_topic
from telegram_bot import run_bot


# topics that commonly appear in study queries
SEED_TOPICS = [
    "artificial intelligence",
    "machine learning",
    "blockchain",
    "cybersecurity",
    "biochemistry",
    "genomics",
    "quantum computing",
    "data science",
    "robotics",
    "distributed systems"
]

CRAWL_INTERVAL = 120    # 2 min between topics (was 60s — too aggressive)
CYCLE_SLEEP = 7200      # 2 hours between full cycles (was 1 hour)

def background_indexer():
    while True:
        for topic in SEED_TOPICS:
            try:
                print(f"[Indexer] Crawling: {topic}")
                index_topic(topic)
            except Exception as e:
                print("Indexer error:", e)
            time.sleep(CRAWL_INTERVAL)

        print("[Indexer] Cycle complete. Sleeping...")
        time.sleep(CYCLE_SLEEP)


def main():

    # start background crawler
    crawler_thread = threading.Thread(target=background_indexer)
    crawler_thread.daemon = True
    crawler_thread.start()

    # start telegram bot
    run_bot()


if __name__ == "__main__":
    main()