import unittest
from mac_worker_contract import contract


class WorkerContractTests(unittest.TestCase):
    def test_job_states_without_secrets_or_user_data(self):
        source = b'''SECRET = "private-password"
def resume_jobs():
    c.execute("UPDATE jobs SET status='queued' WHERE status='running' AND token='private-password'")
def worker_main():
    result = "private-user-lyrics"
    if job['status'] == 'queued':
        job_runner(job)
def do_GET(self):
    if self.path == '/api/jobs': pass
    if self.path == '/api/private-password': pass
'''
        output = contract(source)
        self.assertIn('UPDATE jobs SET status=', output)
        self.assertIn('queued', output)
        self.assertIn('/api/jobs', output)
        self.assertNotIn('private-password', output)
        self.assertNotIn('private-user-lyrics', output)
        self.assertNotIn('/api/private-password', output)


if __name__ == '__main__':
    unittest.main()
