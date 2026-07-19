import sys, asyncio, time
sys.path.insert(0, '.'); sys.path.insert(0, 'src')
from pathlib import Path
from omnicast.pipeline.runner import PipelineRunner
async def main():
    r = PipelineRunner(db_path=Path('output/vault.db'))
    t0=time.time()
    ex = await r.run_file(Path('pipelines/default_channel.yaml'),
                          inputs={'channel_id':'beat_glp1_nausea','do_upload':False})
    print(f'\n==== PIPELINE {ex.status} in {time.time()-t0:.0f}s ====')
    for sid,res in ex.steps.items():
        o=res.outputs or {}
        print(f'  [{res.status}] {sid}  ' + str({k:str(v)[:70] for k,v in o.items() if k in ("topic","script_path","video_path","file_size_mb","score")}))
    if ex.error: print('ERROR:', ex.error[:300])
asyncio.run(main())
