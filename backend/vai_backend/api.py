from __future__ import annotations
import hmac
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, Depends, Header, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from . import __version__
from .config import Settings
from .manager import RunManager
from .models import TaskSpec, RunResult, ParseRequest
from .parsing import parse_question

class ApiFailure(Exception):
    def __init__(self,status,code,message,details=None):
        self.status=status;self.code=code;self.message=message;self.details=details

class ParseResponse(BaseModel):
    supported: bool
    task: TaskSpec | None = None
    missing_fields: list[str] = Field(default_factory=list)
    defaults_applied: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requires_confirmation: Literal[True] = True

class RunList(BaseModel):
    runs: list[RunResult]

def create_app(settings:Settings|None=None,manager:RunManager|None=None):
    settings=settings or Settings.from_env()
    manager=manager or RunManager(settings.data_dir)
    @asynccontextmanager
    async def lifespan(app):
        manager.start()
        try:yield
        finally:manager.close()
    app=FastAPI(title='VAI Virtuoso Automation API',version='1.0.0',lifespan=lifespan,
        description='RC task planning, isolated real Cadence runs, verified screenshots and reports. Single worker only.')
    app.state.manager=manager;app.state.settings=settings
    app.add_middleware(CORSMiddleware,allow_origins=list(settings.cors_origins),allow_credentials=False,
                       allow_methods=['GET','POST','OPTIONS'],allow_headers=['Authorization','Content-Type'])
    @app.exception_handler(ApiFailure)
    async def api_error(request,exc):
        return JSONResponse(status_code=exc.status,content={'error':{'code':exc.code,'message':exc.message,'details':exc.details}})
    @app.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        details=[{'location':list(e['loc']),'message':e['msg'],'type':e['type']} for e in exc.errors()]
        return JSONResponse(status_code=422,content={'error':{'code':'VALIDATION_ERROR','message':'Request did not pass validation','details':details}})
    async def authorize(authorization:str|None=Header(default=None)):
        if settings.api_token:
            expected='Bearer '+settings.api_token
            if not authorization or not hmac.compare_digest(authorization.encode(),expected.encode()):
                raise ApiFailure(401,'UNAUTHORIZED','A valid Bearer token is required')
    deps=[Depends(authorize)]
    @app.get('/health')
    def health():
        return {'status':'ok','version':__version__,'queue':manager.stats(),'server_check':'not_run','authentication_required':bool(settings.api_token)}
    @app.get('/api/v1/capabilities',dependencies=deps)
    def capabilities():
        return {'schema_version':'1.0','templates':[{'id':'rc_lowpass','label':'一阶 RC 低通','analyses':['ac','tran'],'devices':['analogLib/vpulse','analogLib/res','analogLib/cap','analogLib/gnd']}],
                'defaults':TaskSpec(r_ohm=1000,c_f=1e-7).model_dump(),
                'question_input':{'text_parser':'bounded_rules','ai_agent':'Codex Skill reads the question and submits a validated TaskSpec','image_upload':False},
                'artifacts':['schematic_window.png','waveform_window.png','schematic_native.png','waveform_native.png','input.scs','metrics.json','report.html','report.md'],
                'limits':{'max_queued':20,'single_worker':True,'arbitrary_skill_execution':False,'supports_cancellation':False},
                'stages':['upload','preflight','build','probe','netlist','netlist_validation','spectre','export','capture','download','image_validation','validation','report']}
    @app.post('/api/v1/parse',response_model=ParseResponse,dependencies=deps)
    def parse(body:ParseRequest):return parse_question(body.text)
    @app.post('/api/v1/runs',response_model=RunResult,status_code=202,dependencies=deps)
    def submit(body:TaskSpec):
        if manager.stats()['queued']>=20:raise ApiFailure(429,'QUEUE_FULL','Queue is full; retry after a current run completes')
        try:return manager.submit(body)
        except RuntimeError as exc:raise ApiFailure(503,'SHUTTING_DOWN',str(exc)) from exc
    @app.get('/api/v1/runs',response_model=RunList,dependencies=deps)
    def runs(limit:int=Query(default=50,ge=1,le=200)):return {'runs':manager.list(limit)}
    @app.get('/api/v1/runs/{run_id}',response_model=RunResult,dependencies=deps)
    def run(run_id:str):
        result=manager.get(run_id)
        if result is None:raise ApiFailure(404,'RUN_NOT_FOUND','No such run')
        return result
    @app.get('/api/v1/runs/{run_id}/artifacts/{artifact_id}',dependencies=deps)
    def artifact(run_id:str,artifact_id:str,download:bool=False):
        item=manager.artifact_path(run_id,artifact_id)
        if not item:raise ApiFailure(404,'ARTIFACT_NOT_FOUND','No such artifact')
        path,meta=item
        headers={'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'}
        if meta.media_type=='text/html':headers['Content-Security-Policy']="default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
        return FileResponse(path,media_type=meta.media_type,filename=path.name,
                            content_disposition_type='attachment' if download else 'inline',headers=headers)
    return app
