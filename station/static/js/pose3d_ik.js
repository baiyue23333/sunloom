// 3D 骨架正/逆向运动学（Two-Bone Analytic IK）与构图透视投影工具
(function () {
  const rad = d => (Number(d) || 0) * Math.PI / 180;
  const deg = r => r * 180 / Math.PI;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  function rotX(a) { const c = Math.cos(a), s = Math.sin(a); return [[1,0,0],[0,c,-s],[0,s,c]]; }
  function rotY(a) { const c = Math.cos(a), s = Math.sin(a); return [[c,0,s],[0,1,0],[-s,0,c]]; }
  function rotZ(a) { const c = Math.cos(a), s = Math.sin(a); return [[c,-s,0],[s,c,0],[0,0,1]]; }
  function mm(A, B) {
    const C = [[0,0,0],[0,0,0],[0,0,0]];
    for (let i=0;i<3;i++) for (let j=0;j<3;j++) C[i][j]=A[i][0]*B[0][j]+A[i][1]*B[1][j]+A[i][2]*B[2][j];
    return C;
  }
  function tr(A) { return [[A[0][0],A[1][0],A[2][0]],[A[0][1],A[1][1],A[2][1]],[A[0][2],A[1][2],A[2][2]]]; }
  function mv(A, v) {
    return [A[0][0]*v[0]+A[0][1]*v[1]+A[0][2]*v[2], A[1][0]*v[0]+A[1][1]*v[1]+A[1][2]*v[2], A[2][0]*v[0]+A[2][1]*v[1]+A[2][2]*v[2]];
  }
  const add = (a, b) => [a[0]+b[0], a[1]+b[1], a[2]+b[2]];
  const sub = (a, b) => [a[0]-b[0], a[1]-b[1], a[2]-b[2]];
  const len3 = v => Math.hypot(v[0], v[1], v[2]);
  function euler(t) {
    const a = Array.isArray(t) ? t : [0,0,0];
    return mm(rotY(rad(a[1])), mm(rotX(rad(a[0])), rotZ(rad(a[2]))));
  }

  function mirrorPose(p) {
    const o = JSON.parse(JSON.stringify(p || {}));
    o.pelvis_yaw = -(Number(o.pelvis_yaw) || 0);
    ['pelvis_tilt','spine','chest','neck','head'].forEach(k => {
      if (Array.isArray(o[k])) o[k] = [o[k][0], -o[k][1], -o[k][2]];
    });
    ['shoulder','elbow','hip','knee','ankle'].forEach(j => {
      const lv = o['l_' + j] || [0,0,0], rv = o['r_' + j] || [0,0,0];
      o['l_' + j] = [rv[0], -rv[1], -rv[2]];
      o['r_' + j] = [lv[0], -lv[1], -lv[2]];
    });
    return o;
  }

  function solveLimbIK(rootWorld, targetWorld, L1, L2, parentRot, isArm) {
    // 把目标向量转入父骨骼局部坐标（局部默认向下 -Y）
    const dW = sub(targetWorld, rootWorld);
    const v = mv(tr(parentRot), dW);
    const maxReach = (L1 + L2) * 0.992;
    const minReach = Math.abs(L1 - L2) + 0.02;
    const d = clamp(len3(v), minReach, maxReach);
    const ux = v[0] / (len3(v) || 1), uy = v[1] / (len3(v) || 1), uz = v[2] / (len3(v) || 1);

    // 余弦定理求肘/膝弯曲角（度，正值）
    const cosB = clamp((L1 * L1 + L2 * L2 - d * d) / (2 * L1 * L2), -1, 1);
    const bend = clamp(180 - deg(Math.acos(cosB)), 2, 130);
    const cosA = clamp((L1 * L1 + d * d - L2 * L2) / (2 * L1 * d), -1, 1);
    const alpha = deg(Math.acos(cosA));

    // 目标方向在局部 (0, -1, 0) 下的欧拉角：先 rz 左右摆，再 rx 前后抬
    const rz = clamp(deg(Math.atan2(ux, -uy)), -85, 85);
    const horiz = Math.hypot(ux, -uy);
    let rx = deg(Math.atan2(-uz, horiz));
    // 肘向后弯(-rx)时上臂往前抬(-alpha)，膝向前弯(+rx)时大腿往前抬(-alpha)
    rx = isArm ? (rx - alpha * 0.65) : (rx - alpha * 0.72);
    rx = clamp(rx, -165, 80);
    return {
      root: [Math.round(rx), 0, Math.round(rz)],
      mid: [Math.round(bend), 0, 0],
    };
  }

  function buildSkeleton(pose, pr, mirror) {
    const p = mirror ? mirrorPose(pose) : pose;
    const pR = mm(rotY(rad(p.pelvis_yaw || 0)), euler(p.pelvis_tilt));
    const pelvis = [0, 0.52, 0];
    const sR = mm(pR, euler(p.spine));
    const cR = mm(sR, euler(p.chest));
    const nR = mm(cR, euler(p.neck));
    const hR = mm(nR, euler(p.head));
    const waist = add(pelvis, mv(pR, [0, 0.095, 0]));
    const chest = add(waist, mv(sR, [0, 0.130, 0]));
    const neckB = add(chest, mv(cR, [0, 0.082, 0]));
    const headC = add(neckB, mv(nR, [0, 0.092, 0]));
    const nose = add(headC, mv(hR, [0, -0.008, (pr.head_r ? pr.head_r[2] : 0.068) * 0.96]));

    const segs = [
      [pelvis, waist, 0.066, '#7d66db'],
      [waist, chest, 0.062, '#8d75ea'],
      [chest, neckB, 0.044, '#9a84f2'],
      [neckB, headC, 0.025, '#8d75ea'],
    ];
    const balls = [
      [pelvis, 0.072, '#7d66db'],
      [chest, 0.070, '#9a84f2'],
      [headC, 0.070, '#a692f6'],
      [nose, 0.013, '#c7f53b'],
    ];
    const handles = [
      { id: 'pelvis', label: '重心/站位', pos: pelvis, r: 0.068, kind: 'move' },
      { id: 'head', label: '头部', pos: headC, r: 0.068, kind: 'head' },
    ];

    [['l', -1, '#7962d6'], ['r', 1, '#9c84f2']].forEach(([sd, sx, col]) => {
      const sh = add(neckB, mv(cR, [sx * (pr.shoulder_w || 0.20) * 0.5, -0.025, 0]));
      const uaR = mm(cR, euler(p[sd + '_shoulder']));
      const el = add(sh, mv(uaR, [0, -(pr.upper_arm[0] || 0.14), 0]));
      const ea = p[sd + '_elbow'] || [20, 0, 0];
      const faR = mm(uaR, euler([-Math.abs(ea[0] || 0), ea[1] || 0, ea[2] || 0]));
      const wr = add(el, mv(faR, [0, -(pr.forearm[0] || 0.13), 0]));
      const hd = add(wr, mv(faR, [0, -0.048, 0]));
      segs.push([sh, el, 0.028, col], [el, wr, 0.023, col], [wr, hd, 0.018, col]);
      balls.push([sh, 0.028, col], [el, 0.024, col]);
      handles.push({ id: sd + '_hand', side: sd, limb: 'arm', rootPos: sh, parentRot: cR, L1: pr.upper_arm[0] || 0.14, L2: pr.forearm[0] || 0.13, pos: wr, r: 0.036, kind: 'ik' });

      const hp = add(pelvis, mv(pR, [sx * (pr.hip_w || 0.14) * 0.5, -0.02, 0]));
      const thR = mm(pR, euler(p[sd + '_hip']));
      const kn = add(hp, mv(thR, [0, -(pr.thigh[0] || 0.215), 0]));
      const ka = p[sd + '_knee'] || [10, 0, 0];
      const cfR = mm(thR, euler([Math.abs(ka[0] || 0), ka[1] || 0, ka[2] || 0]));
      const ak = add(kn, mv(cfR, [0, -(pr.calf[0] || 0.215), 0]));
      const ftR = mm(cfR, euler(p[sd + '_ankle']));
      const toe = add(ak, mv(ftR, [0, -0.02, pr.foot_len || 0.10]));
      segs.push([hp, kn, 0.045, col], [kn, ak, 0.033, col], [ak, toe, 0.024, col]);
      balls.push([kn, 0.034, col]);
      handles.push({ id: sd + '_foot', side: sd, limb: 'leg', rootPos: hp, parentRot: pR, L1: pr.thigh[0] || 0.215, L2: pr.calf[0] || 0.215, pos: ak, r: 0.042, kind: 'ik' });
    });

    return { segs, balls, handles, cR, pR };
  }

  function facingFromYaw(pose, camYaw) {
    const yaw = (((Number(pose && pose.pelvis_yaw) || 0) + (Number(camYaw) || 0)) % 360 + 540) % 360 - 180;
    if (Math.abs(yaw) >= 120) return 'back';
    if (Math.abs(yaw) >= 50) return 'side';
    return 'front';
  }

  const SLIDERS = [
    ['躯干朝向', 'pelvis_yaw', null, -180, 180], ['前后俯仰', 'pelvis_tilt', 0, -45, 45],
    ['胸腔拧转', 'chest', 1, -45, 45], ['头部转向', 'head', 1, -55, 55],
    ['画左臂(角右)抬举', 'l_shoulder', 0, -165, 80], ['画左臂(角右)外展', 'l_shoulder', 2, -85, 25],
    ['画左肘弯曲', 'l_elbow', 0, 0, 130], ['画右臂(角左)抬举', 'r_shoulder', 0, -165, 80],
    ['画右臂(角左)外展', 'r_shoulder', 2, -25, 85], ['画右肘弯曲', 'r_elbow', 0, 0, 130],
    ['画左腿(角右)抬起', 'l_hip', 0, -110, 60], ['画左膝弯曲', 'l_knee', 0, 0, 130],
    ['画右腿(角左)抬起', 'r_hip', 0, -110, 60], ['画右膝弯曲', 'r_knee', 0, 0, 130],
  ];

  window.POSE3D_IK = {
    rad, deg, clamp, rotX, rotY, rotZ, mm, tr, mv, add, sub, euler,
    mirrorPose, solveLimbIK, buildSkeleton, facingFromYaw, SLIDERS,
  };
})();
