// 只换场景 / 只换服装的智能联动纠偏（与 rand_scenes.js / rand_rules.js 配套）

function _reconcileAfterScene(nextScene) {
  const prof = RAND_SCENE[nextScene] || {};
  const tags = _sceneTags(nextScene);
  const scale = sceneScaleKey(nextScene);
  const camTok = (S.pos.find(b => (b.token || '').startsWith('@CAM_')) || {}).token || '';
  const poseTok = (S.pos.find(b => (b.token || '').startsWith('@POSE_')) || {}).token || '';
  const outTok = (S.pos.find(b => (b.token || '').startsWith('@OUT_')) || {}).token || '';
  const om = RAND_GARMENT_META[outTok.replace(/^@OUT_/, '').toLowerCase()] || {};
  const hasId = S.pos.some(b => /^@ID_/.test(b.token || ''));

  const hasSingle = S.pos.some(b => /^@SINGLE/.test(b.token || ''));
  if (camTok && !_camOk(camTok, nextScene, scale, !hasId)) {
    const fr = hasSingle ? 'near' : (typeof camFraming === 'function' ? camFraming(camTok) : 'mid');
    let cands = (RAND_CAM_BY_FRAME[fr] || RAND_CAM_BY_FRAME.near).filter(c => (S.tokens || {})[c] && _camOk(c, nextScene, scale, !hasId) && !(hasSingle && ['@CAM_FULL','@CAM_MEDIUM','@CAM_THREEQ'].includes(c)));
    if (!RAND_BACK_CAM.has(camTok)) {
      const nonBack = cands.filter(c => !RAND_BACK_CAM.has(c));
      if (nonBack.length) cands = nonBack;
    }
    if (cands.length) _randReplaceOrAdd('@CAM_', _randPick(cands));
  }
  const curCam = (S.pos.find(b => (b.token || '').startsWith('@CAM_')) || {}).token || '';
  const isBack = RAND_BACK_CAM.has(curCam) || RAND_BACK_POSE.has(poseTok);
  const timeTok = (S.pos.find(b => (b.token || '').startsWith('@TIME_')) || {}).token || '';
  if (prof.time && prof.time.length && (!timeTok || !prof.time.includes(timeTok))) {
    _randReplaceOrAdd('@TIME_', _randPick(prof.time));
  }
  const lightTok = (S.pos.find(b => (b.token || '').startsWith('@LIGHT_')) || {}).token || '';
  let lPool = (prof.light && prof.light.length ? prof.light : Object.keys(S.tokens || {}).filter(t => t.startsWith('@LIGHT_')));
  if (isBack) lPool = lPool.filter(l => !RAND_FRONT_LIGHT.has(l));
  if (!lPool.length) lPool = ['@LIGHT_BACK', '@LIGHT_RIM', '@LIGHT_SIDE'].filter(l => (S.tokens || {})[l]);
  if (lPool.length && (!lightTok || !lPool.includes(lightTok))) {
    _randReplaceOrAdd('@LIGHT_', _randPick(lPool));
  }

  const allowedProps = new Set(prof.props || []);
  const framingNow = curCam && typeof camFraming === 'function' ? camFraming(curCam) : 'mid';
  S.pos = S.pos.filter(b => {
    const t = b.token || '';
    if (!t) return true;
    if (isBack && (t.startsWith('@GAZE_') || t.startsWith('@MOOD_'))) return false;
    if (t.startsWith('@ATMO_') && prof.atmo && prof.atmo.length && !prof.atmo.includes(t)) return false;
    if (t.startsWith('@ATMO_') && !tags.has('out') && !tags.has('win') && /RAIN|PETALS|MOON|KOMOREKI/.test(t)) return false;
    if (t.startsWith('@SEASON_')) return tags.has('out') && (!prof.sea || prof.sea.includes(t));
    if (t.startsWith('@WEATHER_')) return tags.has('out');
    if (t.startsWith('@BG_') && prof.bg && prof.bg.length && !prof.bg.includes(t)) return false;
    if (/^@(PROP|HOLD|OBJ|INSTR|RIDE|ROLE|WEAPON)_/.test(t) && t !== '@WEAPON_GRIP' && !allowedProps.has(t)) return false;
    if (t === '@GAZE_WINDOW' && !tags.has('win')) return false;
    return true;
  });
  if (!S.pos.some(b => (b.token || '').startsWith('@WEAPON_') && b.token !== '@WEAPON_GRIP')) {
    S.pos = S.pos.filter(b => b.token !== '@WEAPON_GRIP');
  }
  const hasProp = S.pos.some(b => _propIsHandheld(b.token || ''));
  if (poseTok && RAND_POSE_META[poseTok] && !_poseOk(poseTok, { framing: framingNow, tags, om, isBack, hasBackId: hasId, hasProp })) {
    const pPool = Object.keys(RAND_POSE_META).filter(t => (S.tokens || {})[t] && tokenVisible(t) &&
      _poseOk(t, { framing: framingNow, tags, om, isBack, hasBackId: hasId, hasProp }));
    if (pPool.length) _randReplaceOrAdd('@POSE_', _randPick(pPool));
    else S.pos = S.pos.filter(b => b.token !== poseTok);
  }
}

