"""Freeze session boundaries, data clocks and publication state from the fixed Python live facade."""
import argparse
import asyncio
from datetime import date, datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType

from report_projection import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--application-reference', type=Path)
    parser.add_argument('--application-manifest', type=Path)
    args = parser.parse_args()
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, info in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != info['sha256']:
                raise ValueError('Fixed live session reference changed: ' + relative)
            dependencies[relative] = digest
    cases = []
    with tempfile.TemporaryDirectory() as folder:
        os.environ['ENDFIELD_LOGS_DATA_ROOT'] = folder
        package = ModuleType('parser_core')
        package.__path__ = [str(args.reference / prefix)]
        sys.modules['parser_core'] = package
        ingestion = importlib.import_module('parser_core.ingestion.stream')
        original = ingestion._raw_battle_ingestion
        ingestion._raw_battle_ingestion = lambda text: original(text, reference_date=date(2026, 10, 29))
        live = importlib.import_module('parser_core.realtime.live')
        original_monotonic = live.time.monotonic
        offset = int(datetime(2026, 10, 29).astimezone().utcoffset().total_seconds() / 60)

        def add(label, operations, **options):
            config = dict(summary=summary, align_to_data_watermark=True) | options
            engine = live.LiveOverlayBattleParser(**config)
            expected = []
            wall = 0
            mono = 0
            live._current_clock_ms = lambda: wall
            live.time.monotonic = lambda: mono / 1000
            for step in operations:
                wall, mono = step.get('wall_ms', wall), step.get('monotonic_ms', mono)
                if step.get('reset'):
                    engine.reset()
                if 'live_clock' in step:
                    engine.set_live_clock_enabled(step['live_clock'])
                engine.feed_lines(step.get('feed', []))
                result = engine.snapshot(step.get('observer_ms'), refresh=step.get('refresh', True))
                expected.append(dict(snapshot=canonical(result), generation=engine._generation, revision=engine._revision,
                    source_revision=engine.source_revision, line_count=len(engine._lines), hit_count=engine._hit_count,
                    dirty=engine._dirty, active=engine._official_timer_active, closed=engine._closed_by_timer_end,
                    officially_closed=engine._closed_by_official_timer_end))
            cases.append(dict(name=f'{len(cases):04d}-{label}', config_json=json.dumps(dict(options=config,
                operations=operations, date='2026-10-29', offset_minutes=offset)), expected=expected))

        first = '[00:00:01.100] HP_V2 #1 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=100'
        second = first.replace('01.100', '02.100').replace('#1', '#2').replace('hit=100', 'hit=50')
        start = '[00:00:01.000] OFFICIAL_TIMER_START gameId=challenge'
        end = '[00:00:03.000] OFFICIAL_TIMER_END gameId=challenge isPass=1 passTime=2000'
        context = '[00:00:00.900] SQUAD chars=chr_0001_test'
        for summary in [False, True]:
            add('append-read-only-explicit-clock', [dict(feed=[context, start, first]), {}, dict(observer_ms=3000), {},
                dict(feed=[second], refresh=False), {}, dict(feed=[end]), {}])
            add('reset-and-context', [dict(feed=[context, first]), dict(feed=['GAME_TIMER_RESET']),
                dict(feed=[context, start, first]), dict(reset=True), dict(feed=[second])])
            add('idle-hit-and-context', [dict(feed=[context, first]), dict(feed=[second.replace('00:00:02.100', '00:00:40.100')]),
                dict(feed=['[00:01:30.000] SQUAD chars=chr_0001_test']), dict(feed=[second.replace('00:00:02.100', '00:01:31.100')])])
            add('official-end-late-evidence', [dict(feed=[start, first, end]), dict(feed=['[00:00:04.000] HEARTBEAT']),
                dict(feed=['[00:00:04.100] UNKNOWN_EVIDENCE x=1']), dict(feed=[second]),
                dict(feed=['[00:00:02.000] BUFF_START uid=9 id=unknown_buff owner=chr_0001_test']),
                dict(feed=['[00:00:04.200] SKILL_CAST_START owner=chr_0001_test skill=chr_0001_test_normal_skill'])])
            add('legacy-end-next-hit', [dict(feed=[context, '[00:00:01.000] GAME_TIMER_START', first,
                '[00:00:01.900] GAME_TIMER_END elapsedMs=900']), dict(feed=[second]), {}])
            add('official-overrides-legacy', [dict(feed=[start, first]), dict(feed=['[00:00:01.500] GAME_TIMER_START']),
                dict(feed=['[00:00:01.800] GAME_TIMER_END elapsedMs=300', second]), dict(feed=[end])])
            add('context-boundary', [dict(feed=[context, '[00:00:01.000] GAME_TIMER_START', first,
                '[00:00:01.900] GAME_TIMER_END elapsedMs=900', '[00:00:02.000] LOADOUT chr=chr_0001_test']),
                dict(feed=['[00:00:03.000] OFFICIAL_TIMER_START gameId=next', second.replace('02.100', '03.100')])])
            add('clock-midnight', [dict(feed=[start.replace('00:00:01.000', '23:59:59.000'), first.replace('00:00:01.100', '23:59:59.100')]),
                dict(observer_ms=100), dict(feed=[second.replace('00:00:02.100', '00:00:00.200')]), dict(observer_ms=400), {}])
            add('disabled-clock', [dict(feed=[start, first]), dict(live_clock=False), dict(observer_ms=4000), {},
                dict(live_clock=True), dict(feed=[second])])
            add('wall-drift', [dict(feed=[start, first], wall_ms=1500), dict(wall_ms=2000), dict(wall_ms=900000),
                dict(observer_ms=2500), dict(wall_ms=900000)], align_to_data_watermark=False)
            add('throttle-and-forced-end', [dict(feed=[start, first], monotonic_ms=1000),
                dict(feed=[second], monotonic_ms=1050), dict(observer_ms=3000, monotonic_ms=1100),
                dict(feed=[end], monotonic_ms=1150), dict(monotonic_ms=2000)], min_reparse_interval_ms=500)
            add('unbounded-current-battle', [dict(feed=[context, start] + [first.replace('#1', f'#{i + 1}') for i in range(40)])], max_lines=5)
        live.time.monotonic = original_monotonic
        if args.application_reference and args.application_manifest:
            freeze_publication(args, metadata, dependencies, live, offset, first, second, start, end)
    output = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/live-session.json'
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases),
        dependencies=dependencies), indent=2), encoding='utf8')
    print('Live session fixtures:', len(cases))


