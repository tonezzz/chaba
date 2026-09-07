# TPL variant-card generator — single source of truth for *.a1 / *.b1 cards.
#
# Each base card in SPEC gets two generated siblings:
#   <Title>.a1 — vertical bars   (bars chart, orientation:'vertical')
#   <Title>.b1 — horizontal bars (bars chart, default orientation)
# Both share: base image, device-name label at top, bars in the bottom strip
# (55% height), 24h history as 'bg' layer (bottom 50%, opacity 0.8, scrim).
#
# The TPL grid is 12 columns; every row is  base(4) | .a1(4) | .b1(4).
#
# Usage (idempotent — variants are dropped and rebuilt from this spec):
#   set -a && . ~/.config/secrets/ha-michael-dev.env && set +a
#   python3 scripts/home-assistant/push-dashboard.py \
#       https://tony-dell.taila0626a.ts.net:8124 tony-test \
#       --mutate scripts/home-assistant/tpl-variants.py
#   ./scripts/home-assistant/sync-ssot-from-live.sh
#
# To add/change a card's series: edit SPEC below, re-run.
# To restyle ALL variants (label pos, strip height, history opacity):
#   edit make_variant() once — every card inherits it.

K = 0.001  # W -> kW


def S(label, entity=None, mn=0, mx=100, scale=None, dec=0, unit='', segs=None):
    """Compact series definition."""
    d = {'label': label, 'min': mn, 'max': mx, 'decimals': dec}
    if entity:
        d['entity'] = entity
    if scale is not None:
        d['scale'] = scale
    if unit:
        d['unit'] = unit
    if segs:
        d['segments'] = [{'from': f, 'color': c} for f, c in segs]
    return d


def seg(*pairs):
    return list(pairs)


# Colour conventions:
#   yield metric   : red low -> amber -> green strong
#   band metric    : red outside operating window, green inside
#   bidirectional  : green export(<0) -> amber idle -> red heavy import
PV1 = [
    S('Power', 'sensor.inverters_1_pv_power_1', 0, 5000, K, 2, 'kW',
      seg((0, '#ff5252'), (1000, '#ffb300'), (3000, '#00E676'))),
    S('Voltage', 'sensor.inverters_1_pv_voltage_1', 0, 600, None, 0, 'V',
      seg((0, '#ff5252'), (150, '#ffb300'), (250, '#00E676'), (500, '#ff5252'))),
    S('Current', 'sensor.inverters_1_pv_current_1', 0, 30, None, 1, 'A',
      seg((0, '#ffb300'), (5, '#00E676'), (20, '#ff5252'))),
]
PV2 = [
    S('Power', 'sensor.inverters_1_pv_power_2', 0, 5000, K, 2, 'kW',
      seg((0, '#ff5252'), (1000, '#ffb300'), (3000, '#00E676'))),
    S('Voltage', 'sensor.inverters_1_pv_voltage_2', 0, 600, None, 0, 'V',
      seg((0, '#ff5252'), (150, '#ffb300'), (250, '#00E676'), (500, '#ff5252'))),
    S('Current', 'sensor.inverters_1_pv_current_2', 0, 30, None, 1, 'A',
      seg((0, '#ffb300'), (5, '#00E676'), (20, '#ff5252'))),
]
GRID = [
    S('Power', 'sensor.inverters_1_grid_power', -5000, 5000, K, 2, 'kW',
      seg((-5000, '#00E676'), (0, '#ffb300'), (2000, '#ff5252'))),
    S('Voltage', 'sensor.inverters_1_grid_voltage', 0, 300, None, 0, 'V',
      seg((0, '#ff5252'), (200, '#ffb300'), (220, '#00E676'), (260, '#ff5252'))),
    S('Freq', 'sensor.inverters_1_grid_frequency', 45, 55, None, 1, 'Hz',
      seg((45, '#ff5252'), (49, '#ffb300'), (49.8, '#00E676'), (50.3, '#ff5252'))),
]
ROOM_AIR = [  # tze200 multi-sensor — only room sensor on michael-dev (mock)
    S('Temp', 'sensor.tze200_mja3fuja_ts0601_temperature', 0, 40, None, 1, '°C',
      seg((0, '#4fc3f7'), (18, '#00E676'), (28, '#ff5252'))),
    S('Humidity', 'sensor.tze200_mja3fuja_ts0601_humidity', 0, 100, None, 0, '%',
      seg((0, '#ff5252'), (40, '#00E676'), (70, '#4fc3f7'))),
    S('CO2', 'sensor.tze200_mja3fuja_ts0601_carbon_dioxide', 400, 2000, None, 0, 'ppm',
      seg((400, '#00E676'), (1000, '#ffb300'), (1500, '#ff5252'))),
]
ROOM_AIR_VOC = ROOM_AIR[:2] + [
    S('VOC', 'sensor.tze200_mja3fuja_ts0601_volatile_organic_compounds', 0, 500, None, 0, '',
      seg((0, '#00E676'), (200, '#ffb300'), (350, '#ff5252'))),
]