function _reconcileAfterOutfit(nextOutfit) {
  const om = RAND_GARMENT_META[nextOutfit] || {};
  const sceneTok = (S.pos.find(b => (b.token || '').startsWith('@SET_')) || {}).token || '';
  const tags = _sceneTags(sceneTok);
  const camTok = (S.pos.find(b => (b.token || '').startsWith('@CAM_')) || {}).token || '';
  const framing = camTok && typeof camFraming === 'function' ? camFraming(camTok) : 'mid';
  const isBack = RAND_BACK_CAM.has(camTok);
  const hasId = S.pos.some(b => /^@ID_/.test(b.token || ''));
  const hasProp = S.pos.some(b => _propIsHandheld(b.token || ''));

  S.pos = S.pos.filter(b => {
    const t = b.token || '';
    if (!t) return true;
    if (t.startsWith('@DRAPE_')) return (om.drapes || []).includes(t);
    if (t.startsWith('@FAB_')) return (om.fab || []).includes(t);
    if (t.startsWith('@HOSE_')) {
      if (om.hasSocks || ['swimsuit','swim_m','yukata_m','jinbei_m'].includes(nextOutfit)) return false;
      if (om.pants && !om.bareLegs && /^@HOSE_(THIGH|LACE|FISHNET|STRIPED|KNEE)/.test(t)) return false;
      return true;
    }
    if (t === '@BARE_FEET') return !!om.bareOk;
    if (t === '@ACC_M_SCARF' || t === '@ACC_M_BEANIE') return om.temp !== 'warm';
    if (t === '@ACC_M_CAP' || t === '@ACC_M_GLOVES') return !om.formal;
    if (t === '@ACC_M_BELT') return !!om.pants && nextOutfit !== 'swim_m' && nextOutfit !== 'gym_m';
    if (t === '@HAND_F_POCKET' || t === '@HAND_M_POCKET') return !!om.pockets;
    if (t === '@HAND_M_TIE') return !!om.tie;
    if (t === '@HAND_F_COLLAR' || t === '@HAND_F_CUFF' || t === '@HAND_M_ADJUST_CUFF') return !!om.collar || !!om.jacket;
    return true;
  });

  const poseTok = (S.pos.find(b => (b.token || '').startsWith('@POSE_')) || {}).token || '';
  if (poseTok && RAND_POSE_META[poseTok] && !_poseOk(poseTok, { framing, tags, om, isBack, hasBackId: hasId, hasProp })) {
    const pPool = Object.keys(RAND_POSE_META).filter(t => (S.tokens || {})[t] && tokenVisible(t) &&
      _poseOk(t, { framing, tags, om, isBack, hasBackId: hasId, hasProp }));
    if (pPool.length) _randReplaceOrAdd('@POSE_', _randPick(pPool));
    else S.pos = S.pos.filter(b => b.token !== poseTok);
  }
}

