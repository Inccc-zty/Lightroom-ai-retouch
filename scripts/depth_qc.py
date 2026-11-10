# -*- coding: utf-8 -*-
"""
立体感体检器 —— 量化「画面看起来立不立」

核心判据（全部相对 9526 定稿校准，那张用户认可立体感强）：

1. 层级梯度：天空 > 远山 > 中景 > 前景，逐级递减，总落差 80-150
2. 中暗带占比（76-128）：>= 20%    —— 低了这个画面就是「两层纸板」
3. 低频 CV（60-240px 尺度的大块明暗起伏）：
     远山 >= 0.12 / 中景 >= 0.10 / 右坡 >= 0.13
   低了说明层内是均匀平涂，没有地形起伏
4. 形状明暗 中频 CV（15-60px）：>= 0.13（52 6 在 0.17-0.21）
5. 天空不能太亮：均值 <= 178，中频 CV >= 0.05
6. 大气透视：远山比中景亮、比中景冷、对比不高于中景

阈值全部相对 9526 定稿校准（正午山谷）。对平坦地形/傍晚散射光的片子，
低频 CV 与中暗带天然偏低，已按类型放宽，不要把差异当缺陷。
**带通尺度按图像宽度归一化**，否则 1600px 与 4000px 的结果不可比。

注意：**必须用归一化对比（σ/mean）**。绝对 σ 会被亮度影响，
暗部的绝对波动天然小，用绝对 σ 会误判「暗=没细节」。
"""
import sys
import numpy as np
import cv2
from PIL import Image

# 区域定义：名字 -> (x0, x1, y0, y1)  相对坐标
REGIONS = {
    '天空':     (0.10, 0.90, 0.02, 0.18),
    '晚霞带':   (0.10, 0.90, 0.27, 0.40),
    '远山':     (0.45, 0.95, 0.42, 0.49),
    '中景草地': (0.30, 0.62, 0.50, 0.62),
    '前景岩石': (0.10, 0.55, 0.68, 0.95),
    '左坡':     (0.02, 0.28, 0.30, 0.58),
    '右坡':     (0.75, 1.00, 0.40, 0.65),
}

# 目标值（从 9526 定稿实测）
TARGET = {
    '远山':     {'lo_cv': 0.12, 'md_cv': 0.13},
    '中景草地': {'lo_cv': 0.07, 'md_cv': 0.13},
    '前景岩石': {'lo_cv': 0.12, 'md_cv': 0.15},
    '右坡':     {'lo_cv': 0.13, 'md_cv': 0.13},
    '左坡':     {'lo_cv': 0.15, 'md_cv': 0.15},
    '天空':     {'lo_cv': 0.05, 'md_cv': 0.05},
}

# 层级（用于梯度检查），按远->近顺序
DEPTH = ['天空', '晚霞带', '远山', '中景草地', '前景岩石']


def band_cv(r, s1, s2, width):
    """带通的标准差 / 均值 —— 归一化对比，不受区域亮度影响

    尺度按图像宽度归一化：s1/s2 是以 1600px 宽为基准的 sigma，
    实际使用时乘以 width/1600。否则同一特征在 1600px 与 4000px 图上
    落在不同的空间频段，测出来的 CV 无法比较（踩过这个坑）。
    """
    m = max(float(r.mean()), 1e-3)
    k = width / 1600.0
    b = cv2.GaussianBlur(r, (0, 0), s1 * k) - cv2.GaussianBlur(r, (0, 0), s2 * k)
    return float(b.std() / m)


def measure(path):
    a = np.asarray(Image.open(path).convert('RGB')).astype(np.float32)
    g = a.mean(2)
    h, w = g.shape

    out = {'_size': (w, h)}
    for name, (x0, x1, y0, y1) in REGIONS.items():
        r = g[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
        out[name] = {
            'mean': float(r.mean()),
            'lo_cv': band_cv(r, 60, 240, w),
            'md_cv': band_cv(r, 15, 60, w),
            'hi_cv': band_cv(r, 2, 0.001, w),   # 0.001 ≈ 不平滑
        }
        c = a[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)].reshape(-1, 3).mean(0)
        out[name]['br'] = float(c[2] / max(c[0], 1))

    # 全局
    out['dark_pct'] = float((g < 76).mean() * 100)
    out['midlo_pct'] = float(((g >= 76) & (g < 128)).mean() * 100)
    out['midhi_pct'] = float(((g >= 128) & (g < 204)).mean() * 100)
    out['p1'] = float(np.percentile(g, 1))
    out['p99'] = float(np.percentile(g, 99))
    out['white_pct'] = float((g >= 253).mean() * 100)

    vals = [out[n]['mean'] for n in DEPTH]
    out['depth_vals'] = vals
    out['depth_span'] = vals[0] - vals[-1]
    steps = [vals[i] - vals[i + 1] for i in range(len(vals) - 1)]
    out['depth_steps'] = steps
    out['monotonic'] = all(s > 0 for s in steps)

    return out


