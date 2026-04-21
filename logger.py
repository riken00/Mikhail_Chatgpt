import os
import datetime
import pytz

tz = pytz.timezone('Asia/Kolkata')

class CustomLogger:
    def __init__(self, log_folder: str):
        if not log_folder:
            raise ValueError("❌ Please provide a valid log folder path.")

        self.log_folder = os.path.abspath(log_folder)
        self._setup_log_directory()
        print(f"Log file location : {self.log_folder}")
        
        self.files = {
            "info": os.path.join(self.log_folder, "info.log"),
            "error": os.path.join(self.log_folder, "error.log"),
            "warning": os.path.join(self.log_folder, "warning.log"),
        }
        for file in self.files.values():
            if not os.path.exists(file):
                open(file, 'a').close()
        
        self._cleanup_old_logs()

    def _cleanup_old_logs(self):
        cutoff_date = datetime.datetime.now(tz) - datetime.timedelta(days=7)
        for log_path in self.files.values():
            if not os.path.exists(log_path):
                continue
            
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                clean_lines = []
                for line in lines:
                    try:
                        log_date_str = line.split(' - ')[0]
                        log_date = datetime.datetime.strptime(log_date_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=tz)
                        
                        if log_date >= cutoff_date:
                            clean_lines.append(line)
                    except (ValueError, IndexError):
                        clean_lines.append(line)
                
                if len(clean_lines) != len(lines):
                    with open(log_path, 'w', encoding='utf-8') as f:
                        f.writelines(clean_lines)
            except Exception as e:
                print(f"Error cleaning up {log_path}: {e}")

    def _setup_log_directory(self):
        if not os.path.exists(self.log_folder):
            os.makedirs(self.log_folder)
            print(f"📁 Created log directory: {self.log_folder}")

    def _write_log(self, level: str, message: str):
        timestamp = datetime.datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')
        log_message = f"{timestamp} - {level.upper()} - {message}\n"

        print(log_message.strip())
        
        level_file = self.files.get(level.lower())
        if level_file:
            with open(level_file, "a", encoding="utf-8") as f:
                f.write(log_message)

    def info(self, message: str):
        self._write_log("info", message)

    def error(self, message: str):
        self._write_log("error", message)

    def warning(self, message: str):
        self._write_log("warning", message)

    def log(self, message: str):
        self._write_log("info", message)
