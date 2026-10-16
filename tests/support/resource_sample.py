"""Read-only Windows process metrics; failures remain unknown."""
import json
import subprocess


def resource_sample(pid):
    if type(pid) is not int or pid <= 0:
        raise ValueError('PROCESS_ID_REQUIRED')
    command = f'Get-Process -Id {pid} -ErrorAction Stop | Select-Object Id,WorkingSet64,HandleCount,@{{Name="ThreadCount";Expression={{$_.Threads.Count}}}} | ConvertTo-Json -Compress'
    completed = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
        capture_output=True, text=True, encoding='utf-8', timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    if completed.returncode:
        return dict(pid=pid, rss_bytes=None, handles=None, threads=None, observation_error='process_sample_failed')
    value = json.loads(completed.stdout)
    return dict(pid=value['Id'], rss_bytes=value['WorkingSet64'], handles=value['HandleCount'], threads=value['ThreadCount'])