const _WORN_DRAPES = new Set(['@DRAPE_WORN','@DRAPE_ARMS','@DRAPE_WAIST','@DRAPE_BELT','@DRAPE_SLEEVES_ROLLED','@DRAPE_CARDIGAN_TIED','@DRAPE_M_BELTED','@DRAPE_M_TUCKED','@DRAPE_M_SCARF_WRAP','@DRAPE_M_CUFF','@DRAPE_M_COLLAR_POPPED']);
const _WHITE_KNITS = new Set(['cardigan_set','casual_knit','sundress','sundress_floral','yukata','yukata_bare','lab_coat','loungewear','initial_fine']);
const _FORMAL_GOWNS = new Set(['gala','initial_fine_gala','hanfu','idol','cheongsam']);
const _LONG_COATS = new Set(['winter','coat_m','winter_m','gala','hanfu','sailor_winter','lab_coat','labcoat_m','hakama_m','yukata']);
const _HAIR_ACC_TOKS = new Set(['@PIN_CROSS','@PIN_FEATHER','@PIN_HEART','@PIN_MOON','@HAIRPIN_ROSE','@HAIRPIN_STAR','@CLIP_BUTTERFLY','@CLIP_CAT_EAR','@HEADBAND_PEARL','@RIBBON_BOW','@BERET','@MINI_TOPHAT','@FLOWER_CROWN']);
const _CLUTTER_SETS = new Set(['@SET_CAFE','@SET_BEDROOM','@SET_CLASSROOM','@SET_LIBRARY','@SET_BOOKSTORE','@SET_ARTROOM','@SET_KITCHEN','@SET_OFFICE']);

