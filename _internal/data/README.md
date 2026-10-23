# Runtime resource inventory

This directory is data used by the parser, live decoder, uploader payload builder
and GUI presenters. It is not an installed Python environment or a disposable
cache. Missing files can change resolution, names, conditions and strict rDPS
preflight even when a page still opens.

## Sources and retained contents

The reviewed baseline is the complete ZMDLogs **3.0.12 / 2026-10-16** ZIP.
`resource-manifest.json` records a relative path, size, SHA-256, dataset and
baseline comparison for every retained resource in `data/` and `../jsondata/`.
It contains 3,075 files (about 390.1 MB), excluding Markdown and the manifest itself:
3,071 byte-identical upstream files, 2 modified files and 2 development additions.
The baseline archive hash and fixed source URL are recorded in the manifest.

| Dataset | About MB | Consumers and missing-data behavior |
| --- | ---: | --- |
| `akedata/` | 227.5 | Per-ID character/skill/buff/weapon/equipment/enemy loading in parser, debug, payload and GUI; some files are fallback inputs. Missing entries can remove names, conditions or static context. |
| `local_semantics/` | 67.2 | Parser skill/buff details and classifier hints; GUI energy/frame reference rules. Missing rules can degrade evidence or use explicitly labeled display defaults. |
| `local_static/` | 43.3 | Typed BuffData trees, skill masks, damage elements, keyword maps and item attribute catalogues. Required for the corresponding strict semantic checks. |
| `packet_semantics/` | 32.3 | Live packet bundle and numeric mappings, mechanism/rDPS approval registries. Legacy maps are fallbacks, not proof that the bundle is redundant. |
| `local_tables/` | 15.8 | Local character/weapon/equipment/dungeon tables, localization and numeric ID table. Used alongside or as fallback to other datasets. |
| `public/` | 3.5 | `contract_tags.json` is active in the parser. Remaining rotation assets are retained pending separate coverage review; they are not proven required by the current GUI. |
| root message-ID JSON | small | MessageRegistry loads client/server maps by fixed filename. |
| `../jsondata/` | small | Character-name lookup, skill labels and combo cooldown display configuration. |

The name `akedata` does not establish a matching AKEDatabase commit. Its exact
provenance confirmed here is the pinned official client bundle. Upstream's
generation snapshot records source/extraction hashes; its machine-local root
paths have been removed from the public metadata, with the original in private
archive. Other inherited resource bytes have not been rewritten.

## Development changes

- `packet_semantics/rdps_semantics_registry.json`: reviewed development corrosion
  semantics change; keep this code-maintained registry with the parser.
- `local_semantics/team_energy_rules.json`: development team-energy presentation rules.
- `local_semantics/skill_frame_rules.json`: development skill-frame presentation rules.
- `game_resource_snapshot.json`: source hashes retained; only upstream absolute
  generation paths removed. The snapshot is provenance, not the game's installation path.

Updating `team_energy_rules` or `skill_frame_rules` affects presentation evidence,
not canonical damage/rDPS calculations. Protocol or game-data updates must keep
the source data, typed indexes and semantic registries compatible.

## Maintenance and verification

From the project root:

```powershell
python -B _development/tools/audit_runtime_data.py
python -B _development/tools/audit_runtime_data.py --exercise
```

The first command checks file membership and SHA-256. The second also records
representative reads through raw/viewer/overlay/live, uploader payload generation,
the live packet resolver and GUI data presenters. Results go to ignored
`_development/verification/`. Current representative coverage observed 456 files;
an unobserved resource is not automatically unused, especially with dynamic filenames.

After reviewing a deliberate data update, regenerate the inventory against the
pinned original ZIP with `--refresh <official ZIP>`, then run parser, uploader and
application regressions. Do not merely regenerate hashes to hide an unexpected change.
Do not delete one of two similar datasets without testing their fallback paths.

## Repository and distribution policy

Unchanged upstream resources are excluded from Git. The source repository keeps
this inventory, the sanitized snapshot, the development corrosion registry and
the two development presentation rule files. Existing workspace data stays put.

`Setup-Dev.cmd` restores missing resources with
`_development/tools/prepare_resources.py`, using the pinned source URL/archive
SHA-256 above and every file's inventory hash. Pass `--archive PATH --offline`
for a local official ZIP. Existing changed files and missing development overrides
fail rather than being overwritten. Keys and the uploader are opt-in components;
ordinary resource setup does not extract them. Repeated setup verifies/reuses
the existing resources. Run `--check` for read-only validation (missing returns 2).

The code's MIT license does not relicense game data, artwork, AKEData or other
external material. Exact upstream data licenses/redistribution terms have not
been established by a hash comparison. See the root `THIRD_PARTY_NOTICES.md`.
Personal game installs, captured packets, logs and credentials belong in ignored
local directories, not in this runtime-data tree.
