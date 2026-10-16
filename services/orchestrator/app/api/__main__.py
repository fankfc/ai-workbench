"""Local launcher; the desktop main process supplies WORKBENCH_API_TOKEN."""
import os
from pathlib import Path
import uvicorn
from app.config import AppSettings
from .application import create_app

if __name__=='__main__':
    token=os.environ.get('WORKBENCH_API_TOKEN','')
    root=Path(os.environ.get('WORKBENCH_DATA_ROOT',str(Path.home()/'AppData/Local/AgentWorkbench')))
    uvicorn.run(create_app(AppSettings(root,token,'real',True)),host='127.0.0.1',port=8765,access_log=False)
