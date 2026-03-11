class Status:
    OK = 'ok'
    FAIL = 'fail'
    ERROR = 'error'

class Result:
    def __init__(self, stdout: str = '', stderr: str = '', failed: bool = False, status: Status = Status.OK):
        self.failed = failed
        self.stdout = stdout
        self.stderr = stderr
        self.status = status

    def to_dict(self):
        return {'failed': self.failed, 'stdout': self.stdout, 'stderr': self.stderr, 'status': self.status}