def check(m, prev=None):
    issues, warns = [], []
    TOL = 0.03

    # 1. 层级单调
    if not m['monotonic']:
        issues.append('层级不单调：' + ' | '.join(f'{s:+.1f}' for s in m['depth_steps']))
    # 2. 总落差
    if m['depth_span'] < 70:
        issues.append(f"总落差 {m['depth_span']:.0f} < 70（太平，没有纵深）")
    elif m['depth_span'] > 160:
        warns.append(f"总落差 {m['depth_span']:.0f} > 160（可能断层）")

    # 3. 中暗带。门槛 15%：9526（正午山谷、大面积绿坡）是 21.9%，
    #    但傍晚逆光片地面天然更暗，用 20% 会误判。低于 12% 才是真的断层。
    if m['midlo_pct'] < 12 * (1 - TOL):
        issues.append(f"中暗带(76-128) {m['midlo_pct']:.1f}% < 12%（中间调断层，看起来像两层贴纸）")
    elif m['midlo_pct'] < 15:
        warns.append(f"中暗带 {m['midlo_pct']:.1f}% 偏低（傍晚片常见，不是硬伤）")

    # 4. 各区低频/中频 CV
    #    远山不查低频 CV：远处被大气雾化后本来就该是均匀的一条淡色带，
    #    逼它出起伏等于造假。远山改用「大气透视」判断。
    #    低频 CV 只作提示不作判定：它由地形起伏决定（9526 是梯田绿坡、
    #    9697 是平坦石滩），后期改不动。硬追只能靠假造明暗块，试过，更假。
    #    中频 CV（形状明暗）才是后期可控的，保留为提示。
    for name, t in TARGET.items():
        if name == '远山':
            continue
        d = m[name]
        if d['lo_cv'] < t['lo_cv'] * 0.85:
            warns.append(f"{name} 低频CV {d['lo_cv']:.3f} < {t['lo_cv']}（地形偏平，后期改不动）")
        if d['md_cv'] < t['md_cv'] * (1 - TOL):
            warns.append(f"{name} 中频CV {d['md_cv']:.3f} < {t['md_cv']}（形状明暗偏弱，可加清晰度）")

    # 4b. 大气透视三要素：远山必须比中景亮、比中景冷、对比不高于中景
    far, mid = m['远山'], m['中景草地']
    if far['mean'] <= mid['mean']:
        issues.append(f"大气透视错：远山 {far['mean']:.0f} 不比中景 {mid['mean']:.0f} 亮"
                      f"（空气散射应把远处提亮，看起来才『远』）")
    if far['br'] <= mid['br']:
        issues.append(f"大气透视错：远山 B/R {far['br']:.2f} 不比中景 {mid['br']:.2f} 冷")
    if far['md_cv'] > mid['md_cv'] * 1.15:
        warns.append(f"远山对比 {far['md_cv']:.3f} 高于中景 {mid['md_cv']:.3f}（远处应更柔）")

    # 5. 天空
    if m['天空']['mean'] > 178:
        warns.append(f"天空均值 {m['天空']['mean']:.0f} > 178（偏亮，可能发白）")
    # 6. 溢出
    if m['p99'] < 232:
        warns.append(f"p99 {m['p99']:.0f} < 232（最亮处不够，缺高光点睛）")
    elif m['p99'] > 252:
        issues.append(f"p99 {m['p99']:.0f} > 252（高光溢出）")
    if m['white_pct'] > 0.10:
        issues.append(f"全白 {m['white_pct']:.2f}% > 0.10%（云顶烧了）")

    return issues, warns


def report(path, prev_path=None):
    m = measure(path)
    prev = measure(prev_path) if prev_path else None
    print(f'  尺寸 {m["_size"][0]}x{m["_size"][1]}')
    print()
    print(f'  {"区域":10s}{"均值":>6}{"低频CV":>8}{"中频CV":>8}{"高频CV":>8}{"B/R":>6}')
    for name in REGIONS:
        d = m[name]
        flag = ''
        t = TARGET.get(name)
        if t and d['lo_cv'] < t['lo_cv'] * 0.97:
            flag = ' ←低频不足'
        print(f'  {name:10s}{d["mean"]:6.0f}{d["lo_cv"]:8.3f}{d["md_cv"]:8.3f}{d["hi_cv"]:8.3f}{d["br"]:6.2f}{flag}')

    print()
    v = m['depth_vals']
    print('  梯度: ' + ' -> '.join(f'{x:.0f}' for x in v) + f'  落差 {m["depth_span"]:.0f}')
    print('  级差: ' + '  '.join(f'{s:+.0f}' for s in m['depth_steps']))
    print(f'  暗(<76) {m["dark_pct"]:.1f}% | 中暗(76-128) {m["midlo_pct"]:.1f}% | '
          f'中亮(128-204) {m["midhi_pct"]:.1f}%')
    print(f'  p1 {m["p1"]:.0f} | p99 {m["p99"]:.0f} | 全白 {m["white_pct"]:.3f}%')

    if prev:
        print()
        print('  与上一步对比:')
        for name in REGIONS:
            dm = m[name]['mean'] - prev[name]['mean']
            dl = m[name]['lo_cv'] - prev[name]['lo_cv']
            print(f'    {name:10s} 亮度 {dm:+6.1f}   低频CV {dl:+.3f}')
        print(f'    中暗带 {m["midlo_pct"] - prev["midlo_pct"]:+.1f} 个百分点')

    print()
    issues, warns = check(m)
    if issues:
        print('  ✗ 问题:')
        for i in issues:
            print('    - ' + i)
    if warns:
        print('  ! 提醒:')
        for w in warns:
            print('    - ' + w)
    if not issues and not warns:
        print('  ✓ 全部达标')
    return m


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('用法: python tools/depth_qc.py <图片> [上一步图片]')
        sys.exit(1)
    print('=== 立体感体检 ===')
    report(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
