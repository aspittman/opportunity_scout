"""A single scheduler owned by the CLI process, never Flask imports/reloaders."""
import fcntl
from apscheduler.schedulers.background import BackgroundScheduler


class LocalScheduler:
    def __init__(self, research, lock_path):
        self.research = research
        self.lock_path = lock_path
        self.scheduler = BackgroundScheduler(timezone='UTC')
        self.handle = None

    def start(self):
        self.handle = open(self.lock_path, 'a')
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.handle.close()
            self.handle = None
            return False
        self.configure()
        self.scheduler.start()
        return True

    def configure(self):
        # One dispatcher checks independent durable due times. Two simultaneous jobs
        # would compete for the global research lock and could starve one service.
        self.scheduler.add_job(self.research.run, 'interval', minutes=5,
                               kwargs={'due_only': True}, id='research', replace_existing=True,
                               max_instances=1, coalesce=True)
        self.scheduler.add_job(self.research.maintenance, 'interval', hours=24, id='maintenance', replace_existing=True, max_instances=1, coalesce=True)

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
        if self.handle:
            self.handle.close()
            self.handle = None
