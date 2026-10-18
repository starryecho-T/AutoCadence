"""Compact closed-loop placement for two-terminal circuits."""
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
