from collections import defaultdict
from django.utils import timezone
from django.db import transaction
from app.models import (
    ProcessingStatsHourly,
    ProcessingStatsDaily,
    ProcessingStatsOverall,
)
from threading import Lock


class StatsCollector:
    def __init__(self, file_name: str, flush_every: int = 50):  # increased default
        self.file_name = file_name
        self.flush_every = flush_every
        self.buffer = []
        self.counter = 0
        self._buffer_lock = Lock()
        self._db_lock = Lock()  # only one thread writes to DB at a time

    def log(self, success: bool, processing_time: float):
        now = timezone.now()
        with self._buffer_lock:
            self.buffer.append((now, success, processing_time))
            self.counter += 1
            should_flush = self.counter >= self.flush_every

        if should_flush:
            self.flush()

    def flush(self):
        with self._buffer_lock:
            if not self.buffer:
                return
            snapshot = self.buffer[:]
            self.buffer = []
            self.counter = 0

        # aggregate first, outside DB lock
        hourly_data = defaultdict(lambda: {"processed": 0, "success": 0, "failed": 0, "time": 0})
        daily_data  = defaultdict(lambda: {"processed": 0, "success": 0, "failed": 0, "time": 0})
        total_processed = total_success = total_failed = total_time = 0

        for now, success, t in snapshot:
            date = now.date()
            hour = now.hour

            key_h = (date, hour)
            hourly_data[key_h]["processed"] += 1
            hourly_data[key_h]["success"]   += int(success)
            hourly_data[key_h]["failed"]    += int(not success)
            hourly_data[key_h]["time"]      += t

            daily_data[date]["processed"] += 1
            daily_data[date]["success"]   += int(success)
            daily_data[date]["failed"]    += int(not success)
            daily_data[date]["time"]      += t

            total_processed += 1
            total_success   += int(success)
            total_failed    += int(not success)
            total_time      += t

        # single serialized DB write
        with self._db_lock:
            with transaction.atomic():
                for (date, hour), data in hourly_data.items():
                    obj, _ = ProcessingStatsHourly.objects.get_or_create(
                        file_name=self.file_name, date=date, hour=hour
                    )
                    obj.processed  += data["processed"]
                    obj.success    += data["success"]
                    obj.failed     += data["failed"]
                    obj.total_time += data["time"]
                    obj.avg_time    = obj.total_time / obj.processed
                    obj.save()

                for date, data in daily_data.items():
                    obj, _ = ProcessingStatsDaily.objects.get_or_create(
                        file_name=self.file_name, date=date
                    )
                    obj.processed  += data["processed"]
                    obj.success    += data["success"]
                    obj.failed     += data["failed"]
                    obj.total_time += data["time"]
                    obj.avg_time    = obj.total_time / obj.processed
                    obj.save()

                obj, _ = ProcessingStatsOverall.objects.get_or_create(
                    file_name=self.file_name
                )
                obj.processed  += total_processed
                obj.success    += total_success
                obj.failed     += total_failed
                obj.total_time += total_time
                obj.avg_time    = obj.total_time / obj.processed
                obj.save()