
def hit(index, *, millis=None):
    stamp = index*100 if millis is None else millis
    return (f'[10:00:{stamp//1000:02d}.{stamp%1000:03d}] HP_V2 #{index} hit=120 '
            'packetFinalValue=120 eHP=100000 src=chr_0004_pelica tgt=eny_0051_rodin '
            'atkId=1001 tgtId=3001 skill="chr_0004_pelica_normal_skill"\n')