# Row spec: (base title, device label, image, grid-area base, series, history entity)
# Rows 1-2 are special-cased (PV/Grid areas don't follow the <base>a/<base>b pattern).
SPEC = [
    ('Battery', 'Battery', '/local/battery-bank.jpg', 'battery', [
        S('Power', 'sensor.totals_battery_power', -10000, 10000, K, 2, 'kW',
          seg((-10000, '#4fc3f7'), (0, '#00E676'), (5000, '#ff5252'))),
        S('SOC', 'sensor.totals_battery_state_of_charge', 0, 100, None, 0, '%',
          seg((0, '#ff5252'), (20, '#ffb300'), (50, '#00E676'))),
        S('Voltage', 'sensor.totals_battery_voltage', 40, 60, None, 1, 'V',
          seg((40, '#ff5252'), (48, '#ffb300'), (50, '#00E676'), (56, '#ff5252'))),
    ], 'sensor.totals_battery_power'),
    ('Inverter', 'Inverter', '/local/inverter.webp', 'inverter', [
        S('Power', 'sensor.inverters_1_load_power', 0, 10000, K, 2, 'kW',
          seg((0, '#00E676'), (5000, '#ffb300'), (8000, '#ff5252'))),
        S('Temp', 'sensor.inverters_1_temperature', 0, 80, None, 0, '°C',
          seg((0, '#00E676'), (50, '#ffb300'), (70, '#ff5252'))),
        S('Freq', 'sensor.inverters_1_grid_frequency', 45, 55, None, 1, 'Hz',
          seg((45, '#ff5252'), (49, '#ffb300'), (49.8, '#00E676'), (50.3, '#ff5252'))),
    ], 'sensor.inverters_1_load_power'),
    ('Pool', 'Pool', '/local/pool.jpg', 'pool', [
        S('Energy', 'sensor.pool_energy_daily', 0, 10, None, 1, 'kWh',
          seg((0, '#4fc3f7'), (4, '#00E676'))),
    ], 'sensor.pool_energy_daily'),
    ('Sum', 'Sum', '/local/sum.jpg', 'sum', [
        S('PV1', 'sensor.inverters_1_pv_power_1', 0, 5000, K, 2, 'kW',
          seg((0, '#ffb300'), (3000, '#00E676'))),
        S('PV2', 'sensor.inverters_1_pv_power_2', 0, 5000, K, 2, 'kW',
          seg((0, '#ffb300'), (3000, '#00E676'))),
        S('Total', 'sensor.inverters_1_pv_power', 0, 10000, K, 2, 'kW',
          seg((0, '#ffb300'), (5000, '#00E676'))),
    ], 'sensor.inverters_1_pv_power'),
    ('Kitchen', 'Kitchen', '/local/kitchen.jpg', 'kitchen', [
        S('Load', 'sensor.inverters_1_load_power', 0, 5000, K, 2, 'kW',
          seg((0, '#00E676'), (3000, '#ffb300'), (4500, '#ff5252'))),
        S('Essential', 'sensor.inverters_1_load_power_essential', 0, 5000, K, 2, 'kW',
          seg((0, '#00E676'), (3000, '#ffb300'), (4500, '#ff5252'))),
    ], 'sensor.inverters_1_load_power'),
    ('Home', 'Home', '/local/home-house.jpg', 'home', [
        S('Load', 'sensor.inverters_1_load_power', 0, 5000, K, 2, 'kW',
          seg((0, '#00E676'), (3000, '#ffb300'), (4500, '#ff5252'))),
        S('Grid', 'sensor.inverters_1_grid_power', -5000, 5000, K, 2, 'kW',
          seg((-5000, '#00E676'), (0, '#ffb300'), (2000, '#ff5252'))),
        S('PV', 'sensor.inverters_1_pv_power', 0, 10000, K, 2, 'kW',
          seg((0, '#ffb300'), (5000, '#00E676'))),
    ], 'sensor.inverters_1_load_power'),
    ('Bedroom', 'Bedroom', '/local/bedroom.jpg', 'bedroom', ROOM_AIR,
     'sensor.tze200_mja3fuja_ts0601_temperature'),
    ('Terrace', 'Terrace', '/local/terrace.jpg', 'terrace', ROOM_AIR_VOC,
     'sensor.tze200_mja3fuja_ts0601_temperature'),
    ('Living', 'Living', '/local/living.jpg', 'living', ROOM_AIR,
     'sensor.tze200_mja3fuja_ts0601_temperature'),
    ('Laundry', 'Laundry', '/local/laundry.jpg', 'laundry', [
        S('Power', 'sensor.laundry_room_washing_machine_power', 0, 2500, None, 0, 'W',
          seg((0, '#00E676'), (1000, '#ffb300'), (2000, '#ff5252'))),
    ], 'sensor.laundry_room_washing_machine_power'),
]


