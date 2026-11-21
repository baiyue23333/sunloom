// 随机一套主组装器（依赖 rand_scenes.js / rand_rules.js / rand_mutate.js）

function randomCompose() {
  const all = Object.keys(S.tokens || {}).filter(t => { try { return tokenVisible(t); } catch (e) { return true; } });
  if (!all.length) return;
  const has = t => !!t && all.includes(resolveToken(t));
  const pick = a => a[Math.floor(Math.random() * a.length)];
  const fromPref = p => all.filter(t => t.startsWith(p) && !(S.notes[t] || '').includes('失败'));
  const hist = S._randHist || [];
  const last = hist[hist.length - 1] || {}, last2 = hist[hist.length - 2] || {};
  const without = (arr, vals) => { const f = arr.filter(t => !vals.includes(t)); return f.length ? f : arr; };

  // 1. 场景 & 景别 & 身份策略
  const scene = pick(without(fromPref('@SET_'), [last.scene, last2.scene]));
  const prof = RAND_SCENE[scene] || {};
  const tags = _sceneTags(scene);
  const scale = sceneScaleKey(scene);
  const rc = (typeof selectedCharCard === 'function') ? selectedCharCard() : null;
  const framingPool = scale === 'large' ? ['mid', 'far'] : scale === 'small' ? ['near', 'mid'] : ['near', 'mid', 'far'];
  const framing = pick(framingPool);
  const roll = Math.random();
  const identityMode = framing === 'near'
    ? (roll < 0.18 ? 'none' : roll < 0.50 ? 'text' : 'block')
    : (roll < 0.25 ? 'none' : roll < 0.72 ? 'text' : 'block');

  // 2. 机位（含眼词身份块时避开纯背影机位）
  const camPool = without((RAND_CAM_BY_FRAME[framing] || []).filter(t => has(t) && _camOk(t, scene, scale, identityMode !== 'block')), [last.cam]);
  const cam = camPool.length ? pick(camPool) : (has('@CAM_MEDIUM') ? '@CAM_MEDIUM' : '');
  const isBackCam = RAND_BACK_CAM.has(cam);

  // 3. 服装
  const allGarments = Object.keys(S.garments || {}).filter(k => ((S.garments[k] || {}).gender || 'f') === S.gender);
  let outfitPool = _sceneCompatibleOutfits(scene, allGarments);
  if (!outfitPool.length) outfitPool = allGarments.filter(k => !['school_bare', 'yukata_bare', 'swimsuit', 'swim_m'].includes(k));
  const outfit = pick(without(outfitPool, [last.outfit, last2.outfit]));
  const om = RAND_GARMENT_META[outfit] || {};

  // 4. 道具 & 姿势 & 手部（先定姿势，再按是否背影过滤光源）
  let propTok = '';
  const propCands = (prof.props || []).filter(t => {
    if (!has(t)) return false;
    if (om.formal && /^@ROLE_(BAKER|FLORIST|PAINTER)$/.test(t)) return false;
    if (isBackCam && _propIsHandheld(t)) return false;
    if (framing === 'near' && /^@(RIDE|OBJ_SUITCASE)/.test(t)) return false;
    return true;
  });
  if (propCands.length && Math.random() < 0.35) propTok = pick(propCands);
  const hasHandProp = _propIsHandheld(propTok);

  const hasBackId = (identityMode === 'block');
  let posePool = Object.keys(RAND_POSE_META).filter(t => has(t) &&
    _poseOk(t, { framing, tags, om, isBack: isBackCam, hasBackId, hasProp: hasHandProp }));
  posePool = without(posePool, [last.pose]);
  const pose = posePool.length && (framing !== 'near' || Math.random() < 0.65) ? pick(posePool) : '';
  const poseInfo = RAND_POSE_META[pose] || {};
  const isBack = isBackCam || RAND_BACK_POSE.has(pose);

  // 5. 时间 & 光源（严格避开背影+正面光）
  const timePool = without((prof.time || fromPref('@TIME_')).filter(has), [last.time]);
  const time = timePool.length ? pick(timePool) : '';
  let lightPool = ((prof.light && prof.light.length) ? prof.light : (RAND_TIME_LIGHT[time] || fromPref('@LIGHT_'))).filter(has);
  if (isBack) {
    lightPool = lightPool.filter(l => !RAND_FRONT_LIGHT.has(l));
    if (!lightPool.length) lightPool = ['@LIGHT_BACK', '@LIGHT_WIN_BACK', '@LIGHT_RIM', '@LIGHT_SIDE', '@LIGHT_CANDLE', '@LIGHT_NEON', '@LIGHT_RAY'].filter(has);
  }
  if ((S.loras || []).some(l => /local_char_lora_(h1|h3|h4|v[2-6])\.safetensors$/i.test(l.name || ''))) {
    lightPool = lightPool.filter(l => l !== '@LIGHT_BACK');
  }
  const light = lightPool.length ? pick(without(lightPool, [last.light])) : '';

  // 6. 手部细节（未持物且姿势不占手时）
  let handTok = '';
  if (!hasHandProp && (!pose || poseInfo.hands === 'free') && !isBack && Math.random() < (framing === 'near' ? 0.65 : 0.38)) {
    const hPool = fromPref('@HAND_').filter(t => _handOk(t, { tags, om, framing }));
    if (hPool.length) handTok = pick(hPool);
  }

  // 8. 视线 / 情绪 / 氛围 / 背景 / 季节天气 / 穿法 / 材质 / 袜饰 / 发型 / 配饰 / 构图
  let gaze = '';
  if (!isBack) {
    let gPool = fromPref('@GAZE_').filter(t => t !== '@GAZE_WINDOW' || tags.has('win'));
    if (cam === '@CAM_PROFILE') gPool = gPool.filter(t => t !== '@GAZE_CAMERA' && t !== '@GAZE_UP');
    gaze = (framing === 'near' && cam !== '@CAM_PROFILE' && has('@GAZE_CAMERA') && Math.random() < 0.6)
      ? '@GAZE_CAMERA' : (gPool.length && Math.random() < 0.75 ? pick(gPool) : '');
  }
  const moodPool = ((prof.mood && prof.mood.length) ? prof.mood : fromPref('@MOOD_')).filter(has);
  const mood = !isBack && moodPool.length && Math.random() < 0.55 ? pick(moodPool) : '';
  const atmoPool = ((prof.atmo && prof.atmo.length) ? prof.atmo : fromPref('@ATMO_')).filter(has)
    .filter(t => tags.has('out') || tags.has('win') || !/RAIN|PETALS|MOON|KOMOREKI/.test(t));
  const atmo = atmoPool.length && Math.random() < 0.32 ? pick(atmoPool) : '';
  const bgPool = (prof.bg || ['@BG_BOKEH', '@BG_DEPTH']).filter(t => has(t) && t !== '@BG_CHROMA' && t !== '@BG_FLAT');
  const bgTok = bgPool.length && Math.random() < (framing === 'near' ? 0.55 : 0.28) ? pick(bgPool) : '';

  let seaOrWea = '';
  if (tags.has('out') && Math.random() < 0.25) {
    const sw = (prof.sea || []).concat(['@WEATHER_CLEAR', '@WEATHER_WIND', '@WEATHER_STORM', '@WEATHER_DRIZZLE']).filter(t => {
      if (!has(t)) return false;
      if (t === '@SEASON_SNOW' && om.temp === 'warm') return false;
      if (t === '@SEASON_SUMMER' && om.temp === 'cold') return false;
      return true;
    });
    if (sw.length) seaOrWea = pick(sw);
  }

  const drapePool = (om.drapes || []).filter(has);
  const drapeTok = drapePool.length && Math.random() < 0.35 ? pick(drapePool) : '';
  const fabPool = (om.fab || []).filter(has);
  const fabTok = fabPool.length && Math.random() < (framing === 'far' ? 0.2 : 0.35) ? pick(fabPool) : '';

  let hoseOrBare = '';
  if (om.bareOk && framing === 'far' && has('@BARE_FEET') && Math.random() < 0.35) {
    hoseOrBare = '@BARE_FEET';
  } else if (!om.hasSocks && !['swimsuit', 'swim_m', 'jinbei_m', 'yukata_m'].includes(outfit)) {
    if (S.gender === 'm' && framing === 'far' && (!om.pants || om.bareLegs) && Math.random() < 0.3) {
      const mh = RAND_HOSE_M_POOL.filter(has); if (mh.length) hoseOrBare = pick(mh);
    } else if (S.gender !== 'm' && (om.skirt || om.bareLegs) && framing !== 'near' && Math.random() < 0.35) {
      const fh = RAND_HOSE_POOL.filter(has); if (fh.length) hoseOrBare = pick(fh);
    }
  }

  let hairTok = '';
  const hasLockedHair = identityMode === 'block' || (identityMode === 'text' && (S.gender === 'm' || !!(rc && rc.identity_weak)));
  if (hasLockedHair && S.gender !== 'm' && !isBack && Math.random() < 0.28) {
    const dyn = ['@HAIR_F_WIND', '@HAIR_F_TUCKED', '@HAIR_F_STRAND'].filter(t => has(t) && (t !== '@HAIR_F_WIND' || seaOrWea !== '@WEATHER_WIND'));
    if (dyn.length) hairTok = pick(dyn);
  } else if (!hasLockedHair && Math.random() < 0.55) {
    const hAll = fromPref('@HAIR_').filter(t => t !== '@HAIR_F_WIND' || seaOrWea !== '@WEATHER_WIND');
    if (hAll.length) hairTok = pick(hAll);
  }

  let accTok = '';
  if (S.gender === 'm' && Math.random() < 0.3) {
    const accPool = fromPref('@ACC_M_').concat(['@ACC_GLASSES_ROUND', '@ACC_GLASSES_RECT', '@ACC_SCARF_LOOSE'].filter(has)).filter(t => {
      if ((t === '@ACC_M_SCARF' || t === '@ACC_M_BEANIE' || t === '@ACC_SCARF_LOOSE') && om.temp === 'warm') return false;
      if ((t === '@ACC_M_CAP' || t === '@ACC_M_GLOVES') && om.formal) return false;
      if (t === '@ACC_M_BELT' && (!om.pants || outfit === 'swim_m' || outfit === 'gym_m')) return false;
      if (t === '@ACC_M_TIEBAR' && !om.tie) return false;
      if (t === '@ACC_M_SUNGLASSES' && (tags.has('dark') || gaze === '@GAZE_CAMERA')) return false;
      return true;
    });
    if (accPool.length) accTok = pick(accPool);
  } else if (S.gender !== 'm' && !isBack && Math.random() < 0.25) {
    const fAcc = ['@PIN_CROSS', '@PIN_FEATHER', '@PIN_HEART', '@PIN_MOON', '@HAIRPIN_ROSE', '@HAIRPIN_STAR',
      '@CLIP_BUTTERFLY', '@HEADBAND_PEARL', '@RIBBON_BOW', '@BERET', '@FLOWER_CROWN',
      '@ACC_F_CHOKER', '@ACC_F_EARRINGS', '@ACC_GLASSES_ROUND', '@ACC_GLASSES_RECT', '@ACC_SCARF_LOOSE'].filter(t => {
      if (!has(t)) return false;
      if (t === '@FLOWER_CROWN' && !['@SET_GARDEN_PEONY','@SET_FOREST','@SET_FLOWER_SHOP','@SET_PARK','@SET_BOTANICAL_BRIDGE'].includes(scene)) return false;
      if ((t === '@BERET' || t === '@ACC_SCARF_LOOSE') && (om.formal || om.temp === 'warm')) return false;
      return true;
    });
    if (fAcc.length) accTok = pick(fAcc);
  }

  const useSingle = identityMode === 'block' && framing === 'near';
  const compPool = (RAND_COMP_BY_FRAME[framing] || []).filter(t => {
    if (!has(t)) return false;
    if (useSingle && /^@COMP_FIGURE_/.test(t)) return false;
    if (t === '@COMP_SILHOUETTE' && !['@LIGHT_BACK', '@LIGHT_RIM', '@LIGHT_WIN_BACK'].includes(light)) return false;
    if (t === '@COMP_REFLECTION' && !tags.has('water')) return false;
    if (t === '@COMP_FRAMEINFRAME' && !tags.has('win') && !tags.has('door')) return false;
    if (t === '@COMP_HORIZON_LOW' && !tags.has('out')) return false;
    if (t === '@COMP_VAST' && scale !== 'large') return false;
    return true;
  });
  const comp = compPool.length && Math.random() < 0.4 ? pick(compPool) : '';

  // 9. 画师 LoRA
  let artistName = '';
  if (Math.random() < 0.25) {
    const pool = (S.loraFiles || []).filter(f => loraCat(f) === '画师' && !(typeof isFlatProneArtist === 'function' && isFlatProneArtist(f)));
    if (pool.length) {
      artistName = pick(pool);
      S.loras = (S.loras || []).filter(l => loraCat(l.name) !== '画师');
      const cw = (typeof artistDefaultWeight === 'function' ? artistDefaultWeight(artistName, currentCharLora()) : null) || 1.0;
      S.loras.push({ name: artistName, weight: cw });
    }
  }

  // 10. 组装
  const blocks = [];
  const add = t => { const c = resolveToken(t); if (t && all.includes(c) && !blocks.some(b => b.token === c)) blocks.push({ id: uid(), token: c, text: '', weight: 1, enabled: true }); };
  if (identityMode === 'block') {
    let idToks;
    if (rc && (rc.tokens || []).length) {
      const cardIds = rc.tokens.filter(t => /^@ID_/.test(t));
      const cardRest = rc.tokens.filter(t => !/^@(ID|SINGLE)_/.test(t));
      idToks = (useSingle ? [S.gender === 'm' ? '@SINGLE_M' : '@SINGLE_F'] : [])
        .concat(cardIds.length ? [pick(cardIds)] : [])
        .concat(cardRest);
    } else {
      const pubIds = fromPref('@ID_').filter(t => !tokenOwner(t));
      idToks = S.gender === 'm'
        ? (useSingle ? ['@SINGLE_M'] : []).concat([pubIds.length ? pick(pubIds) : '@ID_M'])
        : (useSingle ? ['@SINGLE_F'] : []).concat(pubIds.length ? [pick(pubIds)] : []);
    }
    idToks.forEach(add);
  } else {
    const txt = identityMode === 'text'
      ? ((rc && rc.identity_weak) || (S.gender === 'm' ? (isBack ? '1boy, solo, short black hair' : TEXT_ID_MALE) : TEXT_ID))
      : (S.gender === 'm' ? '1boy, solo' : '1girl, solo');
    blocks.push({ id: uid(), token: '', text: txt, weight: 1, enabled: true });
  }
  if (!blocks.some(b => /^@BODY_/.test(b.token || ''))) add(pick(fromPref('@BODY_').filter(t => !/_(ADULT|YOUTH|CHIBI|CHIBI_SD)$/.test(t))) || '');
  if (!isBack && !blocks.some(b => /^@FACE_/.test(b.token || ''))) add(pick(fromPref('@FACE_').filter(t => !/_CHIBI$/.test(t))) || '');
  const randTrig = artistName ? artistTrigger(artistName) : '';
  if (randTrig) blocks.push({ id: uid(), token: '', text: randTrig, weight: 1, enabled: true, artist: true });
  [hairTok, accTok, gaze, cam, time, light, scene, '@OUT_' + outfit.toUpperCase(), drapeTok, fabTok,
   hoseOrBare, pose, handTok, propTok, (propTok.startsWith('@WEAPON_') ? '@WEAPON_GRIP' : ''),
   mood, atmo, seaOrWea, bgTok, comp].forEach(add);
  if (scene && framing === 'near') {
    blocks.push({ id: uid(), token: '', text: 'shallow depth of field, softly blurred background behind the subject, standing close to the camera', weight: 1, enabled: true });
  }

  // 11. 负向联动（防正负打架 + 补齐场景/姿势/性别/光影/穿法配套负向）
  S.pos = blocks;
  _syncNegatives('compose');

  S.loras = (S.loras || []).map(l => {
    const w = Number(l.weight);
    if (!Number.isFinite(w) || w <= 0) {
      const cat = loraCat(l.name);
      const dflt = cat === '角色' ? loraDefaultWeight(l.name) : (typeof artistDefaultWeight === 'function' ? artistDefaultWeight(l.name, currentCharLora()) : null) || loraDefaultWeight(l.name);
      return Object.assign({}, l, { weight: dflt });
    }
    return l;
  });

  const seed = 100000 + Math.floor(Math.random() * 899999);
  const sizeSel = document.querySelector('#p-size');
  if (sizeSel && [...sizeSel.options].some(o => o.value === '1024x1536')) sizeSel.value = '1024x1536';
  const customSize = document.querySelector('#custom-size');
  if (customSize) customSize.hidden = true;
  if (document.querySelector('#p-seed')) document.querySelector('#p-seed').value = seed;
  if (document.querySelector('#p-steps')) document.querySelector('#p-steps').value = 30;
  if (document.querySelector('#p-cfg')) document.querySelector('#p-cfg').value = 5.5;

  S._randHist = hist.concat([{ scene, outfit, cam, pose, time, light, framing, identityMode }]).slice(-8);
  renderLanes(); expandPreview();
  if (typeof updateEta === 'function') updateEta();
  const label = (S.garments[outfit] && S.garments[outfit].label) || outfit;
  toast('随机：' + scene.replace('@SET_', '') + ' · ' + label + ' · ' +
        ({ near: '近景', mid: '中景', far: '远景' }[framing] || '') + ' · ' +
        String(light || '无光').replace('@LIGHT_', '') + ' · seed ' + seed);
  scheduleRandomAudit({ scene, outfit, framing, light });
}

