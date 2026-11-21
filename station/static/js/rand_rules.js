// 服装结构元数据、筛选后自然姿态元数据与语义校验器（供 random.js 与 rand_mutate.js 共用）

const RAND_FRONT_LIGHT = new Set(['@LIGHT_WIN', '@LIGHT_SOFT', '@LIGHT_GOLDEN', '@LIGHT_SOFT_WARM', '@LIGHT_BOUNCE_COOL']);
const RAND_BACK_CAM = new Set(['@CAM_BACKSIDE', '@CAM_BACK_FAR']);
const RAND_BACK_POSE = new Set(['@POSE_F_BACK', '@POSE_M_WALK_AWAY']);
const RAND_HOSE_POOL = ['@HOSE_KNEE_WHITE', '@HOSE_THIGH_BLACK', '@HOSE_LACE_TOP', '@HOSE_ANKLE_WHITE', '@HOSE_SLOUCH', '@HOSE_FISHNET', '@HOSE_STRIPED', '@HOSE_ARGYLE', '@HOSE_MESH_BLACK', '@HOSE_RIBBED_CREAM', '@HOSE_OVERKNEE_BLACK', '@HOSE_CREW_STRIPE_COLOR', '@HOSE_LACE_ANKLE'];
const RAND_HOSE_M_POOL = ['@HOSE_M_SOCKS', '@HOSE_M_ANKLE', '@HOSE_M_KNEE', '@HOSE_M_STRIPED', '@HOSE_M_DRESS_NAVY', '@HOSE_M_CREW_WHITE', '@HOSE_M_WOOL_HEATHER'];
const RAND_SOCKED_OUTFITS = new Set(['school', 'sailor_winter', 'maid', 'santa', 'hakama_m']);
const RAND_PRIVATE_OUTFITS = new Set(['slip', 'pajama', 'loungewear']);
const RAND_PRIVATE_SCENES = new Set(['@SET_BEDROOM', '@SET_BATHROOM', '@SET_BALCONY', '@SET_ONSEN']);

