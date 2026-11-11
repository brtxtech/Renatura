"""Per-job subprocess isolation gives every node a real stop operation."""
import multiprocessing as mp,threading,uuid,queue,time,traceback
from . import db
from .nodes import NODES as OBSERVATION_NODES
from .ingestion import NODES as INGESTION_NODES
NODES={**OBSERVATION_NODES,**INGESTION_NODES}
ACTIVE={};LOCK=threading.RLock()
class Context:
    def __init__(self,job,node,stop):self.job=job;self.node=node;self.stop=stop
    def log(self,message,level='info'):db.event(self.job,self.node,message,level)
    def check(self):
        if self.stop.is_set():raise InterruptedError('Cancelled by user')
def child(job,node,payload,stop,out):
    try:
        result=NODES[node](payload,Context(job,node,stop));out.put(('ok',result))
    except BaseException as e:
        # Persist a concise error; never expose traceback or environment secrets.
        db.event(job,node,f'{type(e).__name__}: node execution failed','error');out.put(('error',type(e).__name__))
def create(payload,node=None,order=None):
    if node is not None and node not in NODES:raise ValueError('Unknown node')
    job_id=uuid.uuid4().hex;payload={**payload,'id':payload.get('id') or uuid.uuid4().hex}
    job={'id':job_id,'state':'queued','nodes':{k:'idle' for k in NODES},'payload':payload,'output':None,'single_node':node,'active_node':None,'order':order or ([node] if node else list(OBSERVATION_NODES))}
    db.put('jobs',job_id,job)
    with LOCK:ACTIVE[job_id]={'cancel':threading.Event(),'process':None,'node':None}
    threading.Thread(target=worker,args=(job_id,),daemon=True).start()
    return job_id

def worker(job_id):
    job=db.get('jobs',job_id);payload=job['payload'];control=ACTIVE[job_id]
    order=job.get('order') or ([job['single_node']] if job['single_node'] else list(OBSERVATION_NODES))
    context=mp.get_context('spawn')
    try:
        for node in order:
            if control['cancel'].is_set():job['state']='stopped';break
            job['state']='running';job['active_node']=node;job['nodes'][node]='running';db.put('jobs',job_id,job)
            db.event(job_id,node,'Execution started')
            out=context.Queue();stop=context.Event();proc=context.Process(target=child,args=(job_id,node,payload,stop,out))
            with LOCK:
                if control['cancel'].is_set():job['nodes'][node]='stopped';job['state']='stopped';break
                control.update(process=proc,node=node,stop=stop);proc.start()
            started=time.monotonic();result=None
            while result is None:
                if control['cancel'].is_set():
                    stop.set()
                    if proc.is_alive():proc.terminate()
                    proc.join(3);job['nodes'][node]='stopped';job['state']='stopped';break
                if time.monotonic()-started>120:
                    proc.terminate();proc.join(3);result=('error','timeout');break
                try: result=out.get(timeout=.1)
                except queue.Empty:
                    if not proc.is_alive():
                        try:result=out.get(timeout=.3)
                        except queue.Empty:result=('error','worker exited')
            if job['state']=='stopped':db.event(job_id,node,'Stopped. Downstream nodes were not executed.','warning');break
            proc.join(3)
            if proc.is_alive():proc.terminate();proc.join(3)
            out.close()
            if result[0]!='ok':
                job['nodes'][node]='failed';job['state']='failed';job['error']=result[1];break
            payload=result[1];job['nodes'][node]='completed';job['output']=payload
            db.event(job_id,node,f'Completed in {time.monotonic()-started:.2f}s');db.put('jobs',job_id,job)
        else:
            job['state']='completed'
            if not job['single_node'] and 'chat' in order:db.put('observations',payload['id'],payload)
    except Exception:
        job['state']='failed';job['error']='Workflow execution failed';db.event(job_id,job.get('active_node') or 'system','Workflow execution failed','error')
    finally:
        job['active_node']=None;db.put('jobs',job_id,job)
        with LOCK:ACTIVE.pop(job_id,None)

def stop(job_id,node=None):
    with LOCK:
        control=ACTIVE.get(job_id)
        if not control:return False
        if node and control.get('node')!=node:return False
        control['cancel'].set()
        if control.get('stop'):control['stop'].set()
        return True