function randomPoseOnly() {
  const sceneTok = (S.pos.find(b => (b.token || '').startsWith('@SET_')) || {}).token || '';
  const tags = _sceneTags(sceneTok);
  const camTok = (S.pos.find(b => (b.token || '').startsWith('@CAM_')) || {}).token || '';
  const framing = camTok && typeof camFraming === 'function' ? camFraming(camTok) : 'mid';
  const outKey = ((S.pos.find(b => (b.token || '').startsWith('@OUT_')) || {}).token || '').replace(/^@OUT_/, '').toLowerCase();
  const om = RAND_GARMENT_META[outKey] || {};
  const isBackCam = RAND_BACK_CAM.has(camTok);
  const hasId = S.pos.some(b => /^@ID_/.test(b.token || ''));
  const hasProp = S.pos.some(b => _propIsHandheld(b.token || ''));
  const cur = (S.pos.find(b => (b.token || '').startsWith('@POSE_')) || {}).token || '';

  const allVis = Object.keys(RAND_POSE_META).filter(t => (S.tokens || {})[t] && tokenVisible(t) && t !== cur);
  let pool = allVis.filter(t => _poseOk(t, { framing, tags, om, isBack: isBackCam, hasBackId: hasId, hasProp }));
  if (!pool.length) {
    pool = allVis.filter(t => ['near', 'mid', 'far'].some(fr => _poseOk(t, { framing: fr, tags, om, isBack: isBackCam, hasBackId: hasId, hasProp })));
  }
  if (!pool.length) pool = allVis;
  const next = _randPick(pool);
  if (!next) return;

  _randReplaceOrAdd('@POSE_', next);
  const pm = RAND_POSE_META[next] || {};
  const isBack = isBackCam || RAND_BACK_POSE.has(next);
  if (pm.hands !== 'free' || pm.baked || isBack) {
    S.pos = S.pos.filter(b => !(b.token || '').startsWith('@HAND_'));
  }
  if (isBack) {
    S.pos = S.pos.filter(b => !/^@(GAZE|MOOD)_/.test(b.token || ''));
    const lt = (S.pos.find(b => (b.token || '').startsWith('@LIGHT_')) || {}).token || '';
    if (RAND_FRONT_LIGHT.has(lt)) {
      const bLights = ['@LIGHT_BACK', '@LIGHT_RIM', '@LIGHT_SIDE'].filter(l => (S.tokens || {})[l]);
      if (bLights.length) _randReplaceOrAdd('@LIGHT_', _randPick(bLights));
    }
  }
  _syncNegatives('mutate');
  renderLanes(); expandPreview();
  toast('只换动作：' + next.replace(/^@POSE_([FM]_)?/, '') + '（已联动手部/光影/负向）');
}