function _syncNegatives(mode) {
  const pos = S.pos || [];
  const allToks = S.tokens || {};
  const has = t => !!t && !!allToks[t];
  const pToks = pos.map(b => b.token || '').filter(Boolean);
  const pSet = new Set(pToks);
  const hasAny = arr => arr.some(t => pSet.has(t));
  const outTok = pToks.find(t => t.startsWith('@OUT_')) || '';
  const outfit = outTok.replace(/^@OUT_/, '').toLowerCase();
  const om = RAND_GARMENT_META[outfit] || {};
  const sceneTok = pToks.find(t => t.startsWith('@SET_')) || '';
  const camTok = pToks.find(t => t.startsWith('@CAM_')) || '';
  const drapeTok = pToks.find(t => t.startsWith('@DRAPE_')) || '';
  const poseTok = pToks.find(t => t.startsWith('@POSE_')) || '';
  const framing = camTok && typeof camFraming === 'function' ? camFraming(camTok) : 'mid';
  const hasBareFeet = pSet.has('@BARE_FEET');
  const hasHose = pToks.some(t => t.startsWith('@HOSE_'));
  const hasHandAct = pToks.some(t => t.startsWith('@HAND_') || t.startsWith('@HOLD_') || t.startsWith('@WEAPON_')) ||
    hasAny(['@POSE_F_CHEEK_PEACE','@POSE_F_WINK_PEACE','@POSE_F_HEART_HANDS','@POSE_F_THUMBS_UP','@POSE_F_TOUCH_FACE','@POSE_F_TEA_CUP','@POSE_M_PHONE','@POSE_M_READ_BOOK','@POSE_M_DRINK_CUP','@POSE_M_LOOK_WATCH','@POSE_M_HEADPHONES_LISTEN']);
  const hasAcc = pToks.some(t => _HAIR_ACC_TOKS.has(t));
  const hasSunflowerId = pToks.some(t => /^@ID_F/.test(t) || t === '@ID');
  const longMaleHair = hasAny(['@HAIR_M_LONG_TIED','@HAIR_M_MAN_BUN','@HAIR_M_MULLET','@ID_M_REN']);
  const isDark = hasAny(['@LIGHT_NIGHT','@LIGHT_CANDLE','@TIME_NIGHT']) || hasAny(['@SET_ARCADE','@SET_PARKING','@SET_ONSEN']);
  const isWarmLight = hasAny(['@TIME_DUSK','@TIME_NIGHT','@LIGHT_GOLDEN','@LIGHT_CANDLE','@LIGHT_NEON']);
  const hasWhiteWear = _WHITE_KNITS.has(outfit) || ['uniform_m','santa','labcoat_m'].includes(outfit);
  const hasWhiteHair = hasSunflowerId || pSet.has('@ID_M_REN');
  const hasAnimaLora = (S.loras || []).some(l => /style_lora_a/i.test(l.name || ''));

  // 1. 禁止与当前正向/状态直接矛盾的负向
  const forb = new Set();
  if (!drapeTok) { forb.add('@NEG_DRAPE_ON'); forb.add('@NEG_DRAPE_OFF'); }
  else forb.add(_WORN_DRAPES.has(drapeTok) ? '@NEG_DRAPE_ON' : '@NEG_DRAPE_OFF');
  if (!hasBareFeet && !om.bareOk && outfit !== 'swimsuit' && outfit !== 'swim_m' && !pSet.has('@STRIP_SHOES') && !(S.neg || []).some(b => b.token === '@STRIP_SHOES')) forb.add('@NEG_SHOES');
  if (!hasBareFeet && (om.hasSocks || hasHose) && !pSet.has('@STRIP_SOCKS')) forb.add('@NEG_SOCKS');
  if (_WHITE_KNITS.has(outfit)) forb.add('@NEG_FABRIC');
  if (_FORMAL_GOWNS.has(outfit)) forb.add('@NEG_GARMENT');
  if (framing !== 'far') forb.add('@NEG_PORTRAIT');
  if (isDark) { forb.add('@NEG_EXPO'); }
  if (pSet.has('@ID_F_HANA') || (sceneTok === '@SET_BEACH' && pSet.has('@SEASON_SUMMER'))) forb.add('@NEG_SKIN');
  if (S.gender === 'm') {
    forb.add('@NEG_ANATOMY');
    if (longMaleHair) forb.add('@NEG_MALE_HAIR');
    if (pSet.has('@BODY_M_SLIM') || pSet.has('@ID_M_YOUNG')) forb.add('@NEG_MALE_SOFTBODY');
  } else {
    ['@NEG_MALE_BODY','@NEG_MALE_FACE','@NEG_MALE_HAIR','@NEG_MALE_CLOTHING','@NEG_MALE_HANDS','@NEG_MALE_SOFTBODY'].forEach(k => forb.add(k));
  }
  if (pSet.has('@MOOD_SMOKE')) forb.add('@NEG_PROPS');
  if (hasAny(['@HOLD_R_CUP','@HOLD_L_CUP','@POSE_F_TEA_CUP','@POSE_M_DRINK_CUP'])) forb.add('@NEG_CUP');
  if (hasAny(['@HOLD_R_BOOK','@HOLD_L_BOOK','@PROP_BOOK','@PROP_LETTER','@OBJ_BOOKS'])) forb.add('@NEG_DESK');
  if (hasAny(['@PROP_BLANKET','@OBJ_CANDLE','@OBJ_BOOKS']) || sceneTok !== '@SET_BEDROOM') forb.add('@NEG_BEDSIDE');
  if (!hasAny(['@POSE_F_CURL','@POSE_F_LIE','@POSE_F_LIE_BACK'])) forb.add('@NEG_DIORAMA');
  if (hasAny(['@BG_BOKEH','@ATMO_FOG','@ATMO_BOKEH','@POSE_F_RUN','@POSE_M_RUN'])) forb.add('@NEG_BLUR');
  if (!hasAcc) { forb.add('@NEG_ACC_FACE'); if (mode === 'compose') forb.add('@STRIP_PLANT'); }
  if (!hasAny(['@HOSE_THIGH_BLACK','@HOSE_LACE_TOP','@HOSE_FISHNET','@HOSE_MESH_BLACK'])) forb.add('@NEG_THICKHOSE');

  // 2. 构建/对齐配套负向（优先保证基础防崩 + 语义成对，不臃肿）
  const outNeg = [];
  const pushNeg = t => { if (t && has(t) && !forb.has(t) && !outNeg.includes(t)) outNeg.push(t); };
  ['@NEG_BASE', '@NEG_HANDS', '@NEG_PLANT', '@NEG_AI'].forEach(pushNeg);
  if (sceneTok) pushNeg('@NEG_NO_CLIP');
  if (outfit) pushNeg('@NEG_' + outfit.toUpperCase());

  if (mode === 'mutate') {
    for (const b of (S.neg || [])) {
      const t = b.token || '';
      if (!t) { outNeg.push(b); continue; }
      if (t.startsWith('@NEG_') && Object.prototype.hasOwnProperty.call(RAND_GARMENT_META, t.slice(5).toLowerCase()) && t !== '@NEG_' + outfit.toUpperCase()) continue;
      if (!forb.has(t) && !outNeg.includes(t)) outNeg.push(t);
    }
  }

  if (S.gender === 'm') {
    pushNeg('@NEG_MALE_BODY'); pushNeg('@NEG_MALE_FACE'); pushNeg('@NEG_MALE_CLOTHING');
    if (!longMaleHair) pushNeg('@NEG_MALE_HAIR');
    if (pToks.some(t => t.startsWith('@HAND_M_'))) pushNeg('@NEG_MALE_HANDS');
    if (hasAny(['@BODY_M_MUSCULAR','@BODY_M_ATHLETIC','@BODY_M_BROAD']) || ['swim_m','gym_m','jersey_m'].includes(outfit)) pushNeg('@NEG_MALE_SOFTBODY');
  } else if (poseTok || pToks.some(t => t.startsWith('@HAND_'))) {
    pushNeg('@NEG_ANATOMY');
  }

  if (hasHandAct) pushNeg('@NEG_HAND_ART');
  if (drapeTok) pushNeg(_WORN_DRAPES.has(drapeTok) ? '@NEG_DRAPE_OFF' : '@NEG_DRAPE_ON');
  if (hasBareFeet) { pushNeg('@NEG_SHOES'); pushNeg('@NEG_SOCKS'); }
  if (hasAcc) {
    pushNeg('@NEG_ACC_FACE');
    if (hasSunflowerId) { pushNeg('@NEG_PLANT'); pushNeg('@STRIP_PLANT'); }
  }
  if (_LONG_COATS.has(outfit) && /_(SIT|CROSS_LEGS|LAP_HANDS)/.test(poseTok)) pushNeg('@NEG_HEM');
  if (hasAny(['@POSE_F_CURL','@POSE_F_LIE','@POSE_F_LIE_BACK'])) { pushNeg('@NEG_DIORAMA'); pushNeg('@NEG_LONGHAIR'); }
  if (hasAny(['@CAM_WORM','@CAM_GROUND','@CAM_WIDE','@CAM_LOW_WIDE','@CAM_HIGH_WIDE','@CAM_DUTCH'])) pushNeg('@NEG_PERSPECTIVE');
  if (framing === 'far' && (hasAny(['@CAM_ESTABLISH','@CAM_FULL_WIDE','@CAM_HIGH_WIDE','@CAM_LOW_WIDE','@COMP_VAST']) || pToks.some(t => /^@COMP_FIGURE_/.test(t)))) {
    pushNeg('@NEG_PORTRAIT');
  }
  if (hasAny(['@ID_F_ADULT','@ID_M_ADULT','@BODY_F_ADULT','@FACE_F_ADULT'])) pushNeg('@NEG_CHILD');
  if (hasAnimaLora || (isWarmLight && (hasWhiteHair || hasWhiteWear))) pushNeg('@NEG_COLORBLEED');
  if (!isDark && (sceneTok === '@SET_SNOWFIELD' || pSet.has('@TIME_NOON') || (hasWhiteWear && hasAny(['@LIGHT_WIN','@LIGHT_GOLDEN'])))) {
    pushNeg('@NEG_EXPO');
  }
  if (isWarmLight && !forb.has('@NEG_SKIN')) pushNeg('@NEG_SKIN');

  if (mode === 'compose') {
    const opt = [];
    if (hasAny(['@HOSE_THIGH_BLACK','@HOSE_LACE_TOP','@HOSE_FISHNET','@HOSE_MESH_BLACK'])) opt.push('@NEG_THICKHOSE');
    if (pSet.has('@BG_BOKEH') || pSet.has('@CROP_FULL')) opt.push('@NEG_LETTERBOX');
    if (framing !== 'near') opt.push('@NEG_DOUBLE');
    if (pSet.has('@BG_CLEAN')) opt.push('@NEG_BGCLUTTER');
    if (Math.random() < 0.35) opt.push('@NEG_TEXT');
    for (const t of opt) {
      if (outNeg.length >= 10) break;
      pushNeg(t);
    }
  }

  S.neg = outNeg.map(x => typeof x === 'string' ? { id: uid(), token: x, text: '', weight: 1, enabled: true } : x);
}

