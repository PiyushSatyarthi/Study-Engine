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


def background_indexer():

    while True:

        for topic in SEED_TOPICS:

            try:
                print(f"[Indexer] Crawling topic: {topic}")
                index_topic(topic)

            except Exception as e:
                print("Indexer error:", e)

            # wait a bit between crawls
            time.sleep(60)

        # full cycle delay
        print("[Indexer] Sleeping before next crawl cycle...")
        time.sleep(3600)


def main():

    # start background crawler
    crawler_thread = threading.Thread(target=background_indexer)
    crawler_thread.daemon = True
    crawler_thread.start()

    # start telegram bot
    run_bot()


if __name__ == "__main__":
    main()