// 时段→默认光影、景别→机位/构图、场景服装组与构造函数（供 rand_scenes / random / rand_mutate 复用）

const _F_CAS = ['cardigan_set', 'casual_knit', 'denim_set', 'hoodie_casual', 'sundress', 'sundress_floral'];
const _M_CAS = ['casual_m', 'hoodie_m', 'vest_m', 'uniform_m', 'leather_m'];
const _F_SCH = ['school', 'sailor_winter', 'cardigan_set', 'sunbloom'];
const _M_SCH = ['school_m', 'vest_m', 'casual_m'];
const _F_FOR = ['gala', 'cheongsam', 'suit', 'initial_fine_gala', 'initial_fine'];
const _M_FOR = ['suit_m', 'tuxedo_m', 'coat_m', 'uniform_m'];
const _F_HOM = ['loungewear', 'pajama', 'slip', 'casual_knit', 'cardigan_set'];
const _M_HOM = ['casual_m', 'hoodie_m', 'jinbei_m', 'uniform_m'];
const _F_TRD = ['yukata', 'hanfu', 'cheongsam'];
const _M_TRD = ['yukata_m', 'jinbei_m', 'hakama_m'];
const _F_WRK = ['suit', 'lab_coat', 'cardigan_set'];
const _M_WRK = ['suit_m', 'uniform_m', 'labcoat_m', 'casual_m'];

const _px = (s, pre) => s ? s.split(',').filter(Boolean).map(x => pre + x) : [];
const _sc = (t, l, a, m, o, tags, p, bg, sea) => ({
  time: _px(t, '@TIME_'),
  light: _px(l, '@LIGHT_'),
  atmo: _px(a, '@ATMO_'),
  mood: _px(m, '@MOOD_'),
  outfits: o || [],
  tags: tags || 'in walk',
  props: p ? p.split(',').filter(Boolean).map(x => '@' + x) : [],
  bg: _px(bg, '@BG_'),
  sea: _px(sea, '@SEASON_')
});

const RAND_TIME_LIGHT = {
  '@TIME_MORNING':   ['@LIGHT_WIN', '@LIGHT_SIDE', '@LIGHT_TOP', '@LIGHT_SOFT'],
  '@TIME_AFTERNOON': ['@LIGHT_WIN', '@LIGHT_GOLDEN', '@LIGHT_SIDE', '@LIGHT_SOFT_WARM'],
  '@TIME_DUSK':      ['@LIGHT_GOLDEN', '@LIGHT_RIM', '@LIGHT_BACK', '@LIGHT_SOFT_WARM'],
  '@TIME_TWILIGHT':  ['@LIGHT_GOLDEN', '@LIGHT_RIM', '@LIGHT_BACK', '@LIGHT_NEON', '@LIGHT_NIGHT'],
  '@TIME_BLUE':      ['@LIGHT_RIM', '@LIGHT_BACK', '@LIGHT_NEON', '@LIGHT_NIGHT'],
  '@TIME_NIGHT':     ['@LIGHT_NEON', '@LIGHT_CANDLE', '@LIGHT_TOP', '@LIGHT_STUDIO', '@LIGHT_NIGHT', '@LIGHT_RIM'],
  '@TIME_NOON':      ['@LIGHT_WIN', '@LIGHT_TOP', '@LIGHT_SIDE'],
  '@TIME_DAWN':      ['@LIGHT_RAY', '@LIGHT_BACK', '@LIGHT_SOFT']
};

const RAND_CAM_BY_FRAME = {
  near: ['@CAM_BUST', '@CAM_CLOSEUP', '@CAM_EXTREME_CU', '@CAM_PROFILE', '@CAM_HIP', '@CAM_EYE', '@CAM_SHOULDER', '@CAM_WINDOW', '@CAM_DOORWAY', '@CAM_DUTCH_CLOSE', '@CAM_LENS_SWIRL_BOKEH', '@CAM_LENS_SOFT_DIFFUSION', '@CAM_FOCAL_85MM'],
  mid:  ['@CAM_MEDIUM', '@CAM_COWBOY', '@CAM_THREEQ', '@CAM_HIGH', '@CAM_LOW_THREEQ', '@CAM_EYE', '@CAM_KNEE', '@CAM_CORNER', '@CAM_WINDOW', '@CAM_DOORWAY', '@CAM_TELE', '@CAM_WAIST_SIDE', '@CAM_REFLECTION_LOW', '@CAM_PEEP_FOLIAGE', '@CAM_LENS_ANAMORPHIC', '@CAM_FOCAL_35MM', '@CAM_FOCAL_50MM', '@CAM_FOCAL_135MM', '@CAM_SIDE_TRACKING'],
  far:  ['@CAM_FULL', '@CAM_FULL_WIDE', '@CAM_ESTABLISH', '@CAM_HIGH_WIDE', '@CAM_LOW_WIDE', '@CAM_SIDE_FAR', '@CAM_BACKSIDE', '@CAM_BACK_FAR', '@CAM_WIDE', '@CAM_GROUND', '@CAM_WORM', '@CAM_THREEQ_WIDE', '@CAM_LENS_FISHEYE', '@CAM_LENS_TILTSHIFT', '@CAM_FOCAL_14MM', '@CAM_FOCAL_24MM', '@CAM_ISOMETRIC', '@CAM_LOW_FLOOR_TILT']
};

const RAND_COMP_BY_FRAME = {
  near: ['@COMP_CENTER', '@COMP_THIRDS', '@COMP_GOLDEN', '@COMP_FRAME', '@COMP_FRAMEINFRAME', '@COMP_GLASS_LAYER', '@COMP_EDGE_ANCHOR', '@COMP_LOOKROOM', '@COMP_DIAGONAL', '@COMP_DEPTH_SANDWICH', '@COMP_TIGHT_OVERLAP'],
  mid:  ['@COMP_THIRDS', '@COMP_GOLDEN', '@COMP_LEADING', '@COMP_LAYERS', '@COMP_FRAME', '@COMP_FRAMEINFRAME', '@COMP_GLASS_LAYER', '@COMP_EDGE_ANCHOR', '@COMP_HEADROOM', '@COMP_CURVE', '@COMP_DIAGONAL', '@COMP_TRIANGLE', '@COMP_NEGATIVE', '@COMP_FOREGROUND', '@COMP_GOLDEN_SPIRAL', '@COMP_DEPTH_SANDWICH', '@COMP_DIAGONAL_SHADOW', '@COMP_V_FRAME', '@COMP_RADIAL_BURST', '@COMP_LAYERED_PORTAL', '@COMP_TIGHT_OVERLAP'],
  far:  ['@COMP_WIDE', '@COMP_VAST', '@COMP_HEADROOM', '@COMP_LEADING', '@COMP_SYMMETRY', '@COMP_HORIZON_HIGH', '@COMP_HORIZON_LOW', '@COMP_LAYERS', '@COMP_SILHOUETTE', '@COMP_MINIMAL', '@COMP_REFLECTION', '@COMP_FIGURE_1_3', '@COMP_FIGURE_1_4', '@COMP_FIGURE_SMALL', '@COMP_FIGURE_BOTTOM', '@COMP_FIGURE_EDGE', '@COMP_GOLDEN_SPIRAL', '@COMP_DIAGONAL_SHADOW', '@COMP_V_FRAME', '@COMP_RADIAL_BURST', '@COMP_OFF_BALANCE', '@COMP_LAYERED_PORTAL', '@COMP_LOW_CLEAR_SKY']
};
