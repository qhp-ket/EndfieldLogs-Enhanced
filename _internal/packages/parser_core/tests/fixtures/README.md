# Public regression fixtures

All six `.log` files in this directory are synthetic. They are parser inputs
constructed for tests, not captured battles and not evidence of game mechanics
or upload eligibility. Game template/action IDs are used to select real parser
branches; actor IDs, session IDs, stats, HP and timestamps are invented.

| File | Construction and purpose |
| --- | --- |
| `rdps_snapshot_contract.log` | Upstream synthetic accounting example: 760 damage, 640 attacker / 120 support |
| `ink_recording_contract.log` | Synthetic 120-point hit, 10% recording, 12-point release and independent log weighting |
| `synthetic_combo_skill.log` | Constructed attack/skill categories, explicit three-Buff origin chain and per-hit source allocation |
| `synthetic_combo_ultimate.log` | Constructed ultimate/burning categories, explicit three-Buff origin chain and per-hit source allocation |
| `synthetic_corrosion_packet.log` | Constructed legacy refresh identity, observed resistance, own ignore and conflicting updates |
| `synthetic_fire_corrosion.log` | Constructed strict refresh identity, growth, inheritance and lower-count creation without refresh |

The four `synthetic_*` files and their manifests are reproducible with:

```powershell
python -B _development/tools/generate_test_fixtures.py
```

That generator reads constants only. It does not open a capture or replace IDs
in a real log. The first two fixtures remain their existing synthetic inputs.
Recorded excerpts, parsed metadata and player-loadout snapshots were moved to an
ignored private archive. The former Antal keyword, metadata and weapon audit JSON
inputs are now constructed constants in their respective test modules. Remaining
JSON inputs are an explicitly synthetic approval matrix and official item-text
reference tables, not captured battle excerpts. Real-world validation must explicitly obtain private
recordings or the official baseline; public tests do not silently read them.

Only these six logs are allowlisted by `.gitignore`. New cases should include
their construction, expected invariant and evidence limits before being added.
