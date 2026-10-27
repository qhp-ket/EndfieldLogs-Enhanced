"""Compatible imports; implementation lives in realtime.live_copy."""
from parser_core.realtime.live_copy import (
    Counter,
    _COPY_CONTEXT,
    _reduce_defaults,
    _restore_defaults,
    changed_records,
    copy_ingestion_state,
    deepcopy,
    defaultdict,
    io,
    isolated_copy,
    pickle,
    threading,
)