const RAND_GARMENT_META = {
  cardigan_set:     { skirt:1, pockets:1, collar:1, drapes:['@DRAPE_OFF','@DRAPE_ELBOW','@DRAPE_WORN','@DRAPE_CARDIGAN_TIED'], fab:['@FAB_KNIT','@FAB_WOOL'] },
  casual_knit:      { skirt:1, hasSocks:1, drapes:['@DRAPE_OFF','@DRAPE_WORN','@DRAPE_CARDIGAN_TIED'], fab:['@FAB_KNIT','@FAB_WOOL'] },
  cheongsam:        { collar:1, fab:['@FAB_SATIN'] },
  denim_set:        { pants:1, bareLegs:1, pockets:1, jacket:1, drapes:['@DRAPE_OPEN_FRONT','@DRAPE_WORN','@DRAPE_SLEEVES_ROLLED'], fab:['@FAB_DENIM','@FAB_CORDUROY'] },
  gala:             { skirt:1, formal:1, drapes:['@DRAPE_OFF'], fab:['@FAB_VELVET','@FAB_SATIN'] },
  gym:              { pants:1, pockets:1, fab:['@FAB_FOLDS'] },
  hanfu:            { skirt:1, drapes:['@DRAPE_OFF','@DRAPE_WORN'], fab:['@FAB_CHIFFON','@FAB_SATIN'] },
  hoodie_casual:    { pants:1, bareLegs:1, pockets:1, drapes:['@DRAPE_SLEEVES_ROLLED'], fab:['@FAB_FOLDS'] },
  idol:             { skirt:1, bareLegs:1, fab:['@FAB_SATIN','@FAB_LACE'] },
  initial:          { pants:1, hasSocks:1, jacket:1, drapes:['@DRAPE_WORN'], fab:['@FAB_FOLDS'] },
  initial_fine:     { skirt:1, hasSocks:1, jacket:1, drapes:['@DRAPE_OFF','@DRAPE_ELBOW','@DRAPE_WORN'], fab:['@FAB_FOLDS'] },
  initial_fine_gala:{ skirt:1, formal:1, fab:['@FAB_SATIN','@FAB_VELVET'] },
  initial_fine_lite:{ skirt:1, hasSocks:1, fab:['@FAB_FOLDS'] },
  lab_coat:         { skirt:1, pockets:1, collar:1, jacket:1, drapes:['@DRAPE_OPEN_FRONT','@DRAPE_WORN','@DRAPE_SLEEVES_ROLLED'], fab:['@FAB_WOOL','@FAB_LINEN'] },
  loungewear:       { pants:1, bareLegs:1, hasSocks:1, bareOk:1, fab:['@FAB_FOLDS'] },
  maid:             { skirt:1, hasSocks:1, collar:1, fab:['@FAB_LACE','@FAB_FOLDS'] },
  overalls:         { pants:1, pockets:1, drapes:['@DRAPE_SLEEVES_ROLLED'], fab:['@FAB_DENIM','@FAB_CORDUROY'] },
  pajama:           { pants:1, bareOk:1, collar:1, fab:['@FAB_FOLDS','@FAB_LINEN'] },
  raincoat:         { pants:1, pockets:1, jacket:1, drapes:['@DRAPE_CAPE','@DRAPE_WORN'], fab:['@FAB_FOLDS'] },
  sailor_winter:    { skirt:1, hasSocks:1, pockets:1, collar:1, jacket:1, drapes:['@DRAPE_OPEN_FRONT','@DRAPE_WORN'], fab:['@FAB_WOOL','@FAB_CORDUROY'] },
  santa:            { skirt:1, hasSocks:1, temp:'cold', fab:['@FAB_FUR','@FAB_VELVET'] },
  school:           { skirt:1, hasSocks:1, collar:1, drapes:['@DRAPE_CARDIGAN_TIED'], fab:['@FAB_FOLDS'] },
  school_bare:      { skirt:1, bareOk:1, collar:1, drapes:['@DRAPE_CARDIGAN_TIED'], fab:['@FAB_FOLDS'] },
  slip:             { skirt:1, bareOk:1, drapes:['@DRAPE_OFF','@DRAPE_ELBOW'], fab:['@FAB_SATIN'] },
  smock:            { pants:1, drapes:['@DRAPE_OFF','@DRAPE_WORN','@DRAPE_SLEEVES_ROLLED'], fab:['@FAB_FOLDS','@FAB_LINEN'] },
  suit:             { skirt:1, formal:1, pockets:1, collar:1, jacket:1, drapes:['@DRAPE_WORN'], fab:['@FAB_WOOL'] },
  sunbloom:         { skirt:1, hasSocks:1, jacket:1, drapes:['@DRAPE_OPEN_FRONT','@DRAPE_WORN'], fab:['@FAB_FOLDS'] },
  sundress:         { skirt:1, bareOk:1, temp:'warm', drapes:['@DRAPE_OFF','@DRAPE_WORN','@DRAPE_CARDIGAN_TIED'], fab:['@FAB_CHIFFON','@FAB_LACE','@FAB_LINEN'] },
  sundress_floral:  { skirt:1, bareOk:1, temp:'warm', drapes:['@DRAPE_CARDIGAN_TIED'], fab:['@FAB_CHIFFON','@FAB_LINEN'] },
  swimsuit:         { bareLegs:1, bareOk:1, temp:'warm', fab:[] },
  winter:           { pants:1, pockets:1, scarf:1, jacket:1, temp:'cold', drapes:['@DRAPE_CAPE','@DRAPE_WORN'], fab:['@FAB_WOOL','@FAB_CORDUROY'] },
  yukata:           { bareOk:1, drapes:['@DRAPE_OFF','@DRAPE_WORN'], fab:['@FAB_FOLDS','@FAB_LINEN'] },
  yukata_bare:      { bareOk:1, drapes:['@DRAPE_OFF','@DRAPE_WORN'], fab:['@FAB_FOLDS','@FAB_LINEN'] },
  apron_m:          { pockets:1, collar:1, drapes:['@DRAPE_SLEEVES_ROLLED'], fab:['@FAB_M_LINEN','@FAB_LINEN'] },
  casual_m:         { pants:1, pockets:1, drapes:['@DRAPE_M_OVERSIZE','@DRAPE_M_HALF','@DRAPE_CARDIGAN_TIED'], fab:['@FAB_M_CASHMERE','@FAB_M_DENIM','@FAB_CORDUROY'] },
  coat_m:           { pants:1, pockets:1, scarf:1, jacket:1, temp:'cold', drapes:['@DRAPE_M_OPEN_COAT','@DRAPE_M_BELTED','@DRAPE_M_COLLAR_UP','@DRAPE_M_SCARF_WRAP'], fab:['@FAB_M_WOOL','@FAB_M_CASHMERE','@FAB_CORDUROY'] },
  gym_m:            { pants:1, bareLegs:1, temp:'warm', fab:['@FAB_M_NYLON'] },
  hakama_m:         { pants:1, hasSocks:1, fab:['@FAB_M_LINEN','@FAB_M_WOOL'] },
  hoodie_m:         { pants:1, pockets:1, drapes:['@DRAPE_M_OVERSIZE','@DRAPE_SLEEVES_ROLLED'], fab:['@FAB_M_NYLON'] },
  jersey_m:         { pants:1, bareLegs:1, temp:'warm', fab:['@FAB_M_NYLON'] },
  jinbei_m:         { bareOk:1, temp:'warm', fab:['@FAB_M_LINEN','@FAB_LINEN'] },
  labcoat_m:        { pants:1, pockets:1, collar:1, jacket:1, drapes:['@DRAPE_M_OPEN','@DRAPE_M_CUFF','@DRAPE_SLEEVES_ROLLED'], fab:['@FAB_M_LINEN','@FAB_LINEN'] },
  leather_m:        { pants:1, pockets:1, jacket:1, drapes:['@DRAPE_M_OPEN','@DRAPE_M_COLLAR_UP'], fab:['@FAB_M_LEATHER'] },
  raincoat_m:       { pants:1, pockets:1, jacket:1, drapes:['@DRAPE_M_OPEN_COAT'], fab:['@FAB_M_NYLON'] },
  school_m:         { pants:1, pockets:1, collar:1, tie:1, jacket:1, drapes:['@DRAPE_M_OPEN','@DRAPE_M_UNBUTTONED','@DRAPE_M_COLLAR_POPPED'], fab:['@FAB_M_WOOL','@FAB_SILK_M'] },
  suit_m:           { pants:1, pockets:1, collar:1, tie:1, jacket:1, formal:1, drapes:['@DRAPE_M_OPEN','@DRAPE_M_UNBUTTONED'], fab:['@FAB_M_TWEED','@FAB_M_WOOL','@FAB_SILK_M'] },
  swim_m:           { bareOk:1, temp:'warm', fab:[] },
  tracksuit_m:      { pants:1, pockets:1, jacket:1, drapes:['@DRAPE_M_CUFF','@DRAPE_SLEEVES_ROLLED'], fab:['@FAB_M_NYLON'] },
  tuxedo_m:         { pants:1, pockets:1, collar:1, tie:1, jacket:1, formal:1, drapes:['@DRAPE_M_OPEN'], fab:['@FAB_M_WOOL','@FAB_SILK_M'] },
  uniform_m:        { pants:1, pockets:1, collar:1, drapes:['@DRAPE_M_CUFF','@DRAPE_M_TUCKED','@DRAPE_M_HALF','@DRAPE_M_UNBUTTONED','@DRAPE_M_COLLAR_POPPED','@DRAPE_SLEEVES_ROLLED'], fab:['@FAB_M_LINEN','@FAB_LINEN','@FAB_SILK_M'] },
  vest_m:           { pants:1, pockets:1, collar:1, drapes:['@DRAPE_M_TUCKED','@DRAPE_SLEEVES_ROLLED'], fab:['@FAB_M_CORDUROY','@FAB_M_CASHMERE','@FAB_CORDUROY'] },
  winter_m:         { pants:1, pockets:1, scarf:1, jacket:1, temp:'cold', drapes:['@DRAPE_M_OPEN_COAT','@DRAPE_M_SCARF_WRAP'], fab:['@FAB_M_NYLON','@FAB_M_WOOL'] },
  yukata_m:         { bareOk:1, fab:['@FAB_M_LINEN','@FAB_LINEN'] }
};

