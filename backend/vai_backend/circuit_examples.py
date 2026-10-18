"""Reviewable explicit topologies, used by the UI and real regression runner."""
import json
EXAMPLES = {
    'divider': ('电阻分压与导线', '''V1 vin 0 DC 10
R1 vin mid 1k
W1 mid out
R2 out 0 1k
.op
.save V(out) I(R1)'''),
    'divider_dc': ('工作点与反向直流扫描', '''V1 vin 0 DC 10
R1 vin out 1k
R2 out 0 1k
.op
.dc V1 10 0 -1
.save V(out) I(R1)'''),
    'rc_highpass': ('RC 高通', '''V1 vin 0 PULSE 0 1 1u 1u 1u 1m 2m AC 1
C1 vin out 100n
R1 out 0 1k
.ac 10 1meg 50
.tran 5m 1u
.save V(vin) V(out) I(C1)'''),
    'rlc': ('串联 RLC', '''V1 vin 0 SINE 0 1 1000 AC 1
R1 vin a 100
L1 a out 10m
C1 out 0 1u
.ac 10 100k 60
.tran 10m 2u
.save V(out) I(L1)'''),
    'rectifier': ('二极管半波整流', '''V1 vin 0 SINE 0 5 50
D1 vin out
R1 out 0 1k
C1 out 0 100u
.tran 200m 20u
.save V(vin) V(out) I(D1)'''),
    'inverting': ('理想运放反相放大', '''V1 vin 0 SINE 0 1 1000 AC 1
R1 vin feedback 10k
R2 feedback out 20k
U1 0 feedback out
.op
.ac 10 100k 30
.tran 4m 1u
.save V(vin) V(out) V(feedback)'''),
    'diode_iv': ('二极管直流扫描', '''V1 vin 0 DC 0
R1 vin a 100
D1 a 0
.dc V1 -1 1 0.01
.save V(a) I(D1)'''),
    'current_rl': ('电流源与 RL', '''I1 0 vin PULSE 0 0.01 1u 1u 1u 1m 2m
R1 vin 0 100
L1 vin 0 10m
.tran 5m 1u
.save V(vin) I(L1) I(I1)'''),
    'rl_initial': ('电感初始电流', '''R1 out 0 100
L1 out 0 10m ic=0.01
.tran 1m 1u ic
.save V(out) I(L1)'''),
    'floating_cap': ('浮置电容初始电压', '''R1 a 0 1k
R2 b 0 1k
C1 a b 1u ic=1
.tran 20m 10u ic
.save V(a,b) V(a) V(b)'''),
    'pwl_cap': ('分段线性电源与电容初始电压', json.dumps({
        'title':'PWL 与电容初始条件',
        'components':[
            {'id':'V1','type':'voltage_source','pins':{'p':'vin','n':'0'},'waveform':{'type':'pwl','points':[[0,0],[.001,1],[.002,0],[.004,0]]}},
            {'id':'R1','type':'resistor','pins':{'p':'vin','n':'out'},'resistance_ohm':1000},
            {'id':'C1','type':'capacitor','pins':{'p':'out','n':'0'},'capacitance_f':1e-6,'initial_voltage_v':1},
        ],
        'analyses':[{'type':'tran','stop_s':.004,'max_step_s':1e-6,'use_initial_conditions':True}],
        'signals':[{'id':'output','type':'voltage','p':'out'},{'id':'current','type':'current','component':'C1'}],
    },ensure_ascii=False,indent=2)),
}