function randomSceneOnly() {
  const all = Object.keys(S.tokens || {}).filter(t => t.startsWith('@SET_') && !(S.notes[t] || '').includes('失败'));
  if (!all.length) return;
  const cur = (S.pos.find(b => (b.token || '').startsWith('@SET_')) || {}).token || '';
  const curOut = ((S.pos.find(b => (b.token || '').startsWith('@OUT_')) || {}).token || '').replace(/^@OUT_/, '').toLowerCase();
  const om = RAND_GARMENT_META[curOut] || {};
  const hist = (S._randHist || []).slice(-4).map(h => h.scene);
  let pool = all.filter(t => t !== cur && !hist.includes(t));
  if (curOut) {
    const matched = pool.filter(s => {
      const tags = _sceneTags(s);
      if (curOut === 'swimsuit' || curOut === 'swim_m') return tags.has('water');
      if (RAND_PRIVATE_OUTFITS.has(curOut)) return tags.has('priv') || tags.has('in');
      if (om.temp === 'cold') return !tags.has('warm');
      const so = (RAND_SCENE[s] && RAND_SCENE[s].outfits) || [];
      return !so.length || so.includes(curOut) || !tags.has('priv');
    });
    if (matched.length) pool = matched;
  }
  const next = _randPick(pool.length ? pool : all.filter(t => t !== cur));
  if (!next) return;
  _randReplaceOrAdd('@SET_', next);
  _reconcileAfterScene(next);
  _syncNegatives('mutate');
  renderLanes(); expandPreview();
  toast('只换场景：' + next.replace('@SET_', '') + '（已联动光影/动作/负向）');
}