def make_variant(title, label, img, area, orient, series, hist_entity):
    """Shared chrome for every variant card — edit once, all inherit."""
    return {
        'type': 'custom:sunsynk-power-flow-card',
        'cardstyle': 'pfg',
        'preset': 'pfg',
        'title': title,
        'pfg_grid_size': 1,
        'pfg_grid_width': '100%',
        'pfg_border': {'1,1': '2px solid #555'},
        'pfg_images': {'1,1': img},
        'pfg_labels': {'1,1': label},
        'pfg_label_pos': {'1,1': 'top'},
        'view_layout': {'grid-area': area},
        'card_width': '100%',
        'pfg_charts': {'1,1': [
            # history first: 'bg' layer renders behind the bars
            {'type': 'history', 'entity': hist_entity, 'hours': 24,
             'min': 0, 'max': 100, 'position': 'bg',
             'opacity': 0.8, 'scrim': True},
            {'type': 'bars', 'orientation': orient, 'position': 'bottom',
             'height': '55%', 'series': series},
        ]},
    }


def mutate(config):
    tpl = next((v for v in config.get('views', []) if v.get('path') == 'tpl'), None)
    if tpl is None:
        return
    # Drop all generated variants; rebuild from spec below.
    tpl['cards'] = [
        c for c in tpl.get('cards', [])
        if not str(c.get('title', '')).endswith(('.a1', '.b1'))
    ]
    cards = tpl['cards']
    rows = [
        '"pv pv pv pv pvv pvv pvv pvv pvh pvh pvh pvh"',
        '"grid grid grid grid ga ga ga ga gb gb gb gb"',
    ]
    # PV + Grid rows: custom areas
    cards.append(make_variant('PV.a1', 'PV2', '/local/pv-tiles.jpg', 'pvv',
                              'vertical', PV2, 'sensor.inverters_1_pv_power_2'))
    cards.append(make_variant('PV.b1', 'PV1', '/local/pv-tiles.jpg', 'pvh',
                              'horizontal', PV1, 'sensor.inverters_1_pv_power_1'))
    cards.append(make_variant('Grid.a1', 'Grid', '/local/power-grid.jpg', 'ga',
                              'vertical', GRID, 'sensor.inverters_1_grid_power'))
    cards.append(make_variant('Grid.b1', 'Grid', '/local/power-grid.jpg', 'gb',
                              'horizontal', GRID, 'sensor.inverters_1_grid_power'))
    # One row per remaining base card: base(4) | <base>a(4) | <base>b(4)
    for title, label, img, base, series, hist in SPEC:
        rows.append('"%s %s %s %s %sa %sa %sa %sa %sb %sb %sb %sb"'
                    % (base, base, base, base, base, base, base, base,
                       base, base, base, base))
        cards.append(make_variant(title + '.a1', label, img, base + 'a',
                                  'vertical', series, hist))
        cards.append(make_variant(title + '.b1', label, img, base + 'b',
                                  'horizontal', series, hist))
    lay = tpl.setdefault('layout', {})
    lay['grid-template-columns'] = 'repeat(12, 1fr)'
    lay['grid-template-rows'] = 'repeat(%d, auto)' % len(rows)
    lay['grid-template-areas'] = ' '.join(rows)
