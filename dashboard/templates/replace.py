import re

with open('c:/Git/portfolio-tracker/dashboard/templates/index.html', 'r', encoding='utf-8') as f:
    code = f.read()

code = re.sub(
    r'function renderSecured\(\) \{[\s\S]*?renderPremiumTables\(\);\s*\}',
    'function renderSecured() {\n  if (!_wheelCfg || !_appData) return;\n  if (!document.getElementById(\'securedChart\')) return;\n  renderSecuredChart();\n  renderPremiumTables();\n}',
    code
)

start_idx = code.find('function _wheelObligByStrike(type) {')
if start_idx != -1:
    put_start = code.find('// Puts secured (wheel only):', start_idx)
    end_call = code.find('loadData();', put_start)
    if put_start != -1 and end_call != -1:
        new_funcs = '''function renderSecuredChart() {
  // ---- 1. Puts Logic ----
  const putByStrike = _wheelObligByStrike('P');
  const planByLevel = {};
  (_wheelCfg.items || []).forEach(it => {
    if (it.qty && (it.type === 'long_call' || it.type === 'long_future'))
      planByLevel[it.level] = (planByLevel[it.level] || 0) + it.qty;
  });
  const putPoints = [...new Set([
    ...Object.keys(putByStrike).map(Number), ...Object.keys(planByLevel).map(Number),
  ])].sort((a, b) => a - b);
  
  let putCarry = 0, putOverCount = 0, putWorstOver = 0;
  const putByK = {};
  [...putPoints].sort((a, b) => b - a).forEach(K => {
    const plan = planByLevel[K] || 0;
    const frame = plan + putCarry;
    const pb = putByStrike[K] || { pos: 0, ord: 0 };
    const oblig = pb.pos + pb.ord; 
    const gap = frame - oblig; 
    if (gap < -1e-9) { putOverCount++; putWorstOver = Math.max(putWorstOver, -gap); }
    putCarry = gap;
    putByK[K] = { pos: pb.pos, ord: pb.ord, oblig, gap };
  });

  const putVEl = document.getElementById('sec-put-verdict');
  if (!putPoints.length) { putVEl.className = 'sec-verdict'; putVEl.innerHTML = 'No wheel puts.'; }
  else if (putOverCount === 0) {
    putVEl.className = 'sec-verdict ok';
    putVEl.innerHTML = '\\u2705 Put Secured — within planned cover';
  } else {
    putVEl.className = 'sec-verdict warn';
    putVEl.innerHTML = '\\u26A0 ' + putOverCount + ' Put strike(s) exceed cover (worst \\u2212' + putWorstOver.toFixed(2) + ' BTC gap)';
  }

  // ---- 2. Calls Logic ----
  const X = _wheelCfg.current_level == null ? null : _wheelCfg.current_level;
  const usableBtc = (_wheelCfg.external_btc || 0) + deribitBalance();
  const floor = X == null ? 60000 : X;
  let base_gap = Infinity;
  for (let P = 100000; P <= W_XMAX; P += 2000) {
    if (P < floor) continue;
    const g = equityAt(P, X, usableBtc) - minAt(P);
    if (g < base_gap) { base_gap = g; }
  }
  if (base_gap === Infinity) base_gap = 0;
  
  const sign = base_gap >= 0 ? '+' : '';
  const gapColor = base_gap >= 0 ? '#3fb950' : '#f85149';
  const callLvlEl = document.getElementById('sec-call-lvl');
  if(callLvlEl) callLvlEl.innerHTML = 'Strategy Base Gap (>100k): <span style="color:' + gapColor + '; font-weight:bold;">' + sign + base_gap.toFixed(3) + ' BTC</span>';
  
  const callByStrike = _wheelObligByStrike('C');
  const callPoints = Object.keys(callByStrike).map(Number).sort((a, b) => a - b);
  
  let callCarry = 0, callOverCount = 0, callWorstOver = 0;
  const callByK = {};
  callPoints.forEach((K, index) => {
    const plan = (index === 0) ? base_gap : 0;
    const frame = plan + callCarry;
    const pb = callByStrike[K] || { pos: 0, ord: 0 };
    const oblig = pb.pos + pb.ord; 
    const gap = frame - oblig; 
    if (gap < -1e-9) { callOverCount++; callWorstOver = Math.max(callWorstOver, -gap); }
    callCarry = gap;
    callByK[K] = { pos: pb.pos, ord: pb.ord, oblig, gap };
  });

  const callVEl = document.getElementById('sec-call-verdict');
  if (!callPoints.length) { 
    callVEl.className = 'sec-verdict'; 
    callVEl.innerHTML = 'No wheel calls.';
  } else if (callOverCount === 0) {
    callVEl.className = 'sec-verdict ok';
    callVEl.innerHTML = '\\u2705 Call Secured — within cover';
  } else {
    callVEl.className = 'sec-verdict warn';
    callVEl.innerHTML = '\\u26A0 ' + callOverCount + ' Call strike(s) exceed cover (worst \\u2212' + callWorstOver.toFixed(2) + ' BTC gap)';
  }

  // ---- 3. Combine Data for Chart ----
  const labels = [];
  const posX = [];
  const ordX = [];
  const spareX = [];
  const overFlag = [];
  const annotations = [];
  
  const fmtBar = v => Math.abs(v) > 1e-9 ? v.toFixed(2) : '';

  putPoints.forEach(K => {
    labels.push((K / 1000) + 'k P');
    const r = putByK[K];
    posX.push(r.pos);
    ordX.push(r.ord);
    spareX.push(Math.max(r.gap, 0));
    overFlag.push(r.gap < -1e-9);
    annotations.push({
      x: (K / 1000) + 'k P', y: r.oblig + Math.max(r.gap, 0), yanchor: 'bottom', yshift: 4,
      text: '<b>gap ' + (r.gap >= 0 ? '+' : '') + r.gap.toFixed(2) + '</b>', showarrow: false,
      font: { size: 18, color: r.gap < -1e-9 ? '#f85149' : '#e6edf3' }
    });
  });

  callPoints.forEach(K => {
    labels.push((K / 1000) + 'k C');
    const r = callByK[K];
    posX.push(r.pos);
    ordX.push(r.ord);
    spareX.push(Math.max(r.gap, 0));
    overFlag.push(r.gap < -1e-9);
    annotations.push({
      x: (K / 1000) + 'k C', y: r.oblig + Math.max(r.gap, 0), yanchor: 'bottom', yshift: 4,
      text: '<b>gap ' + (r.gap >= 0 ? '+' : '') + r.gap.toFixed(2) + '</b>', showarrow: false,
      font: { size: 18, color: r.gap < -1e-9 ? '#f85149' : '#e6edf3' }
    });
  });

  if (!labels.length) {
    _securedEl = document.getElementById('securedChart');
    if (_securedEl) Plotly.purge(_securedEl);
    return;
  }

  const traces = [
    { type: 'bar', name: 'position', x: labels, y: posX,
      marker: { color: overFlag.map(f => f ? '#cb2431' : '#238636') },
      text: posX.map(fmtBar), textposition: 'inside',
      insidetextanchor: 'middle', textfont: { size: 16, color: '#ffffff', weight: 'bold' },
      hovertemplate: 'position %{y:.2f} BTC<extra></extra>' },
    { type: 'bar', name: 'order', x: labels, y: ordX,
      marker: { color: overFlag.map(f => f ? '#b31d28' : '#196c2e'),
                pattern: { shape: '/', size: 4, solidity: 0.35 } },
      text: ordX.map(fmtBar), textposition: 'inside',
      insidetextanchor: 'middle', textfont: { size: 16, color: '#ffffff', weight: 'bold' },
      hovertemplate: 'order %{y:.2f} BTC<extra></extra>' },
    { type: 'bar', name: 'cover (spare)', x: labels, y: spareX,
      marker: { color: 'rgba(0,0,0,0)', line: { color: '#8b949e', width: 1.5 } },
      hovertemplate: 'spare cover %{y:.2f} BTC<extra></extra>' },
  ];

  const shapes = [];
  if (putPoints.length > 0 && callPoints.length > 0) {
    shapes.push({
      type: 'line',
      x0: putPoints.length - 0.5,
      x1: putPoints.length - 0.5,
      y0: 0,
      y1: 1,
      yref: 'paper',
      line: { color: '#8b949e', width: 2, dash: 'dash' }
    });
  }

  const layout = {
    paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
    font: { color: '#e6edf3', size: 11 }, margin: { l: 46, r: 12, t: 22, b: 34 }, autosize: true,
    barmode: 'stack',
    uniformtext: { minsize: 16, mode: 'show' },
    xaxis: { title: 'Strikes (Puts -> Calls)', type: 'category', categoryorder: 'array', categoryarray: labels, gridcolor: '#30363d' },
    yaxis: { title: 'BTC', gridcolor: '#30363d', zerolinecolor: '#8b949e', rangemode: 'tozero' },
    legend: { font: { size: 9 }, bgcolor: 'transparent', orientation: 'h', y: -0.16 },
    annotations,
    shapes
  };
  
  _securedEl = document.getElementById('securedChart');
  Plotly.newPlot(_securedEl, traces, layout, { displayModeBar: false, responsive: true })
    .then(() => Plotly.Plots.resize(_securedEl));
  if (!_securedObserver) {
    _securedObserver = new ResizeObserver(() => { if (_securedEl.data) Plotly.Plots.resize(_securedEl); });
    _securedObserver.observe(_securedEl);
  }
}

'''
        code = code[:put_start] + new_funcs + code[end_call:]
        with open('c:/Git/portfolio-tracker/dashboard/templates/index.html', 'w', encoding='utf-8') as f:
            f.write(code)
        print('Successfully replaced functions.')
    else:
        print('Could not find put_start or end_call')
else:
    print('Could not find _wheelObligByStrike')
