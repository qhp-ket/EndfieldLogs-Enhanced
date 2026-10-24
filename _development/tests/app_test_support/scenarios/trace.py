from app_test_support.paths import ROOT
from PySide6.QtCore import QEventLoop, QTimer

def two_battles():
    fixture = ROOT / '_internal/packages/parser_core/tests/fixtures/rdps_snapshot_contract.log'
    text = fixture.read_text(encoding='utf8')
    return '\n'.join([
        '[10:00:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_hard011_s challengeStartTs=1000',
        text,
        '[10:00:03.000] OFFICIAL_TIMER_END source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE gameId=indie_hard011_s isPass=1 passTime=3000',
        '[10:00:04.000] GAME_TIMER_RESET source=SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST',
        '[10:01:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_hard011_s challengeStartTs=61000',
        text.replace('10:00:', '10:01:').replace('hit=100 ', 'hit=200 '),
        '[10:01:03.000] OFFICIAL_TIMER_END source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE gameId=indie_hard011_s isPass=1 passTime=3000'])

def wait_for(predicate, app, timeout=45000):
    loop=QEventLoop()
    poll=QTimer()
    poll.setInterval(25)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    timeout_timer=QTimer()
    timeout_timer.setSingleShot(True)
    timeout_timer.timeout.connect(loop.quit)
    if not predicate():
        poll.start(); timeout_timer.start(timeout); loop.exec()
    poll.stop(); timeout_timer.stop()
    assert predicate()