def freeze_publication(args, metadata, dependencies, live, offset, first, second, start, end):
    application = json.loads(args.application_manifest.read_text(encoding='utf8'))
    relative = '_internal/src/endfield_pcap/analysis/live/publisher.py'
    source = args.application_reference / relative
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != application['files'][relative]['sha256']:
        raise ValueError('Fixed publisher source changed')
    # Only bundle_root is imported at module load; parser_factory explicitly supplies the fixed calculation engine.
    paths = ModuleType('endfield_pcap.runtime.paths')
    paths.bundle_root = lambda: args.application_reference / '_internal'
    sys.modules['endfield_pcap.runtime.paths'] = paths
    spec = importlib.util.spec_from_file_location('fixed_snapshot_publisher', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cases = []

    async def add(name, operations, summary):
        publisher = module.SnapshotPublisher(parser_factory=lambda: live.LiveOverlayBattleParser(
            align_to_data_watermark=True, summary=summary), summary=summary)
        streams = {}

        def normalized(frame):
            if frame is None:
                return None
            frame = dict(frame)
            stream = frame['stream_id']
            frame['stream_id'] = streams.setdefault(stream, f'stream-{len(streams)}')
            return canonical(frame)

        expected = []
        for step in operations:
            if step.get('reset'):
                publisher.reset(new_stream=step.get('new_stream', False))
            for line in step.get('feed', []):
                publisher.feed_line(line)
            if step.get('request'):
                publisher.request_current()
            frame = await publisher.publish_pending() if step.get('publish', True) else None
            expected.append(dict(frame=normalized(frame), current=normalized(publisher.current_message())))
        await publisher.close()
        cases.append(dict(name=f'{len(cases):04d}-{name}', config_json=json.dumps(dict(summary=summary,
            date='2026-10-29', offset_minutes=offset, operations=operations)), expected=expected))

    async def generate():
        for summary in [False, True]:
            await add('coalescing-cached-reads', [{}, dict(feed=[start, first, second]), {}, dict(request=True),
                dict(feed=['[00:00:02.200] UNKNOWN_EVIDENCE x=1']), dict(request=True)], summary)
            await add('ordered-reset', [dict(feed=[first]), {}, dict(feed=['GAME_TIMER_RESET', second]), {}, {},
                dict(reset=True, new_stream=True, feed=[first]), {}, dict(request=True)], summary)
            await add('ended-heartbeats-and-late-evidence', [{}, dict(feed=[start, first, end]),
                dict(feed=['[00:00:04.000] HEARTBEAT']), dict(request=True), dict(feed=[second]),
                dict(feed=['[00:00:02.000] BUFF_START uid=7 id=unknown_buff owner=chr_0001_test'])], summary)
            await add('queued-evidence', [{}, dict(feed=[first], publish=False), dict(feed=[second], publish=False), {}, {}], summary)
            await add('empty-and-repeated-reset', [{}, dict(request=True), dict(feed=['[00:00:01.000] HEARTBEAT']),
                dict(feed=['GAME_TIMER_RESET']), dict(reset=True), dict(request=True)], summary)
            await add('legacy-battle-boundaries', [{}, dict(feed=[first, '[00:00:02.000] GAME_TIMER_END elapsedMs=900']),
                dict(feed=[second]), dict(feed=[first.replace('00:00:01.100', '00:01:10.100')]), {}], summary)
            await add('transport-wide-integer', [{}, dict(feed=[first.replace('hit=100', 'hit=1208925819614629174706176')]),
                dict(request=True)], summary)
    asyncio.run(generate())
    output = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/live-publication.json'
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'],
        application_head=application['head'], application_dependencies={relative: digest}, cases=len(cases),
        dependencies=dependencies), indent=2), encoding='utf8')
    print('Live publication fixtures:', len(cases))


if __name__ == '__main__':
    main()
