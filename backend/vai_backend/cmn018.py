"""Allowlisted direct CMN018 Spectre models; the proprietary deck is server-local."""

MODEL_PLACEHOLDER = '@CMN018_MODEL_FILE@'
MODEL_FILENAME = 'cmn018_gp2a_5v_v1d4.scs'

# (device type, corner section suffix, minimum L, minimum W, maximum L, maximum W)
# MOS geometry values are metres, from the model card's supported-range table.
CMN018_MODELS = {
    'nch': ('nmos', '', .18e-6, .22e-6, 20e-6, 900e-6),
    'pch': ('pmos', '', .18e-6, .22e-6, 20e-6, 900e-6),
    'nch_5': ('nmos', '_5', .6e-6, .22e-6, 900e-6, 900e-6),
    'pch_5': ('pmos', '_5', .5e-6, .22e-6, 900e-6, 900e-6),
    'mench': ('nmos', '_m', .3e-6, .22e-6, 20e-6, 900e-6),
    'mepch': ('pmos', '_m', .25e-6, .22e-6, 20e-6, 900e-6),
    'mench5': ('nmos', '_5m', .8e-6, .22e-6, 900e-6, 900e-6),
    'mepch5': ('pmos', '_5m', .8e-6, .22e-6, 900e-6, 900e-6),
    'nanch': ('nmos', '_na', .5e-6, .22e-6, 20e-6, 900e-6),
    'nanch5': ('nmos', '_5vna', 1.6e-6, 1.2e-6, 900e-6, 900e-6),
    **{name: ('bjt', '_bip', None, None, None, None)
       for name in ('npn2', 'npn5', 'npn10', 'pnp2', 'pnp5', 'pnp10')},
    **{name: ('bjt', '_bip5_rpo', None, None, None, None)
       for name in ('npn2_5_rpo', 'npn5_5_rpo', 'npn10_5_rpo',
                    'pnp2_5_rpo', 'pnp5_5_rpo', 'pnp10_5_rpo')},
    **{name: ('diode', '_dio', None, None, None, None)
       for name in ('ndio', 'pdio', 'nwdio')},
    **{name: ('diode', '_dio_5', None, None, None, None)
       for name in ('ndio_5', 'pdio_5', 'nwdio_5')},
    **{name: ('diode', '_dio_m', None, None, None, None)
       for name in ('ndio_m', 'pdio_m')},
    **{name: ('diode', '_dio_5m', None, None, None, None)
       for name in ('ndio_5m', 'pdio_5m')},
    **{name: ('diode', '_dio_dnw', None, None, None, None)
       for name in ('dnwpsub', 'pwdnw')},
    'pwdnw_5': ('diode', '_dio_dnw_5', None, None, None, None),
}

MISMATCH_FLAGS = {
    '': 'mismatchflag_mos', '_5': 'mismatchflag_mos_5',
    '_m': 'mismatchflag_mos_m', '_5m': 'mismatchflag_mos_5m',
    '_na': 'mismatchflag_mos_na', '_5vna': 'mismatchflag_mos_na5',
    '_bip': 'mismatchflag_bip', '_bip5_rpo': 'mismatchflag_bip5_rpo',
}


def section(corner, name):
    return corner + CMN018_MODELS[name][1]
