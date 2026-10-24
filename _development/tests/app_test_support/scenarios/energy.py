
def resource_snapshot():
    return dict(battle={'duration_ms': 6000}, participants=[{'character_key': key}
        for key in ('chr_0004_pelica', 'chr_0005_chen')], atb_events=[
        dict(ts_ms_from_start=1000, line_no=1, character_key='chr_0004_pelica', value=200, recovery_speed=8),
        dict(ts_ms_from_start=3000, line_no=3, character_key='chr_0005_chen', value=120, recovery_speed=0),
        dict(ts_ms_from_start=4000, line_no=4, character_key='chr_0005_chen', value=130, recovery_speed=8)])