function randomCamOnly() {
  const sceneTok = (S.pos.find(b => (b.token || '').startsWith('@SET_')) || {}).token || '';
  const scale = sceneTok && typeof sceneScaleKey === 'function' ? sceneScaleKey(sceneTok) : 'medium';
  const tags = _sceneTags(sceneTok);
  const cur = (S.pos.find(b => (b.token || '').startsWith('@CAM_')) || {}).token || '';
  const hasId = S.pos.some(b => /^@ID_/.test(b.token || ''));
  const outKey = ((S.pos.find(b => (b.token || '').startsWith('@OUT_')) || {}).token || '').replace(/^@OUT_/, '').toLowerCase();
  const om = RAND_GARMENT_META[outKey] || {};

  const allCams = [...new Set([].concat(RAND_CAM_BY_FRAME.near || [], RAND_CAM_BY_FRAME.mid || [], RAND_CAM_BY_FRAME.far || []))];
  let pool = allCams.filter(c => (S.tokens || {})[c] && c !== cur && _camOk(c, sceneTok, scale, !hasId));
  if (!pool.length) pool = allCams.filter(c => (S.tokens || {})[c] && c !== cur);
  const next = _randPick(pool);
  if (!next) return;

  _randReplaceOrAdd('@CAM_', next);
  const framing = typeof camFraming === 'function' ? camFraming(next) : 'mid';
  const isBackCam = RAND_BACK_CAM.has(next);
  const compTok = (S.pos.find(b => (b.token || '').startsWith('@COMP_')) || {}).token || '';
  const validComps = (RAND_COMP_BY_FRAME[framing] || []).filter(c => (S.tokens || {})[c]);
  if (compTok && validComps.length && !validComps.includes(compTok)) {
    _randReplaceOrAdd('@COMP_', _randPick(validComps));
  }
  if (isBackCam) {
    S.pos = S.pos.filter(b => !_propIsHandheld(b.token || '') && b.token !== '@WEAPON_GRIP');
  }
  const hasProp = S.pos.some(b => _propIsHandheld(b.token || ''));
  const poseTok = (S.pos.find(b => (b.token || '').startsWith('@POSE_')) || {}).token || '';
  if (poseTok && RAND_POSE_META[poseTok] && !_poseOk(poseTok, { framing, tags, om, isBack: isBackCam, hasBackId: hasId, hasProp })) {
    const pPool = Object.keys(RAND_POSE_META).filter(t => (S.tokens || {})[t] && tokenVisible(t) &&
      _poseOk(t, { framing, tags, om, isBack: isBackCam, hasBackId: hasId, hasProp }));
    if (pPool.length) _randReplaceOrAdd('@POSE_', _randPick(pPool));
    else S.pos = S.pos.filter(b => b.token !== poseTok);
  }
  const curPose = (S.pos.find(b => (b.token || '').startsWith('@POSE_')) || {}).token || '';
  const isBack = isBackCam || RAND_BACK_POSE.has(curPose);
  S.pos = S.pos.filter(b => {
    const t = b.token || '';
    if (!t) return true;
    if (t.startsWith('@HAND_') && (isBack || !_handOk(t, { tags, om, framing }))) return false;
    if (isBack && /^@(GAZE|MOOD)_/.test(t)) return false;
    if (next === '@CAM_PROFILE' && (t === '@GAZE_CAMERA' || t === '@GAZE_UP')) return false;
    return true;
  });
  if (isBack) {
    const lt = (S.pos.find(b => (b.token || '').startsWith('@LIGHT_')) || {}).token || '';
    if (RAND_FRONT_LIGHT.has(lt)) {
      const bLights = ['@LIGHT_BACK', '@LIGHT_RIM', '@LIGHT_SIDE'].filter(l => (S.tokens || {})[l]);
      if (bLights.length) _randReplaceOrAdd('@LIGHT_', _randPick(bLights));
    }
  }
  _syncNegatives('mutate');
  renderLanes(); expandPreview();
  toast('只换视角：' + next.replace('@CAM_', '') + '（已联动动作/构图/负向）');
}

function randomComposePlaceholder() {}
