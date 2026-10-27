"""Presentation payloads shared by the Qt host and OBS mirror."""
from endfield_pcap.overlays.templates import template_for


def table_snapshot(entry, message):
    if (message and 'analysis_summary' in template_for(entry).subscriptions and message.get('type') == 'analysis_snapshot'
            and isinstance(message.get('snapshot'), dict)):
        fields = {'battle', 'participants', 'snapshot_quality', 'rdps_preflight',
                  'rdps_damage_basis', 'unresolved_hits', 'unresolved_buff_actions'}
        return {**message, 'snapshot': {key: value for key, value in message['snapshot'].items() if key in fields}}
    return message
