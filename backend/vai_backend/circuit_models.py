"""Strict v2 circuit contract. All quantities use SI units; no executable input."""
from __future__ import annotations

import math
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Name = Annotated[str, Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,31}$')]
Node = Annotated[str, Field(pattern=r'^(?:0|[A-Za-z][A-Za-z0-9_]{0,31})$')]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Pins(Strict):
    p: Node
    n: Node


class Part(Strict):
    id: Name
    pins: Pins


class Resistor(Part):
    type: Literal['resistor']
    resistance_ohm: float = Field(gt=0, le=1e15)


class Capacitor(Part):
    type: Literal['capacitor']
    capacitance_f: float = Field(gt=0, le=1e3)
    initial_voltage_v: float | None = Field(default=None, ge=-1e6, le=1e6)


class Inductor(Part):
    type: Literal['inductor']
    inductance_h: float = Field(gt=0, le=1e9)
    initial_current_a: float | None = Field(default=None, ge=-1e6, le=1e6)


class DiodePins(Strict):
    a: Node
    k: Node


class Diode(Strict):
    id: Name
    type: Literal['diode']
    pins: DiodePins
    model: Name = 'generic_diode'


class OpampPins(Strict):
    plus: Node
    minus: Node
    out: Node


class Opamp(Strict):
    id: Name
    type: Literal['ideal_opamp']
    pins: OpampPins


class Wire(Part):
    type: Literal['wire']


class Sine(Strict):
    type: Literal['sine']
    offset: float = Field(default=0, ge=-1e6, le=1e6)
    amplitude: float = Field(gt=0, le=1e6)
    frequency_hz: float = Field(gt=0, le=1e12)
    phase_deg: float = Field(default=0, ge=-360, le=360)
    delay_s: float = Field(default=0, ge=0, le=1e6)


class Pulse(Strict):
    type: Literal['pulse']
    low: float = Field(default=0, ge=-1e6, le=1e6)
    high: float = Field(ge=-1e6, le=1e6)
    period_s: float = Field(gt=0, le=1e6)
    width_s: float = Field(gt=0, le=1e6)
    rise_s: float = Field(gt=0, le=1e6)
    fall_s: float = Field(gt=0, le=1e6)
    delay_s: float = Field(default=0, ge=0, le=1e6)

    @model_validator(mode='after')
    def timing(self):
        if self.rise_s + self.width_s + self.fall_s >= self.period_s:
            raise ValueError('pulse rise + width + fall must be less than period')
        return self


class Pwl(Strict):
    type: Literal['pwl']
    points: list[tuple[float, float]] = Field(min_length=2, max_length=50)

    @model_validator(mode='after')
    def ordered(self):
        if self.points[0][0] != 0 or any(t < 0 or t > 1e6 or abs(v) > 1e6 for t, v in self.points):
            raise ValueError('PWL must start at t=0 and use bounded SI values')
        if any(a[0] >= b[0] for a, b in zip(self.points, self.points[1:])):
            raise ValueError('PWL times must strictly increase')
        return self


class Source(Part):
    type: Literal['voltage_source', 'current_source']
    dc: float = Field(default=0, ge=-1e6, le=1e6)
    ac_magnitude: float = Field(default=0, ge=0, le=1e6)
    ac_phase_deg: float = Field(default=0, ge=-360, le=360)
    waveform: Annotated[Sine | Pulse | Pwl, Field(discriminator='type')] | None = None


Component = Annotated[Resistor | Capacitor | Inductor | Diode | Opamp | Wire | Source, Field(discriminator='type')]


class DiodeModel(Strict):
    id: Name
    saturation_current_a: float = Field(default=1e-14, gt=0, le=1)
    emission_coefficient: float = Field(default=1, ge=.1, le=10)
    series_resistance_ohm: float = Field(default=0, ge=0, le=1e9)
    junction_capacitance_f: float = Field(default=0, ge=0, le=1)
    transit_time_s: float = Field(default=0, ge=0, le=1)
    breakdown_voltage_v: float | None = Field(default=None, gt=0, le=1e6)


class OP(Strict):
    type: Literal['op']


