from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import sys
import types
from pathlib import Path

# Support direct execution without initializing the CoScientist agent application.
if not __package__:
    if 'CoScientist' not in sys.modules:
        package = types.ModuleType('CoScientist')
        package.__path__ = [str(Path(__file__).resolve().parents[1])]
        package.__package__ = 'CoScientist'
        sys.modules['CoScientist'] = package
    __package__ = 'CoScientist.sapphire_pipeline'

from .client import SapphireClient
from .pipeline import SapphirePipeline


def main():
    """Run one ingestion pass using CLI options and a local exclusive lock.

    Print outcome counters and return 1 for article failures, otherwise 0.
    Argument and lock errors exit through argparse; other errors propagate.
    Close the HTTP client when the pass finishes or fails.
    """
    parser = argparse.ArgumentParser(description='Update RAG from Sapphire (one complete pass)')
    parser.add_argument('--url', default=os.getenv('SAPPHIRE_URL', 'http://fpin-projects.ru:12280'))
    parser.add_argument('--page-size', type=int, default=1)
    parser.add_argument('--max-articles', type=int, help='Maximum number of publications to inspect')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--max-pdf-mb', type=int, default=100)
    parser.add_argument('--lock-file', type=Path, default=Path('data/sapphire_pipeline.lock'))
    args = parser.parse_args()
    if args.max_articles is not None and args.max_articles < 1:
        parser.error('--max-articles must be positive')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    client = SapphireClient(args.url, args.page_size, args.timeout, args.max_pdf_mb * 1024 * 1024)
    try:
        args.lock_file.parent.mkdir(parents=True, exist_ok=True)
        with args.lock_file.open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                parser.exit(1, 'Sapphire pipeline is already running with this lock file\n')
            from .runtime import RAGBackend
            counts = SapphirePipeline(client, RAGBackend()).run(max_articles=args.max_articles)
            print(json.dumps(counts, ensure_ascii=False, indent=2))
            return 1 if counts.get('failed') else 0
    finally:
        client.close()


if __name__ == '__main__':
    raise SystemExit(main())
