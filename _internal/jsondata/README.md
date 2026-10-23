# Display lookup resources

These three inherited JSON files provide character names, skill labels and
combo-cooldown configuration to the GUI/overlays. They are runtime inputs, not
personal settings. They are restored from the pinned official ZIP rather than
committed to Git. Origins and byte hashes are included in
`../data/resource-manifest.json`; maintenance and external-resource boundaries
are described in `../data/README.md`.

Keep canonical IDs stable when changing labels. A display cooldown is an estimate
from captured triggers and static configuration, not a claim that the skill is
currently usable. User-specific overlay preferences live in `.dev-gui/` instead.
