"""Presentation payloads shared by the Qt host and OBS mirror."""
from .models import OverlaySourceType
from .overlay_templates import template_for, template_values


def overlay_config(entry):
    template = template_for(entry)
    values = template_values(entry, template)
    return dict(id=entry.id, locked=entry.locked, click_through=entry.click_through,
                opacity=entry.opacity, fontScale=entry.font_scale, fontMode=template.font_mode,
                settings=values, subscriptions=list(template.subscriptions),
                builtin=entry.source_value or 'damage',
                barMode=values.get('bar_mode', entry.bar_mode),
                visibleColumns=values.get('columns', list(entry.visible_columns)),
                theme=values.get('theme', entry.overlay_theme))


def table_snapshot(entry, message):
    if (message and entry.source_type == OverlaySourceType.BUILTIN
            and entry.source_value == 'damage' and message.get('type') == 'analysis_snapshot'
            and isinstance(message.get('snapshot'), dict)):
        fields = {'battle', 'participants', 'snapshot_quality', 'rdps_preflight',
                  'rdps_damage_basis', 'unresolved_hits', 'unresolved_buff_actions'}
        return {**message, 'snapshot': {key: value for key, value in message['snapshot'].items() if key in fields}}
    return message