// 排除 FLOAT / KICK / JUMP / HOP / SKIP / BALANCE / BENT_OVER / ARCH_BACK / CROUCH / SQUAT 等高怪异动作
const RAND_POSE_META = {
  '@POSE_F_STAND':         { fr:['mid','far'], hands:'free', face:'any' },
  '@POSE_F_WALK':          { fr:['mid','far'], req:['walk'], hands:'free', face:'any' },
  '@POSE_F_RUN':           { fr:['far'], req:['run'], hands:'both', face:'any' },
  '@POSE_F_SIT':           { fr:['mid','far'], req:['chair'], hands:'free', face:'any' },
  '@POSE_F_LAP_HANDS':     { fr:['mid','far'], req:['chair'], hands:'both', face:'any' },
  '@POSE_F_CROSS_LEGS':    { fr:['mid','far'], req:['chair'], hands:'free', face:'any' },
  '@POSE_F_SLEEP_SIT':     { fr:['mid'], req:['chair'], hands:'both', face:'front' },
  '@POSE_F_SIT_FLOOR':     { fr:['far'], req:['floor','bed'], hands:'both', face:'any' },
  '@POSE_F_SIT_SIDE':      { fr:['far'], req:['floor','steps','bed'], hands:'one', face:'any' },
  '@POSE_F_CURL':          { fr:['far'], req:['bed'], hands:'both', face:'any' },
  '@POSE_F_LIE':           { fr:['far'], req:['bed'], hands:'one', face:'any' },
  '@POSE_F_KNEEL':         { fr:['far'], req:['floor','bed'], hands:'free', face:'any' },
  '@POSE_F_LEAN':          { fr:['mid','far'], req:['wall'], hands:'free', face:'any' },
  '@POSE_F_LEAN_RAIL':     { fr:['mid','far'], req:['rail'], hands:'both', face:'any' },
  '@POSE_F_WINDOW_GAZE':   { fr:['near','mid','far'], req:['win'], hands:'one', face:'any' },
  '@POSE_F_PEEK':          { fr:['near','mid'], req:['door','wall'], hands:'one', face:'front' },
  '@POSE_F_LOOK_BACK':     { fr:['near','mid','far'], hands:'free', face:'back' },
  '@POSE_F_QUIET_TURN':    { fr:['near','mid','far'], hands:'free', face:'back' },
  '@POSE_F_BACK':          { fr:['far'], hands:'free', face:'back' },
  '@POSE_F_LOOK_UP':       { fr:['near','mid'], hands:'free', face:'front' },
  '@POSE_F_LOOK_DOWN':     { fr:['near','mid'], hands:'both', face:'front' },
  '@POSE_F_TILT_HEAD':     { fr:['near'], hands:'free', face:'front' },
  '@POSE_F_HAND_ON_HAIR':  { fr:['near','mid'], hands:'one', face:'front' },
  '@POSE_F_TOUCH_FACE':    { fr:['near'], hands:'one', face:'front' },
  '@POSE_F_ADJUST_COLLAR': { fr:['near','mid'], out:'collar', hands:'one', face:'front' },
  '@POSE_F_ARMS_CROSSED':  { fr:['near','mid'], hands:'both', face:'front' },
  '@POSE_F_HANDS_CLASP':   { fr:['mid','far'], hands:'both', face:'any' },
  '@POSE_F_HANDS_POCKETS': { fr:['mid','far'], out:'pockets', hands:'both', face:'any' },
  '@POSE_F_CHEEK_PEACE':   { fr:['near'], hands:'one', face:'front' },
  '@POSE_F_WINK_PEACE':    { fr:['near'], hands:'one', face:'front' },
  '@POSE_F_HEART_HANDS':   { fr:['near'], hands:'both', face:'front' },
  '@POSE_F_THUMBS_UP':     { fr:['near'], hands:'one', face:'front' },
  '@POSE_F_POUT':          { fr:['near'], hands:'both', face:'front' },
  '@POSE_F_STRETCH':       { fr:['mid','far'], hands:'both', face:'any' },
  '@POSE_F_STRETCH_YAWN':  { fr:['near','mid'], req:['bed','chair'], hands:'both', face:'front' },
  '@POSE_F_SCARF_WRAP':    { fr:['near','mid'], out:'scarf', hands:'both', face:'front' },
  '@POSE_F_TEA_CUP':       { fr:['near','mid'], req:['chair','bed'], hands:'both', face:'front', baked:1 },
  '@POSE_F_PRAY':          { fr:['mid','far'], hands:'both', face:'front' },
  '@POSE_F_SIT_WINDOW':    { fr:['mid','far'], req:['win'], hands:'free', face:'any' },
  '@POSE_F_TURN_SKIRT':    { fr:['mid','far'], req:['walk'], hands:'free', face:'any' },
  '@POSE_F_BENCH_KNEES':   { fr:['mid','far'], req:['chair'], hands:'free', face:'any' },
  '@POSE_F_LEAN_DOOR':     { fr:['mid','far'], req:['door'], hands:'free', face:'any' },
  '@POSE_F_LEAN_TABLE':    { fr:['mid','far'], req:['desk'], hands:'both', face:'front' },
  '@POSE_F_HIP_WEIGHT':    { fr:['mid','far'], hands:'one', face:'any' },
  '@POSE_F_SIT_DESK':      { fr:['mid','far'], req:['desk'], hands:'both', face:'any' },
  '@POSE_F_HOLD_NOTEBOOK': { fr:['near','mid','far'], hands:'both', face:'front', baked:1 },
  '@POSE_F_READ_STANDING': { fr:['near','mid','far'], hands:'both', face:'front', baked:1 },
  '@POSE_F_TURN_SMILE':    { fr:['mid','far'], req:['walk'], hands:'both', face:'front' },
  '@POSE_F_FINGERS_CHIN':  { fr:['near','mid'], hands:'both', face:'front' },
  '@POSE_F_WALK_SIDE':     { fr:['far'], req:['walk'], hands:'free', face:'any' },
  '@POSE_F_WALK_STAIRS':   { fr:['far'], req:['steps','walk'], hands:'free', face:'any' },
  '@POSE_F_TIED_HAIR':     { fr:['near','mid'], hands:'both', face:'front' },
  '@POSE_F_SIT_CROSS_ANKLE':{ fr:['mid','far'], req:['chair','steps'], hands:'both', face:'any' },
  '@POSE_F_UMBRELLA_TWIRL':{ fr:['far'], req:['walk'], hands:'one', face:'front', baked:1 },
  '@POSE_M_WALK':            { fr:['mid','far'], req:['walk'], hands:'free', face:'any' },
  '@POSE_M_WALK_FORWARD':    { fr:['mid','far'], req:['walk'], hands:'free', face:'front' },
  '@POSE_M_WALK_AWAY':       { fr:['far'], req:['walk'], hands:'free', face:'back' },
  '@POSE_M_RUN':             { fr:['far'], req:['run'], hands:'both', face:'any' },
  '@POSE_M_HANDS_POCKET':    { fr:['mid','far'], out:'pockets', hands:'both', face:'any' },
  '@POSE_M_THUMBS_POCKET':   { fr:['mid','far'], out:'pockets', hands:'both', face:'any' },
  '@POSE_M_ARMS_CROSSED':    { fr:['near','mid','far'], hands:'both', face:'front' },
  '@POSE_M_ARMS_AKIMBO':     { fr:['mid','far'], hands:'both', face:'any' },
  '@POSE_M_HANDS_CLASP_BACK':{ fr:['mid','far'], hands:'both', face:'any' },
  '@POSE_M_LEAN_WALL':       { fr:['mid','far'], req:['wall'], hands:'free', face:'any' },
  '@POSE_M_LEAN_DOOR':       { fr:['mid','far'], req:['door'], hands:'both', face:'any' },
  '@POSE_M_LEAN_RAILING':    { fr:['mid','far'], req:['rail'], hands:'both', face:'any' },
  '@POSE_M_SIT_DESK':        { fr:['mid','far'], req:['desk'], hands:'free', face:'any' },
  '@POSE_M_CROSS_LEGS_SIT':  { fr:['mid','far'], req:['chair'], hands:'both', face:'any' },
  '@POSE_M_SIT_SPREAD':      { fr:['far'], req:['chair','steps'], hands:'both', face:'any' },
  '@POSE_M_SIT_STEPS':       { fr:['far'], req:['steps'], hands:'both', face:'any' },
  '@POSE_M_SIT_FLOOR':       { fr:['far'], req:['floor','bed'], hands:'both', face:'any' },
  '@POSE_M_KNEEL':           { fr:['far'], req:['floor'], hands:'free', face:'any' },
  '@POSE_M_LOOK_BACK':       { fr:['near','mid','far'], hands:'free', face:'back' },
  '@POSE_M_LOOK_SIDE':       { fr:['near','mid'], hands:'free', face:'front' },
  '@POSE_M_LOOK_UP':         { fr:['near','mid'], hands:'free', face:'front' },
  '@POSE_M_WAVE':            { fr:['near','mid'], hands:'one', face:'front' },
  '@POSE_M_HOLD_JACKET':     { fr:['mid','far'], out:'jacket', hands:'one', face:'any' },
  '@POSE_M_DRINK_CUP':       { fr:['near','mid'], req:['chair','desk'], hands:'one', face:'front', baked:1 },
  '@POSE_M_READ_BOOK':       { fr:['mid','far'], req:['chair','desk'], hands:'one', face:'front', baked:1 },
  '@POSE_M_PHONE':           { fr:['near','mid'], hands:'one', face:'front', baked:1 },
  '@POSE_M_STRETCH':         { fr:['mid','far'], hands:'both', face:'any' },
  '@POSE_M_SIT_BENCH':       { fr:['mid','far'], req:['chair'], hands:'free', face:'any' },
  '@POSE_M_LOOK_WATCH':      { fr:['near','mid'], hands:'one', face:'front' },
  '@POSE_M_LEAN_TABLE':      { fr:['mid','far'], req:['desk'], hands:'both', face:'front' },
  '@POSE_M_HAND_IN_POCKET_SIT':{ fr:['far'], req:['steps','chair'], out:'pockets', hands:'both', face:'any' },
  '@POSE_M_HEADPHONES_LISTEN':{ fr:['near','mid'], hands:'one', face:'front', baked:1 },
  '@POSE_M_WALK_STAIRS':     { fr:['far'], req:['steps','walk'], hands:'free', face:'any' },
  '@POSE_M_CARRY_BAG_SIDE':  { fr:['mid','far'], req:['walk'], hands:'one', face:'any' },
  '@POSE_M_CROUCH_SIDE':     { fr:['far'], req:['floor'], hands:'both', face:'any' },
  '@POSE_M_WEIGHT_SHIFT':    { fr:['mid','far'], out:'pockets', hands:'one', face:'any' },
  '@POSE_M_SIT_WINDOW':      { fr:['mid','far'], req:['win'], hands:'one', face:'any' },
  '@POSE_M_SIT_CHIN':        { fr:['mid','far'], req:['chair'], hands:'both', face:'front' },
  '@POSE_M_WINDOW_GAZE':     { fr:['near','mid','far'], req:['win'], hands:'one', face:'front' },
  '@POSE_M_HOLD_BOOK_SIDE':  { fr:['mid','far'], hands:'one', face:'any', baked:1 },
  '@POSE_M_STEP_TURN':       { fr:['mid','far'], req:['walk'], hands:'free', face:'front' },
  '@POSE_M_V_SIGN_CASUAL':   { fr:['near','mid'], hands:'one', face:'front' },
  '@POSE_M_HAND_NECK':       { fr:['near','mid'], hands:'one', face:'front' },
  '@POSE_M_ADJUST_COLLAR':   { fr:['near','mid'], out:'collar', hands:'one', face:'front' },
  '@POSE_M_SPRINT_STOP':     { fr:['far'], req:['walk','run'], hands:'free', face:'front' },
  '@POSE_M_COAT_BUTTON':     { fr:['near','mid'], out:'jacket', hands:'both', face:'front' },
  '@POSE_M_LEAN_RAIL_ONE':   { fr:['mid','far'], req:['rail'], hands:'one', face:'any' }
};