class DC(Strict):
    type: Literal['dc']
    source: Name
    start: float = Field(ge=-1e6, le=1e6)
    stop: float = Field(ge=-1e6, le=1e6)
    step: float

    @model_validator(mode='after')
    def sweep(self):
        if self.step == 0 or (self.stop-self.start)*self.step <= 0:
            raise ValueError('DC step must point from start toward stop')
        if abs((self.stop-self.start)/self.step) > 10000:
            raise ValueError('DC point budget exceeded (10000)')
        steps = (self.stop-self.start)/self.step
        if not math.isclose(steps, round(steps), rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError('DC range must contain an integer number of steps')
        return self


class AC(Strict):
    type: Literal['ac']
    start_hz: float = Field(gt=0, le=1e12)
    stop_hz: float = Field(gt=0, le=1e12)
    points_per_decade: int = Field(default=50, ge=2, le=200)

    @model_validator(mode='after')
    def sweep(self):
        if self.stop_hz <= self.start_hz:
            raise ValueError('AC stop must exceed start')
        if math.log10(self.stop_hz/self.start_hz)*self.points_per_decade > 10000:
            raise ValueError('AC point budget exceeded (10000)')
        return self


class TRAN(Strict):
    type: Literal['tran']
    stop_s: float = Field(gt=0, le=1e6)
    max_step_s: float = Field(gt=0, le=1e6)
    use_initial_conditions: bool = False
    initial_condition_resistance_ohm: float = Field(default=1e-3, gt=0, le=1,
        description='Spectre rforce during the initial-condition solve only; not a physical circuit resistor.')

    @model_validator(mode='after')
    def budget(self):
        if self.max_step_s > self.stop_s or self.stop_s/self.max_step_s > 200000:
            raise ValueError('transient step must not exceed stop; point budget is 200000')
        return self


Analysis = Annotated[OP | DC | AC | TRAN, Field(discriminator='type')]


class Voltage(Strict):
    id: Name
    type: Literal['voltage']
    p: Node
    n: Node = '0'


class Current(Strict):
    id: Name
    type: Literal['current']
    component: Name


Signal = Annotated[Voltage | Current, Field(discriminator='type')]


class Measurement(Strict):
    id: Name
    analysis: Literal['op', 'dc', 'ac', 'tran']
    signal: Name
    operation: Literal['final', 'min', 'max', 'mean', 'rms', 'peak_to_peak', 'at']
    representation: Literal['real', 'imag', 'magnitude', 'phase_deg'] = 'real'
    at: float | None = None
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode='after')
    def bounds(self):
        if (self.operation == 'at') != (self.at is not None):
            raise ValueError('at is required only for operation=at')
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError('measurement minimum exceeds maximum')
        return self


class CircuitTask(Strict):
    schema_version: Literal['2.0'] = '2.0'
    template_id: Literal['general_circuit'] = 'general_circuit'
    title: str = Field(default='通用电路仿真', max_length=120)
    question: str | None = Field(default=None, max_length=50000)
    components: list[Component] = Field(min_length=1, max_length=100)
    models: list[DiodeModel] = Field(default_factory=list, max_length=30)
    analyses: list[Analysis] = Field(min_length=1, max_length=4)
    signals: list[Signal] = Field(min_length=1, max_length=16)
    measurements: list[Measurement] = Field(default_factory=list, max_length=100)
    temperature_c: float = Field(default=27, ge=-100, le=200)

    @model_validator(mode='after')
    def references(self):
        for label, items in [('component', self.components), ('model', self.models), ('signal', self.signals), ('measurement', self.measurements)]:
            ids = [x.id.lower() for x in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f'duplicate {label} id (case insensitive)')
        kinds = [a.type for a in self.analyses]
        if len(kinds) != len(set(kinds)):
            raise ValueError('only one analysis of each type is allowed')
        parts = {c.id: c for c in self.components}
        model_ids = {'generic_diode'} | {m.id for m in self.models}
        nodes = {n for c in self.components for n in c.pins.model_dump().values()}
        if len({n.lower() for n in nodes}) != len(nodes):
            raise ValueError('node names differing only by case are ambiguous')
        for c in self.components:
            if c.type == 'diode' and c.model not in model_ids:
                raise ValueError(f'{c.id}: unknown diode model {c.model}')
        for a in self.analyses:
            if a.type == 'dc' and (a.source not in parts or parts[a.source].type not in ('voltage_source', 'current_source')):
                raise ValueError('DC sweep must reference an independent source')
        if 'ac' in kinds and not any(c.type in ('voltage_source', 'current_source') and c.ac_magnitude > 0 for c in self.components):
            raise ValueError('AC requires at least one source with ac_magnitude > 0')
        for s in self.signals:
            if s.type == 'voltage' and any(n not in nodes and n != '0' for n in (s.p, s.n)):
                raise ValueError(f'{s.id}: unknown voltage node')
            if s.type == 'current' and (s.component not in parts or parts[s.component].type in ('wire', 'ideal_opamp')):
                raise ValueError(f'{s.id}: current must reference a two-terminal component, not a wire or opamp')
        signals = {s.id for s in self.signals}
        for m in self.measurements:
            if m.analysis not in kinds or m.signal not in signals:
                raise ValueError(f'{m.id}: unknown analysis or signal')
            if m.analysis != 'ac' and m.representation in ('imag', 'phase_deg'):
                raise ValueError('imaginary/phase measurements require AC')
            if m.operation == 'at':
                a = next(a for a in self.analyses if a.type == m.analysis)
                lo,hi = (a.start_hz,a.stop_hz) if a.type == 'ac' else (0,a.stop_s) if a.type == 'tran' else (min(a.start,a.stop),max(a.start,a.stop)) if a.type == 'dc' else (0,0)
                if not lo <= m.at <= hi:
                    raise ValueError(f'{m.id}: measurement coordinate outside analysis range')
        from .circuits import normalize
        normalize(self)  # deterministic topology checks before anything is queued
        return self
