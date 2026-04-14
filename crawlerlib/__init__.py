"""
CrawlerLib — A premium, production-grade web crawling library.

Usage:
    from crawlerlib import Crawler

    crawler = Crawler(url="https://example.com")
    results = crawler.crawl()
"""

from crawlerlib.crawler import Crawler
from crawlerlib.fetcher import Fetcher
from crawlerlib.parser import PageParser
from crawlerlib.storage import JSONStorage
from crawlerlib.navigator import PageNavigator
from crawlerlib.extractor import StructuredExtractor

__version__ = "2.0.0"
__all__ = [
    "Crawler",
    "Fetcher",
    "PageParser",
    "JSONStorage",
    "PageNavigator",
    "StructuredExtractor",
]
