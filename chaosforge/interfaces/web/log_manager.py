import threading


class LogManager:
    def __init__(self):

        self.lock = threading.Lock()

        self.lines = []

        self.running = False

        self.finished = False

        self.current = 0

        self.total = 0

        self.current_experiment = ""

    def clear(self):

        with self.lock:
            self.lines.clear()

            self.running = False

            self.finished = False

            self.current = 0

            self.total = 0

            self.current_experiment = ""

    def append(self, line):

        with self.lock:
            self.lines.append(str(line))

    def get_logs(self):

        with self.lock:
            return list(self.lines)


log_manager = LogManager()
log_managers = {"aws": log_manager}


def get_log_manager(cloud=None):
    cloud = cloud if cloud in {"aws", "azure"} else "aws"
    if cloud not in log_managers:
        log_managers[cloud] = LogManager()
    return log_managers[cloud]
