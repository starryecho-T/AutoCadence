from __future__ import annotations
import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Pulse(StrictModel):
    low_v: float = Field(default=0, ge=-10, le=10)
    high_v: float = Field(default=1, ge=-10, le=10)
    period_s: float = Field(default=.002, ge=1e-5, le=.1)
    width_s: float = Field(default=.001, gt=0, le=.1)
    rise_s: float = Field(default=1e-9, ge=1e-10, le=.001)
    fall_s: float = Field(default=1e-9, ge=1e-10, le=.001)
    delay_s: float = Field(default=1e-6, ge=0, le=.01)
    @model_validator(mode='after')
    def timing(self):
        if self.high_v <= self.low_v:
            raise ValueError('high_v must exceed low_v')
        if self.rise_s + self.width_s + self.fall_s >= self.period_s:
            raise ValueError('rise + width + fall must be less than period')
        return self

class AC(StrictModel):
    start_hz: float = Field(default=10, gt=0, le=1e8)
    stop_hz: float = Field(default=1e6, gt=0, le=1e9)
    points_per_decade: int = Field(default=50, ge=20, le=100)

class Transient(StrictModel):
    stop_s: float = Field(default=.004201, gt=0, le=.5)
    max_step_s: float = Field(default=1e-6, ge=1e-9, le=.001)

class TaskSpec(StrictModel):
    schema_version: Literal['1.0'] = '1.0'
    template_id: Literal['rc_lowpass'] = 'rc_lowpass'
    title: str = Field(default='RC low-pass simulation', max_length=120)
    question: str | None = Field(default=None, max_length=10000)
    r_ohm: float = Field(ge=10, le=1e6)
    c_f: float = Field(ge=1e-12, le=1e-3)
    pulse: Pulse = Field(default_factory=Pulse)
    ac: AC = Field(default_factory=AC)
    transient: Transient = Field(default_factory=Transient)
    @model_validator(mode='after')
    def analysis_coverage(self):
        tau = self.r_ohm * self.c_f
        fc = 1 / (2 * math.pi * tau)
        if not (self.ac.start_hz <= fc / 5 and self.ac.stop_hz >= fc * 5):
            raise ValueError('AC range must bracket theoretical cutoff by at least 5x each side')
        if math.log10(self.ac.stop_hz/self.ac.start_hz)*self.ac.points_per_decade > 1500:
            raise ValueError('AC point budget exceeded')
        if self.transient.stop_s < self.pulse.delay_s + 2.05*self.pulse.period_s:
            raise ValueError('transient must cover at least 2.05 pulse periods after delay')
        if self.transient.max_step_s > min(tau/20,self.pulse.period_s/200,self.pulse.width_s/20):
            raise ValueError('max_step_s too large for RC or pulse timing')
        if self.transient.stop_s/self.transient.max_step_s > 60000:
            raise ValueError('transient point budget exceeded')
        return self

class ParseRequest(StrictModel):
    text: str = Field(min_length=1,max_length=10000)

class Stage(StrictModel):
    name: str
    status: Literal['pending','running','succeeded','failed']
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_s: float | None = None
    exit_code: int | None = None
    log_path: str | None = None
    message: str | None = None

class Artifact(StrictModel):
    id: str
    kind: str
    filename: str
    media_type: str
    bytes: int
    sha256: str
    url: str

class RunError(StrictModel):
    code: str
    stage: str
    message: str

from .circuit_models import CircuitTask


class RunResult(StrictModel):
    schema_version: Literal['1.0'] = '1.0'
    run_id: str
    status: Literal['queued','running','succeeded','failed']
    created_at: str
    updated_at: str
    task: TaskSpec | CircuitTask
    stages: list[Stage] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: RunError | None = None