function _sceneTags(scene) {
  return new Set(String((RAND_SCENE[scene] && RAND_SCENE[scene].tags) || 'in walk').split(/\s+/).filter(Boolean));
}
function _randPick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }
function _randReplaceOrAdd(prefix, newTok) {
  const idx = (S.pos || []).findIndex(b => (b.token || '').startsWith(prefix));
  if (idx >= 0) S.pos = S.pos.map((b, i) => i === idx ? Object.assign({}, b, { token: newTok, enabled: true }) : b);
  else S.pos.push({ id: uid(), token: newTok, text: '', weight: 1, enabled: true });
}
function _poseOk(tok, { framing, tags, om, isBack, hasBackId, hasProp }) {
  const pm = RAND_POSE_META[tok];
  if (!pm || !(pm.fr || []).includes(framing)) return false;
  if (pm.req && !pm.req.some(r => tags.has(r))) return false;
  if (pm.out && !om[pm.out]) return false;
  if (isBack && pm.face === 'front') return false;
  if (hasBackId && pm.face === 'back') return false;
  if (hasProp && (pm.hands !== 'free' || pm.baked)) return false;
  return true;
}
function _handOk(tok, { tags, om, framing }) {
  if (tok.includes('_POCKET') && !om.pockets) return false;
  if (tok === '@HAND_F_COLLAR' && !om.collar) return false;
  if (tok === '@HAND_F_CUFF' && !om.jacket && !om.collar) return false;
  if (tok === '@HAND_M_ADJUST_CUFF' && !om.collar && !om.jacket) return false;
  if (tok === '@HAND_M_TIE' && !om.tie) return false;
  if (tok === '@HAND_F_SCARF_TOUCH' && !om.scarf) return false;
  if (tok === '@HAND_M_LAPEL' && !om.jacket && !om.collar) return false;
  if (tok === '@HAND_F_GLASSES' || tok === '@HAND_M_GLASSES') return false;
  if (tok === '@HAND_F_KNEES' && framing === 'near') return false;
  if ((tok === '@HAND_F_CHIN' || tok === '@HAND_M_HOLD_CUP') && !tags.has('chair') && !tags.has('desk')) return false;
  return true;
}
function _camOk(cam, scene, scale, allowBack) {
  const tags = _sceneTags(scene);
  if (cam === '@CAM_WINDOW' && !tags.has('win')) return false;
  if (cam === '@CAM_DOORWAY' && !tags.has('door')) return false;
  if (cam === '@CAM_CORNER' && !tags.has('in')) return false;
  if (scale === 'small' && ['@CAM_ESTABLISH','@CAM_HIGH_WIDE','@CAM_LOW_WIDE','@CAM_GROUND','@CAM_WORM'].includes(cam)) return false;
  if (!tags.has('out') && ['@CAM_GROUND','@CAM_WORM'].includes(cam) && scale !== 'large') return false;
  return allowBack || !RAND_BACK_CAM.has(cam);
}
function _propIsHandheld(tok) {
  return tok.startsWith('@HOLD_') || tok.startsWith('@WEAPON_') ||
    ['@PROP_BRUSH','@PROP_PALETTE','@PROP_CANVAS','@PROP_BOOK','@PROP_LETTER','@PROP_PLANT','@PROP_UMBRELLA','@PROP_VINYL','@PROP_VIOLIN','@PROP_LANTERN','@INSTR_FLUTE','@INSTR_GUITAR','@OBJ_UMBRELLA_OPEN','@OBJ_CAT'].includes(tok);
}
function _sceneCompatibleOutfits(scene, allGarments) {
  const prof = RAND_SCENE[scene] || {};
  let list = (prof.outfits || []).filter(k => allGarments.includes(k));
  if (!list.length) {
    const tags = _sceneTags(scene);
    list = allGarments.filter(k => {
      const m = RAND_GARMENT_META[k] || {};
      if (k === 'swimsuit' || k === 'swim_m') return tags.has('water') && tags.has('warm');
      if (RAND_PRIVATE_OUTFITS.has(k)) return tags.has('priv');
      if (m.temp === 'cold' && tags.has('warm')) return false;
      return !['school_bare', 'yukata_bare'].includes(k);
    });
  }
  return list;
}
