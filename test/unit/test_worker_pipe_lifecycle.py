"""A silent worker must respect timeouts and cannot block terminal signals."""
import json
import subprocess
import sys
import time

from src.core.uv_manager import UVManager
from test.unit.test_parity_repairs import isolated


def spawn(script):
    return subprocess.Popen([sys.executable,'-u','-c',script],stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')


def close(process):
    if process.poll() is None:process.kill()
    process.wait(timeout=5)
    for pipe in [process.stdin,process.stdout,process.stderr]:pipe.close()


def test_silent_worker_response_has_a_real_deadline(isolated):
    process=spawn('import sys,time;sys.stdin.readline();time.sleep(20)')
    try:
        start=time.monotonic()
        result=UVManager().send_command_to_worker(process,{'type':'run_node'},timeout=.2)
        assert not result['success'] and '超时' in result['error']
        assert time.monotonic()-start<2
    finally:close(process)


def test_worker_pipes_are_drained_and_reused_across_commands(isolated):
    script='''import sys,json
for line in sys.stdin:
 request=json.loads(line)
 sys.stderr.write('diagnostic\\n' * 50000);sys.stderr.flush()
 print('###JSON_OUTPUT###')
 print(json.dumps({'success':True,'data':request}))
 print('###JSON_OUTPUT_END###',flush=True)
'''
    process=spawn(script)
    try:
        manager=UVManager()
        for i in range(2):
            result=manager.send_command_to_worker(process,{'sequence':i},timeout=5)
            assert result=={'success':True,'data':{'sequence':i}}
        assert len(process._mozikit_channels.threads)==2
    finally:close(process)
