# -*- coding: utf-8 -*-
import json
lib=json.load(open(r'A:/workflow/dsh/ref/prompt_lib.json',encoding='utf-8'))
toks=lib['tokens']
def cat(k):
    n=k.upper()
    order=[('@NEG','负向'),('@DRAPE','型态'),('@OUT','服装'),('@MOOD','情绪'),('@POSE','姿势'),('@HOLD','手持'),
           ('@WEAPON','武器'),('@GAZE','视线'),('@HAND','手部'),('@HAIR','头发'),('@FAB','材质'),
           ('@ATMO','氛围'),('@TIME','时间'),('@SET','场景'),('@PROP','道具'),('@COMP','构图'),
           ('@STYLE','风格'),('@CAM','机位'),('@LIGHT','打光'),('@OBJ','道具'),('@INSTR','道具'),
           ('@RIDE','道具'),('@ROLE','道具'),('@STRIP','负向'),('@WEATHER','氛围'),('@SEASON','时间'),
           ('@BODY','体型'),('@FACE','脸型'),('@MAKEUP','脸型'),('@PIN','头发'),('@CLIP','头发'),
           ('@HAIRPIN','头发'),('@BERET','头发'),('@MINI','头发'),('@HEADBAND','头发'),('@RIBBON','头发'),
           ('@FLOWER','头发'),('@FX','风格'),('@CROP','构图'),('@BARE','体型'),('@SKIN','脸型'),
           ('@BG','构图'),('@CUSTOM','构图'),('@HOSE','服装'),('@ID','身份')]
    for pre,label in order:
        if n.startswith(pre): return label
    if n=='@SINGLE': return '身份'
    return '自定义'
groups={}
for k,v in toks.items(): groups.setdefault(cat(k),[]).append((k,v))
order=['身份','体型','脸型','头发','情绪','视线','手部','手持','武器','姿势','机位','构图','打光','氛围','时间','场景','道具','服装','材质','型态','风格','负向']
out=['# SUNLOOM 积木总表','','共 %d 块，按分类整理。' % len(toks),'']
for g in order:
    if g not in groups: continue
    items=sorted(groups[g])
    out.append('## %s（%d）' % (g,len(items)))
    out.append('')
    out.append('| 积木 | 提示词（截断） |')
    out.append('| --- | --- |')
    for k,v in items:
        t=str(v).replace('|','/')
        out.append('| %s | %s |' % (k, t[:90]))
    out.append('')
open(r'A:/workflow/dsh/产出作品/积木总表.md','w',encoding='utf-8').write('\n'.join(out))
print('written', len(toks), 'tokens', len(groups), 'groups')