function randomOutfitOnly() {
  const garments = Object.keys(S.garments || {}).filter(k => ((S.garments[k] || {}).gender || 'f') === S.gender);
  if (!garments.length) return;
  const scene = (S.pos.find(b => (b.token || '').startsWith('@SET_')) || {}).token || '';
  const cur = ((S.pos.find(b => (b.token || '').startsWith('@OUT_')) || {}).token || '').replace(/^@OUT_/, '').toLowerCase();
  let pool = _sceneCompatibleOutfits(scene, garments);
  if (S.pos.some(b => b.token === '@SEASON_SNOW')) pool = pool.filter(k => (RAND_GARMENT_META[k] || {}).temp !== 'warm');
  if (S.pos.some(b => b.token === '@SEASON_SUMMER')) pool = pool.filter(k => (RAND_GARMENT_META[k] || {}).temp !== 'cold');
  pool = pool.filter(k => k !== cur);
  if (!pool.length) pool = garments.filter(k => k !== cur && !['school_bare', 'yukata_bare'].includes(k));
  const next = _randPick(pool);
  if (!next) return;
  const oldKey = cur.toUpperCase();
  _randReplaceOrAdd('@OUT_', '@OUT_' + next.toUpperCase());
  const newNeg = '@NEG_' + next.toUpperCase();
  if (oldKey && S.neg.some(b => b.token === '@NEG_' + oldKey)) {
    S.neg = S.neg.map(b => (b.token === '@NEG_' + oldKey) ? Object.assign({}, b, { token: newNeg }) : b);
  } else if ((S.tokens || {})[newNeg] && !S.neg.some(b => b.token === newNeg)) {
    S.neg.push({ id: uid(), token: newNeg, text: '', weight: 1, enabled: true });
  }
  _reconcileAfterOutfit(next);
  _syncNegatives('mutate');
  renderLanes(); expandPreview();
  const label = (S.garments[next] && S.garments[next].label) || next;
  toast('只换服装：' + label + '（已联动穿法/袜饰/动作/负向）');
}
