import json
import time
import uuid
from pathlib import Path
from datetime import datetime,timezone
from .io import public_data


class RunLog:
    def __init__(self,folder,component):
        self.path=Path(folder)/'run_events.jsonl';self.path.parent.mkdir(parents=True,exist_ok=True)
        self.run_id=uuid.uuid4().hex;self.component=component;self.started=time.monotonic();self.last=self.started

    def event(self,stage,**details):
        now=time.monotonic()
        data={'time':datetime.now(timezone.utc).isoformat(),'run_id':self.run_id,'component':self.component,
              'stage':stage,'elapsed_s':round(now-self.started,3),'previous_stage_s':round(now-self.last,3),
              **public_data(details)}
        with self.path.open('a',encoding='utf-8') as f:f.write(json.dumps(data,ensure_ascii=False)+'\n')
        self.last=now
