"""Topology-based supply rail drawing remains tied to actual pin connectivity."""
from vai_backend.circuit_compiler import scripts
from vai_backend.circuit_examples import EXAMPLES
from vai_backend.circuit_parsing import parse_circuit
from vai_backend.circuits import compile_task
from vai_backend.schematic_layout import ladder_layout


def design(capacitors):
    base = EXAMPLES['switch_10mhz'][1]
    return parse_circuit(base.replace('R2 A B 10', 'R2a A M 5\nR2b M B 5')
                         .replace('C1 A 0 27n', capacitors))


def test_ladder_recognizes_real_capacitor_positions():
    for description, count in (
        ('C1 A 0 27n', 1),
        ('C1 B 0 27n', 1),
        ('C1 A 0 13.5n\nC2 B 0 13.5n', 2),
        ('C1 A 0 9n\nC2 M 0 9n\nC3 B 0 9n', 3),
    ):
        task = design(description)
        compiled = compile_task(task)
        layout = ladder_layout(compiled['devices'])
        assert layout is not None
        assert len(layout['placements']) == len(compiled['devices'])
        assert layout['nodes'][0] == compiled['devices'][0]['nodes'][0]
        assert len([d for d in compiled['devices'] if d['type'] == 'capacitor']) == count
        for i, device in enumerate(compiled['devices']):
            if device['type'] == 'capacitor':
                p, n = layout['placements'][i]
                assert p[1] == 3.5 and n[1] == 0.0
                assert device['nodes'][0] in layout['nodes']
                assert any(node == device['nodes'][0] and x0 < p[0] < x1
                           for node, x0, x1 in layout['segments'])
        program = scripts(task)
        assert 'PROBE_RESULT=PASS' in program['probe.il']
        assert 'gBetween(cv master' in program['build.il']

    four = parse_circuit(EXAMPLES['switch_10mhz'][1]
                         .replace('R1 supply A 10', 'R1a supply U 5\nR1b U A 5')
                         .replace('R2 A B 10', 'R2a A M 5\nR2b M B 5')
                         .replace('C1 A 0 27n',
                                  'C1 U 0 6.75n\nC2 A 0 6.75n\nC3 M 0 6.75n\nC4 B 0 6.75n'))
    layout = ladder_layout(compile_task(four)['devices'])
    assert layout is not None and len(layout['nodes']) == 5
    assert len(layout['placements']) == len(compile_task(four)['devices'])


def test_unrecognized_topology_keeps_existing_layout():
    task = parse_circuit(EXAMPLES['bjt_transfer'][1])
    assert ladder_layout(compile_task(task)['devices']) is None
    assert 'BUILD_PASSED' in scripts(task)['build.il']


def test_ladder_does_not_depend_on_input_component_order():
    original = EXAMPLES['switch_10mhz'][1].splitlines()
    shuffled = '\n'.join(list(reversed(original[:-2])) + original[-2:])
    task = parse_circuit(shuffled)
    compiled = compile_task(task)
    layout = ladder_layout(compiled['devices'])
    assert layout is not None
    assert len(layout['placements']) == len(compiled['devices'])
    assert layout['nodes'][0] == next(d['nodes'][0] for d in compiled['devices']
                                       if d['id'] == 'V0')
    assert 'PROBE_RESULT=PASS' in scripts(task)['probe.il']
