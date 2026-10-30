"""Reviewable explicit topologies, used by the UI and real regression runner."""
import json
EXAMPLES = {
    'switch_10mhz': ('10 MHz 受控开关与电源去耦', '''V0 supply 0 DC 5
R1 supply A 10
R2 A B 10
Ra A 0 1k
Rd1 B 0 990
Radd B switched 99
S1 switched 0 clock 0 0.2 0.8 1e12 1m
VCLK clock 0 PULSE 0 1 1n 100p 100p 49.9n 100n
C1 A 0 27n
.tran 10u 200p
.save V(A) V(B)'''),
    'bjt_transfer': ('NPN 共射转移曲线与工作区', '''VIN input 0 DC 0
VCC supply 0 DC 5
RB input base 1k
RC supply out 10k
Q1 out base 0 generic_npn
.dc VIN 0 1.2 0.005
.save V(out) I(Q1,c) I(Q1,b)
.transfer Q1 VIN VCC RB RC'''),
    'pnp_bias': ('PNP 工作点', '''VCC supply 0 DC 5
VB base 0 DC 4.3
RC out 0 1k
Q1 out base supply generic_pnp
.op
.save V(out) I(Q1,c) P(Q1,gm) P(Q1,region)'''),
    'pmos_families': ('PMOS 输出特性与栅压扫描', '''VG gate 0 DC -2
VD drain 0 DC 0
M1 drain gate 0 0 generic_pmos w=10u l=1u
.dc VD 0 -5 -0.05
.step VG dc -1 -1.5 -2 -2.5
.save I(M1,d) I(M1,g) P(M1,region)'''),
    'pmos_ground_reference': ('PMOS 接 VDD 的输出特性', '''VDD source 0 DC 5
VG gate 0 DC 3
VD drain 0 DC 5
M1 drain gate source source generic_pmos w=10u l=1u
.dc VD 5 0 -0.05
.step VG dc 4 3.5 3 2.5
.save I(M1,d) I(M1,g) P(M1,region)'''),
    'nmos_families': ('NMOS 输出特性与栅压扫描', '''VG gate 0 DC 1.5
VD drain 0 DC 0
M1 drain gate 0 0 generic_nmos w=10u l=1u
.dc VD 0 5 0.05
.step VG dc 1 1.5 2
.save I(M1,d) I(M1,g) P(M1,region)'''),
    'nmos_id_vgs': ('NMOS 共源栅压扫描与漏极电流', json.dumps({
        'components':[
            {'id':'VDD','type':'voltage_source','pins':{'p':'drain','n':'0'},'dc':3.3},
            {'id':'VG','type':'voltage_source','pins':{'p':'gate','n':'0'},'dc':0},
            {'id':'M1','type':'nmos','pins':{'d':'drain','g':'gate','s':'0','b':'0'},'model':'generic_nmos','width_m':10e-6,'length_m':1e-6},
        ],
        'analyses':[{'type':'dc','source':'VG','start':0,'stop':3.3,'step':0.05}],
        'signals':[
            {'id':'id','type':'current','component':'M1','terminal':'d'},
            {'id':'vgs','type':'device_parameter','component':'M1','parameter':'vgs'},
            {'id':'region','type':'device_parameter','component':'M1','parameter':'region'},
        ],
        'measurements':[{'id':'id_max','analysis':'dc','signal':'id','operation':'max'}],
    },ensure_ascii=False,indent=2)),
    'controlled_sources': ('四种线性受控源', '''V1 input 0 DC 1 AC 1
Rin input sense 1k
VS sense 0 DC 0
E1 ev 0 input 0 2
RE ev 0 1k
G1 gi 0 input 0 0.001
RG gi 0 1k
F1 fi 0 VS 3
RF fi 0 1k
H1 hv 0 VS 2k
RH hv 0 1k
.op
.ac 10 100k 10
.save V(ev) V(gi) V(fi) V(hv) I(VS)'''),
    'common_base_y': ('共基极小信号模型：Y 参数与等效验证', '''VE emitter 0 DC 0 AC 1
VC collector 0 DC 0
RBE emitter 0 1k
RCE emitter collector 100k
GM emitter collector emitter 0 0.04
.ac 10 100k 10
.save I(VE) I(VC)
.twoport VE VC 1k'''),
    'bjt_biased_y': ('有偏置 BJT：小信号二端口等效', '''VE emitter 0 DC -0.65 AC 1
VC collector 0 DC 5
Q1 collector 0 emitter generic_npn
.ac 10 100k 10
.save I(VE) I(VC)
.twoport VE VC 1k'''),
    'parameter_comparison': ('参数扫描与跨组曲线比较', '''V1 input 0 DC 10
R1 input out 1k
R2 out 0 1k
.dc V1 0 10 0.1
.step R1 resistance_ohm 1k 2k
.save V(out)
.compare repeat dc s1 s1 base s000 0.0001 1n'''),
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
