"""Topology-aware placement for grounded ladders and closed loops."""


def ladder_layout(devices):
    """Recognize a grounded resistor rail with shunts and one switched load.

    Return anchor coordinates for *actual* device pins. Unrecognized circuits
    keep the existing general-purpose layout rather than guessing topology.
    """
    if not 4 <= len(devices) <= 30:
        return None
    if any(len(d['nodes']) != len(d['terminals']) for d in devices):
        return None
    allowed = {'resistor', 'capacitor', 'voltage_source', 'switch'}
    if any(d['type'] not in allowed for d in devices):
        return None
    switches = [i for i, d in enumerate(devices) if d['type'] == 'switch']
    if len(switches) > 1:
        return None
    graph = {}
    for i, d in enumerate(devices):
        if d['type'] == 'resistor' and len(d['nodes']) == 2 and '0' not in d['nodes']:
            a, b = d['nodes']
            graph.setdefault(a, []).append((b, i))
            graph.setdefault(b, []).append((a, i))
    if any(len(edges) > 3 for edges in graph.values()):
        return None
    direct = {}
    for i, d in enumerate(devices):
        if d['type'] in ('resistor', 'capacitor') and len(d['nodes']) == 2 and '0' in d['nodes']:
            other = next((n for n in d['nodes'] if n != '0'), None)
            if other:
                direct.setdefault(other, []).append(i)

    def candidate(source_index, nodes, edges):
        if len(edges) < 2 or nodes[-1] not in direct:
            return None
        control_inner = devices[switches[0]]['nodes'][0] if switches else None
        if any(neighbor not in nodes and neighbor != control_inner
               for neighbor, _ in graph.get(nodes[-1], [])):
            return None
        trunk = set(nodes)
        assigned = set(edges) | {source_index}
        shunts = {n: sorted(direct.get(n, [])) for n in nodes}
        assigned.update(i for ids in shunts.values() for i in ids)
        if shunts[nodes[0]]:
            return None  # keep the left-hand source branch unobstructed
        series = {}
        control = None
        if switches:
            si = switches[0]
            sw = devices[si]
            if len(sw['nodes']) != 4 or sw['nodes'][1] != '0' or sw['nodes'][3] != '0':
                return None
            inner, clock = sw['nodes'][0], sw['nodes'][2]
            if inner in trunk or clock in trunk or inner == clock:
                return None
            branches = [i for i, d in enumerate(devices)
                        if i not in assigned and d['type'] == 'resistor' and
                        len(d['nodes']) == 2 and inner in d['nodes'] and
                        any(n in trunk for n in d['nodes'])]
            drivers = [i for i, d in enumerate(devices)
                       if i != source_index and d['type'] == 'voltage_source' and
                       d['nodes'] == [clock, '0']]
            if len(branches) != 1 or len(drivers) != 1:
                return None
            bi = branches[0]
            tap = next(n for n in devices[bi]['nodes'] if n in trunk)
            series[tap] = (bi, si)
            control = drivers[0]
            assigned.update((bi, si, control))
        if assigned != set(range(len(devices))):
            return None
        return nodes, edges, shunts, series, control

    choices = []
    for source_index, source in enumerate(devices):
        if source['type'] != 'voltage_source' or len(source['nodes']) != 2 or source['nodes'][1] != '0':
            continue
        start = source['nodes'][0]

        def walk(node, nodes, edges):
            hit = candidate(source_index, nodes, edges)
            if hit:
                choices.append((len(edges), sum(len(x) for x in hit[2].values()),
                                -source_index, hit, source_index))
            if len(edges) >= 12:
                return
            for nxt, index in sorted(graph.get(node, []), key=lambda x: x[1]):
                if nxt not in nodes:
                    walk(nxt, nodes + [nxt], edges + [index])

        walk(start, [start], [])
    if not choices:
        return None
    _, _, _, (nodes, edges, shunts, series, control), source = max(choices, key=lambda x: x[:3])
    top, bottom = 3.5, 0.0
    placements = {source: ((0.0, top), (0.0, bottom))}
    segments = []
    taps = {}
    cursor = 0.0
    for j, index in enumerate(edges):
        left = cursor + (0.75 if j == 0 else 0.5)
        right = left + 1.0
        a, b = devices[index]['nodes']
        p, n = ((left, top), (right, top)) if (a, b) == (nodes[j], nodes[j+1]) else ((right, top), (left, top))
        placements[index] = (p, n)
        segments.append((nodes[j], cursor, left))
        branch_count = len(shunts[nodes[j+1]]) + int(nodes[j+1] in series)
        end = right + max(2.0, 1.0 + 1.25 * branch_count)
        taps[nodes[j+1]] = [right + 0.75 + k*1.25 for k in range(branch_count)]
        rail_end = taps[nodes[j+1]][-1] + 0.35 if j == len(edges)-1 else end
        segments.append((nodes[j+1], right, rail_end))
        cursor = end
    switched = None
    for node in nodes:
        slots = iter(taps.get(node, []))
        for index in shunts[node]:
            x = next(slots)
            pair = devices[index]['nodes']
            p, n = ((x, top), (x, bottom)) if pair[0] == node else ((x, bottom), (x, top))
            placements[index] = (p, n)
        if node in series:
            ri, si = series[node]
            x = next(slots)
            pair = devices[ri]['nodes']
            p, n = ((x, top), (x, 2.0)) if pair[0] == node else ((x, 2.0), (x, top))
            placements[ri] = (p, n)
            placements[si] = ((x, 2.0), (x, bottom))
            switched = (si, x)
    if control is not None:
        control_x = cursor + 2.0
        placements[control] = ((control_x, 2.5), (control_x, bottom))
        cursor = control_x
    # Every series resistor's terminals are anchored to adjacent, labelled
    # rail sections; a branch is never inferred from component input order.
    return {'placements': placements, 'segments': segments, 'ground_end': cursor,
            'switch': switched, 'control': control, 'source': source, 'nodes': nodes}


def loop_layout(devices):
    if not 3 <= len(devices) <= 16 or any(len(d['nodes']) != 2 for d in devices):
        return None
    adjacent = {}
    for i, d in enumerate(devices):
        for node in d['nodes']:
            adjacent.setdefault(node, []).append(i)
    if '0' not in adjacent or any(len(edges) != 2 for edges in adjacent.values()):
        return None
    first = next((i for i in adjacent['0'] if devices[i]['type'] in ('voltage_source', 'current_source')), adjacent['0'][0])
    order, current, used = [], '0', set()
    edge = first
    while edge not in used:
        used.add(edge)
        nxt = next((n for n in devices[edge]['nodes'] if n != current), None)
        if nxt is None:
            return None
        order.append((edge, current, nxt))
        current = nxt
        edge = next((i for i in adjacent[current] if i not in used), first)
    if len(used) != len(devices) or current != '0':
        return None
    result = {}
    for j, (index, start, end) in enumerate(order):
        if j == 0:
            a, b = (0, 0), (0, 2)
        elif j == len(order) - 1:
            a, b = ((j-1)*2.5, 2), ((j-1)*2.5, 0)
        else:
            a, b = ((j-1)*2.5, 2), (j*2.5, 2)
        d = devices[index]
        result[index] = (a, b) if d['nodes'][0] == start else (b, a)
    return {'devices': result, 'width': (len(order)-2)*2.5}
