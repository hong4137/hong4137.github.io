// ═══════════════════════════════════════════════════════════
// 메인 대시보드 PC 화면 (768px 이상) — 2026-11-19 개편
// 정본 시안: 통합 개발/대시보드개편/시안-v2.html
// 모든 칸은 지금 사이트가 쓰는 실제 데이터로만 채운다 (지어낸 내용 금지).
//   외신 브리핑  news.sharktalk.co.kr/list.json
//   UptoDate     signal.sharktalk.co.kr/data/front.json
//   경제 일정    ./catalysts.json   (D-day 는 오늘 기준 계산, 지난 일정은 뺀다)
//   스포츠       ./sports.json · ./korean_overseas.json
//   시장         TradingView 위젯 (종목은 옛 화면과 같은 localStorage 'dashboard_stocks')
//   날씨         open-meteo
//   관제실       vaaj-35yd.sharktalk.co.kr/api/status (같은 .sharktalk.co.kr 쿠키)
// ═══════════════════════════════════════════════════════════
(function () {
  'use strict';
  var MQ = window.matchMedia('(min-width: 768px)');
  var started = false;

  // ── 바로가기 정의 ──────────────────────────────────────────
  // [이름, 아이콘, 숫자키, 주소, 관제실 id(들)]
  var MINE = [
    ['매체', [
      ['Daily UptoDate', 'paper', '1', 'https://signal.sharktalk.co.kr/front.html', ['uptodate']],
      ['외신 브리핑', 'globe', '2', 'https://news.sharktalk.co.kr/', ['news']],
      ['카드뉴스', 'cards', '', 'https://news.sharktalk.co.kr/cards/', ['cards']],
      ['Must News', 'rank', '', 'https://must.sharktalk.co.kr/', ['must']],
      ['Signal', 'wave', '', 'https://signal.sharktalk.co.kr/', ['signal']],
      ['경제 브리핑', 'bars', '9', 'https://econ.sharktalk.co.kr/', ['econ']]]],
    ['투자', [
      ['투자 노트', 'note', '3', 'https://cio.sharktalk.co.kr/', ['cio']],
      ['거래소', 'swap', '4', 'https://exchange.sharktalk.co.kr/', ['paper']],
      ['Investment Map', 'map', '7', 'https://map.sharktalk.co.kr/', ['map']],
      ['NDX Watch', 'gauge', '', 'https://ndx.sharktalk.co.kr/', ['ndx']]]],
    ['공부', [
      ['시사상식 다이어리', 'bulb', '', 'https://sisa.sharktalk.co.kr/', ['sisa']],
      ['서재', 'shelf', '', 'https://read.sharktalk.co.kr/', ['read']]]],
    ['가족', [
      ['School ToDo', 'pack', '5', 'https://hong4137.github.io/schooltodo/', ['school', 'school-bot']],
      ['도형 놀이터', 'shapes', '6', 'https://shape.sharktalk.co.kr/', ['shape']],
      ['바둑 공부', 'stones', '', 'https://baduk.sharktalk.co.kr/', ['baduk']],
      ['아이 독서기록', 'kidbook', '', 'https://kid.sharktalk.co.kr/', ['kid']]]],
    ['생활', [
      ['밑줄', 'under', '', 'https://books.sharktalk.co.kr/', ['books']],
      ['약속 잡기', 'cal', '8', 'https://when.sharktalk.co.kr/', ['when']],
      ['포털', 'flame', '', 'https://sharktalk.co.kr/', ['portal']],
      ['관제실', 'radar', '', 'https://vaaj-35yd.sharktalk.co.kr/', ['ops']]]]
  ];
  var GLABEL = { 매체: '매체', 투자: '투자', 공부: '공부', 가족: '아이·가족', 생활: '생활' };
  var TINT = { 매체: '#FF9A5C', 투자: '#6CB6FF', 공부: '#B79CFF', 가족: '#F5C85B', 생활: '#B9C3D1' };
  var WORK = [
    ['티타임즈 CMS', 'pen', 'https://ttimesvibe.github.io/main/'],
    ['VOD 전달', 'play', 'https://hong4137.github.io/mgmt-2026/'],
    ['이벤터스', 'fav:f05.png', 'https://event-us.kr/']
  ];
  // 파비콘 파일은 일부러 중립 이름(f01…) — github.png·gmail.png 같은 이름은 광고 차단 확장이 막아 흰 칸이 됐다(11-20)
  var EXT = [
    ['GitHub', 'f06.png', 'https://github.com/hong4137'],
    ['클라우드플레어', 'f03.png', 'https://dash.cloudflare.com/'],
    ['수파베이스', 'f11.png', 'https://supabase.com/'],
    ['클로드', 'f02.png', 'https://claude.ai'],
    ['지메일', 'f07.png', 'https://mail.google.com/'],
    ['Outlook', 'f10.jpg', 'https://outlook.office.com/'],
    ['네이버', 'f09.png', 'https://www.naver.com/'],
    ['다음', 'f04.png', 'https://www.daum.net/'],
    ['LinkedIn', 'f08.png', 'https://www.linkedin.com/'],
    ['챗GPT', 'f01.png', 'https://chatgpt.com/']
  ];
  var OPS_URL = 'https://vaaj-35yd.sharktalk.co.kr/';

  // 선 아이콘 (stroke, 24 격자)
  var P = {
    paper: '<path d="M4 5h13v14a1 1 0 0 0 1 1H6a2 2 0 0 1-2-2z"/><path d="M17 9h3v9a2 2 0 0 1-2 2"/><path d="M7 8h7M7 12h7M7 16h4"/>',
    globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.6 2.6 14.4 0 17M12 3.5c-2.6 2.6-2.6 14.4 0 17"/>',
    bars: '<path d="M4 20h16"/><path d="M7 16v-5M12 16V7M17 16v-8"/>',
    bulb: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>',
    note: '<rect x="5" y="3.5" width="14" height="17" rx="2"/><path d="m8 15 3-3 2 2 3-4"/>',
    map: '<path d="m3.5 6.5 5.5-2.5 6 2.5 5.5-2.5v13.5l-5.5 2.5-6-2.5-5.5 2.5z"/><path d="M9 4v13.5M15 6.5V20"/>',
    gauge: '<path d="M4.5 16a8 8 0 1 1 15 0"/><path d="m12 16 4-5"/><circle cx="12" cy="16" r="1.2"/>',
    swap: '<path d="M5 8h13l-3.5-3.5M19 16H6l3.5 3.5"/>',
    pack: '<path d="M7 8a5 5 0 0 1 10 0v11a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1z"/><path d="M10 4.5V3h4v1.5M7 13h10M11 13v2h2v-2"/>',
    shapes: '<path d="m7 3.5 4.5 7.5h-9z"/><circle cx="16.5" cy="7.5" r="3.5"/><rect x="8" y="14" width="7" height="7" rx="1"/>',
    cal: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/><path d="m9 15 2 2 4-4"/>',
    flame: '<path d="M12 3c1.2 3.8 5.2 5.8 5.2 10.2a5.2 5.2 0 0 1-10.4 0c0-2.4 1.4-3.6 2-5.2 1 1 1.6 2 1.6 3.1 1-1.6 1.6-4.1 1.6-8.1z"/>',
    pen: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    cards: '<rect x="7" y="3.5" width="12" height="15" rx="2"/><path d="M5 7v12a2 2 0 0 0 2 2h9"/>',
    rank: '<path d="M5 20V12M12 20V5M19 20v-5"/><path d="M3 20h18"/>',
    wave: '<path d="M3 12h3l2.5-6 4 12 3-8 2 2H21"/>',
    stones: '<path d="M4 8h16M4 16h16M8 4v16M16 4v16"/><circle cx="8" cy="8" r="2.2" fill="currentColor"/><circle cx="16" cy="16" r="2.2"/>',
    shelf: '<path d="M5 4v16M9 4v16M13.5 5l4.5 14.5"/><path d="M3.5 20h17"/>',
    kidbook: '<path d="M12 7c-2-1.5-5-2-8-1.5v12c3-.5 6 0 8 1.5 2-1.5 5-2 8-1.5v-12C17 5 14 5.5 12 7z"/><path d="M12 7v12"/>',
    under: '<path d="M7 4v7a5 5 0 0 0 10 0V4"/><path d="M5 20h14"/>',
    radar: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><path d="M12 12 18 6"/>',
    play: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="m10.5 9.5 4 2.5-4 2.5z"/>'
  };

  // ── 작은 도구 ──────────────────────────────────────────────
  function $(id) { return document.getElementById(id); }
  function el(t, c, txt) { var e = document.createElement(t); if (c) e.className = c; if (txt != null) e.textContent = txt; return e; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function svg(k) { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + P[k] + '</svg>'; }
  function getJSON(url, opts) { return fetch(url, opts || {}).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }); }
  function bust(u) { return u + (u.indexOf('?') < 0 ? '?' : '&') + 'v=' + Date.now(); }
  // 서울 기준 오늘 (자정)
  function seoulYMD(d) { return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(d || new Date()); }
  function dayDiff(ymd) { var a = Date.parse(seoulYMD() + 'T00:00:00Z'), b = Date.parse(ymd + 'T00:00:00Z'); return Math.round((b - a) / 864e5); }
  // "MM.DD" (연도 없음) → 오늘 기준 앞뒤 반년 안에서 가장 가까운 날짜의 일수 차
  function mdDiff(md) {
    var m = /^(\d{1,2})\.(\d{1,2})/.exec(md || ''); if (!m) return null;
    var y = +seoulYMD().slice(0, 4), best = null;
    [y - 1, y, y + 1].forEach(function (yy) {
      var n = dayDiff(yy + '-' + ('0' + m[1]).slice(-2) + '-' + ('0' + m[2]).slice(-2));
      if (best === null || Math.abs(n) < Math.abs(best)) best = n;
    });
    return best;
  }
  // "2026-11-19 16:09:46 KST" → 몇 시간 전
  function ageHours(kst) { var m = /(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/.exec(kst || ''); if (!m) return null; return (Date.now() - Date.parse(m[1] + 'T' + m[2] + ':00+09:00')) / 36e5; }
  function md(ymd) { return ymd.slice(5, 7) + '.' + ymd.slice(8, 10); }
  function staleTag(txt) { var s = el('span', 'stale', txt); return s; }

  // ── 토스트 없이: 링크는 새 탭 ──────────────────────────────
  function openUrl(u) { window.open(u, '_blank', 'noopener'); }

  // ── 런처 ───────────────────────────────────────────────────
  var CHIP_BY_ID = {}; // 관제실 id → [chip 요소]
  var PAL_ITEMS = [], NEWS_PAL = [];
  function chip(name, iconKey, url, opts) {
    opts = opts || {};
    var a = el('a', 'chip'); a.href = url; a.target = '_blank'; a.rel = 'noopener'; a.title = name;
    var s = el('span', 'ico');
    if (iconKey.indexOf('.') > 0) { // 파비콘 파일
      s.className = 'ico fav'; var im = document.createElement('img'); im.alt = ''; im.width = 16; im.height = 16; im.src = '/icons/fav/' + iconKey.replace('fav:', ''); s.appendChild(im);
    } else { s.innerHTML = svg(iconKey); if (opts.tint) s.style.setProperty('--tint', opts.tint); }
    a.appendChild(s);
    a.appendChild(document.createTextNode(name));
    if (opts.key) { a.appendChild(el('span', 'key', opts.key)); a.dataset.key = opts.key; }
    (opts.ids || []).forEach(function (id) { (CHIP_BY_ID[id] = CHIP_BY_ID[id] || []).push(a); });
    return a;
  }
  function buildLauncher() {
    var mine = $('pcMine');
    MINE.forEach(function (g) {
      var c = el('div', 'cluster'); c.appendChild(el('em', '', GLABEL[g[0]]));
      g[1].forEach(function (i) {
        c.appendChild(chip(i[0], i[1], i[3], { key: i[2], tint: TINT[g[0]], ids: i[4] }));
        PAL_ITEMS.push({ t: i[0], s: '내 서비스' + (i[2] ? ' · ' + i[2] : ''), u: i[3] });
      });
      mine.appendChild(c);
    });
    WORK.forEach(function (w) { $('pcWork').appendChild(chip(w[0], w[1], w[2])); PAL_ITEMS.push({ t: w[0], s: '업무', u: w[2] }); });
    EXT.forEach(function (x) { $('pcExt').appendChild(chip(x[0], x[1], x[2])); PAL_ITEMS.push({ t: x[0], s: '외부', u: x[2] }); });
  }

  // ── 관제실: 이상 있을 때만 빨간 점 ──────────────────────────
  // 관제실 대시보드 전용 요약 /api/summary (관제실 713c606). CORS 는 me.sharktalk.co.kr 에만 열려 있다.
  // problems[] = problem:true 인 서비스(breach·down·stale·jobfail). flaky·known·unknown 은 점 없음.
  function loadOps() {
    var pill = $('pcOps'), txt = $('pcOpsTxt');
    fetch(OPS_URL + 'api/summary', { credentials: 'include' }).then(function (r) {
      if (r.status === 401) { var e = new Error('login'); e.login = true; throw e; }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (data) {
      var bad = (data.problems || []).filter(function (s) { return s.problem !== false; });
      if (data.url) pill.href = data.url;
      Object.keys(CHIP_BY_ID).forEach(function (id) { CHIP_BY_ID[id].forEach(function (c) { c.classList.remove('down'); var d = c.querySelector('.badge-dot'); if (d) d.remove(); }); });
      bad.forEach(function (s) {
        (CHIP_BY_ID[s.id] || []).forEach(function (c) {
          c.classList.add('down');
          var d = el('span', 'badge-dot'); c.querySelector('.ico').appendChild(d);
          c.title = c.textContent.replace(/\d$/, '') + ' · ' + (s.label || '이상') + (s.note ? ': ' + s.note : '');
        });
      });
      var n = data.problemCount != null ? data.problemCount : bad.length;
      pill.className = 'ops ' + (n ? 'bad' : 'ok');
      txt.textContent = n ? '관제실 이상 ' + n : '관제실 정상';
      pill.title = n ? bad.map(function (s) { return (s.name || s.id) + ' · ' + (s.label || '') + (s.note ? ' (' + s.note + ')' : ''); }).join('\n') : '모든 점검 정상 · 관제실 열기';
    }).catch(function (e) {
      // 상태를 못 읽으면 아무것도 주장하지 않는다 (초록도 빨강도 아님)
      pill.className = 'ops'; txt.textContent = e && e.login ? '관제실 · 로그인 필요' : '관제실';
      pill.title = '상태를 읽지 못함 · 관제실 열기';
    });
  }

  // ── 맨 위 줄: 날짜·시계 ─────────────────────────────────────
  var CITIES = [['서울', 'Asia/Seoul', 1], ['런던', 'Europe/London', 0], ['뉴욕', 'America/New_York', 0], ['LA', 'America/Los_Angeles', 0]];
  function tickClocks() {
    var ck = $('pcClocks'); ck.innerHTML = ''; var now = new Date();
    CITIES.forEach(function (c) {
      var t = new Intl.DateTimeFormat('en-GB', { timeZone: c[1], hour: '2-digit', minute: '2-digit', hour12: false }).format(now);
      var h = parseInt(t, 10);
      var p = el('div', 'clock' + (c[2] ? ' home' : '') + (!c[2] && h >= 7 && h < 18 ? ' day' : ''));
      p.title = c[2] ? '' : (h >= 7 && h < 18 ? '낮' : '밤');
      p.appendChild(el('small', '', c[0])); p.appendChild(el('span', 'num', t)); ck.appendChild(p);
    });
    $('pcToday').textContent = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', weekday: 'short' }).format(now).replace(/\. ?/g, '.').replace(/\.\(/, ' (');
  }

  // ── 날씨 (open-meteo, 지금 사이트와 같은 출처) ──────────────
  function wIcon(c) { if (c === 0) return 'fa-sun'; if (c >= 1 && c <= 3) return 'fa-cloud-sun'; if (c >= 45 && c <= 48) return 'fa-smog'; if (c >= 51 && c <= 67) return 'fa-cloud-rain'; if (c >= 71 && c <= 77) return 'fa-snowflake'; if (c >= 80 && c <= 82) return 'fa-cloud-showers-heavy'; if (c >= 85 && c <= 86) return 'fa-snowflake'; if (c >= 95) return 'fa-bolt'; return 'fa-cloud'; }
  function wText(c) { if (c === 0) return '맑음'; if (c <= 2) return '구름 조금'; if (c === 3) return '흐림'; if (c >= 45 && c <= 48) return '안개'; if (c >= 51 && c <= 67) return '비'; if (c >= 71 && c <= 77) return '눈'; if (c >= 80 && c <= 82) return '소나기'; if (c >= 85 && c <= 86) return '눈'; if (c >= 95) return '뇌우'; return ''; }
  function loadWeather() {
    getJSON('https://api.open-meteo.com/v1/forecast?latitude=37.5665&longitude=126.9780&current_weather=true&hourly=temperature_2m,weathercode&daily=weathercode,temperature_2m_max,temperature_2m_min&timezone=Asia%2FSeoul&forecast_days=6').then(function (d) {
      var cw = d.current_weather, dl = d.daily, hr = d.hourly;
      var lo0 = Math.round(dl.temperature_2m_min[0]), hi0 = Math.round(dl.temperature_2m_max[0]);
      $('pcWxBtn').innerHTML = '<i class="fas ' + wIcon(cw.weathercode) + '" aria-hidden="true"></i> 서울 <b class="num">' + Math.round(cw.temperature) + '°</b> <span class="num" style="color:var(--muted)">' + lo0 + '° / ' + hi0 + '°</span>';
      var pop = $('pcWxPop');
      var h = '<div style="display:flex;align-items:baseline;gap:10px"><b class="num" style="font-size:26px">' + Math.round(cw.temperature) + '°C</b><span style="color:var(--muted)">서울 · ' + esc(wText(cw.weathercode)) + ' · 바람 ' + cw.windspeed + ' km/h</span></div>';
      // 시간별: 지금 시각 다음부터 3시간 간격 6칸
      var nowKey = cw.time.slice(0, 13); var idx = hr.time.findIndex(function (t) { return t.slice(0, 13) === nowKey; }); if (idx < 0) idx = 0;
      h += '<div class="hours">';
      for (var i = 1; i <= 6; i++) { var k = idx + i * 3; if (!hr.time[k]) break; h += '<div><small class="num">' + hr.time[k].slice(11, 16) + '</small><i class="fas ' + wIcon(hr.weathercode[k]) + '" aria-hidden="true"></i><b class="num">' + Math.round(hr.temperature_2m[k]) + '°</b></div>'; }
      h += '</div><div class="days">';
      var n = Math.min(5, dl.time.length), mn = Infinity, mx = -Infinity;
      for (var j = 0; j < n; j++) { mn = Math.min(mn, dl.temperature_2m_min[j]); mx = Math.max(mx, dl.temperature_2m_max[j]); }
      var span = Math.max(1, mx - mn), wd = ['일', '월', '화', '수', '목', '금', '토'];
      for (var q = 0; q < n; q++) {
        var dt = new Date(dl.time[q] + 'T12:00:00+09:00'), lo = dl.temperature_2m_min[q], hi = dl.temperature_2m_max[q];
        h += '<div class="day-row"><span>' + md(dl.time[q]) + ' ' + wd[dt.getUTCDay()] + '</span><i class="fas ' + wIcon(dl.weathercode[q]) + '" aria-hidden="true"></i><span class="num lo">' + Math.round(lo) + '°</span><span class="track"><i style="left:' + ((lo - mn) / span * 100).toFixed(0) + '%;width:' + Math.max(4, (hi - lo) / span * 100).toFixed(0) + '%"></i></span><span class="num">' + Math.round(hi) + '°</span></div>';
      }
      pop.innerHTML = h + '</div>';
    }).catch(function () { $('pcWxBtn').textContent = '서울 날씨 —'; });
  }

  // ── 외신 브리핑 ───────────────────────────────────────────
  var BRIEF = { groups: {}, order: [], cur: null, open: false };
  var SHOW = 10; // 1열 · 최신 10건 (11-20 사용자: "한 줄만, 너비 줄이고, 최신 10건만")
  function cleanTitle(t) { return String(t || '').replace(/^(외신 브리핑\s*[|\-]\s*|Jae's Briefing\s*-\s*)/, '').replace(/\s*\|\s*주간 외신 브리핑.*$/, '').trim(); }
  function dkey(it) { return ((it.date || '').match(/\d{4}-\d{2}-\d{2}/) || [''])[0]; }
  function loadBriefing() {
    getJSON(bust('https://news.sharktalk.co.kr/list.json')).then(function (data) {
      var g = {};
      data.forEach(function (it) { var k = /^\d{4}-\d{2}/.test(it.date || '') ? it.date.slice(0, 7) : 'special'; (g[k] = g[k] || []).push(it); });
      Object.keys(g).forEach(function (k) { g[k].sort(function (a, b) { return dkey(b).localeCompare(dkey(a)); }); });
      var months = Object.keys(g).filter(function (k) { return k !== 'special'; }).sort().reverse();
      BRIEF.groups = g;
      // 탭: 이번 달 · 특별판 · 지난 달
      var tabs = [];
      if (months[0]) tabs.push({ k: months[0], t: (+months[0].slice(5)) + '월 · ' + g[months[0]].length });
      if (g.special) tabs.push({ k: 'special', t: '특별판 · ' + g.special.length });
      if (months[1]) tabs.push({ k: months[1], t: '지난 달 · ' + g[months[1]].length });
      var tb = $('pcTabs'); tb.innerHTML = '';
      tabs.forEach(function (x, i) {
        var b = el('button', 'tab', x.t); b.type = 'button'; b.setAttribute('role', 'tab'); b.dataset.k = x.k;
        b.addEventListener('click', function () { showBrief(x.k); });
        tb.appendChild(b);
      });
      var latest = months[0] && g[months[0]][0];
      $('pcEd').textContent = latest ? md(dkey(latest)) + ' 판' : '';
      if (latest && dkey(latest) !== seoulYMD()) { $('pcEd').title = '오늘 판은 아직 없음'; }
      if (tabs[0]) showBrief(tabs[0].k);
      // 팔레트에 기사 제목 넣기 (최근 두 달 + 특별판)
      NEWS_PAL = [];
      [months[0], 'special', months[1]].forEach(function (k) { (g[k] || []).forEach(function (it) { NEWS_PAL.push({ t: cleanTitle(it.title), s: '외신 ' + (dkey(it) ? md(dkey(it)) : '특별판'), u: it.link }); }); });
    }).catch(function () { $('pcNews').innerHTML = '<li class="empty">브리핑 목록을 불러오지 못했습니다.</li>'; });
  }
  function showBrief(k) {
    BRIEF.cur = k;
    document.querySelectorAll('#pcTabs .tab').forEach(function (b) { b.setAttribute('aria-selected', String(b.dataset.k === k)); });
    var items = BRIEF.groups[k] || [], ol = $('pcNews'); ol.innerHTML = '';
    var shown = items.slice(0, SHOW);
    var today = seoulYMD();
    shown.forEach(function (it) {
      var li = el('li'), a = el('a'), d = dkey(it);
      a.href = it.link; a.target = '_blank'; a.rel = 'noopener'; a.title = cleanTitle(it.title);
      a.appendChild(el('span', 'd num', d ? md(d) : ''));
      a.appendChild(el('span', 't', cleanTitle(it.title)));
      if (d === today) li.className = 'new';
      li.appendChild(a); ol.appendChild(li);
    });
    $('pcAllLink').textContent = (k === 'special' ? '특별판 ' : (+k.slice(5)) + '월 ') + items.length + '편 모두 보기 →';
  }

  // ── UptoDate 1면 ──────────────────────────────────────────
  function loadFront() {
    getJSON(bust('https://signal.sharktalk.co.kr/data/front.json')).then(function (f) {
      var L = f.lead || {}, box = $('pcUtd');
      if (!L.headline) { box.innerHTML = '<span class="empty" style="padding:0">오늘 1면 정보 없음</span>'; return; }
      box.innerHTML = '';
      // 1면 톱 사진(1면이 쓰는 그 사진·출처 표기 그대로) + 제목 + 부제 + 첫머리
      var im = L.img || {};
      if (im.sm || im.src) {
        var fig = el('figure', 'utd-fig'), pic = document.createElement('img');
        pic.src = im.sm || im.src; pic.alt = im.alt || ''; pic.loading = 'lazy'; pic.referrerPolicy = 'no-referrer';
        pic.onerror = function () { fig.remove(); };
        fig.appendChild(pic);
        if (im.credit || im.nr) fig.appendChild(el('figcaption', '', im.credit || im.nr));
        box.appendChild(fig);
      }
      box.appendChild(el('b', '', L.headline));
      if (L.sub) box.appendChild(el('span', '', L.sub));
      if (L.deck) box.appendChild(el('p', 'deck', L.deck));
      var ed = String(f.edition || ''); // "2026-11-19 07:43"
      var meta = $('pcUtdMeta'); meta.textContent = ed ? ed.slice(11, 16) + ' 판' : '';
      if (ed && ed.slice(0, 10) !== seoulYMD()) { meta.textContent = md(ed.slice(0, 10)) + ' 판'; meta.appendChild(document.createTextNode(' ')); meta.appendChild(staleTag('오늘 판 아직')); }
    }).catch(function () { $('pcUtd').innerHTML = '<span class="empty" style="padding:0">1면을 불러오지 못했습니다.</span>'; });
  }

  // ── 경제 일정 (catalysts) — D-day 는 오늘 기준, 지난 일정은 뺀다 ──
  var CAL_URL = 'https://signal.sharktalk.co.kr/data/calendar.json';
  function loadCalendar() {
    $('pcCalMeta').textContent = '오늘 ' + md(seoulYMD()) + ' 기준';
    // 2026-11-20: 대시보드 전용 수집(catalysts.json)을 끄고 Daily UptoDate 경제 일정 하나로 합쳤다.
    // UptoDate 루틴(06:20)이 오늘~10일 뒤를 쓰고, 1면은 그중 3일치만 싣는다.
    getJSON(bust(CAL_URL)).then(function (p) {
      var ul = $('pcCal'); ul.innerHTML = '';
      var all = (p.events || []).filter(function (e) { return e.verified !== false; })
        .map(function (e) { return { e: e, n: dayDiff(e.date) }; }).filter(function (x) { return x.n >= 0; });
      // 3일 안은 모두, 그 뒤는 중요도 4·5 만 — 가까운 중요도 3 일정이 칸을 다 채우지 않게
      var evs = all.filter(function (x) { return x.n <= 2 || x.e.importance >= 4; }).slice(0, 8);
      if (!evs.length) ul.innerHTML = '<li style="display:block;color:var(--muted)">다가오는 주요 일정 없음</li>';
      evs.forEach(function (x) {
        var e = x.e, li = el('li', e.importance === 5 ? 'imp5' : '');
        li.appendChild(el('span', 'dd' + (x.n <= 3 ? ' soon' : ''), x.n === 0 ? '오늘' : 'D-' + x.n));
        var t = el(e.source ? 'a' : 'span', 'tt', e.title); if (e.source) { t.href = e.source; t.target = '_blank'; t.rel = 'noopener'; }
        t.title = e.title + (e.why ? '\n' + e.why : '') + (e.consensus ? '\n예상 ' + e.consensus : '') + (e.previous ? ' · 직전 ' + e.previous : '');
        li.appendChild(t); li.appendChild(el('span', 'when', md(e.date) + (e.time ? ' ' + e.time : ''))); ul.appendChild(li);
      });
      var age = ageHours(p.generated_at);
      if (age != null && age > 36) { var m = $('pcCalMeta'); m.textContent = ''; m.appendChild(staleTag('갱신 멈춤 · ' + p.generated_at.slice(5, 10).replace('-', '.'))); }
    }).catch(function () { $('pcCal').innerHTML = '<li style="display:block;color:var(--muted)">일정을 불러오지 못했습니다.</li>'; });
  }

  // ── 시장: TradingView (옛 화면과 같은 종목 목록) ─────────────
  function renderMarket(stocks) {
    var c = $('pcTv'); if (!c) return;
    c.innerHTML = '<div class="tradingview-widget-container__widget"></div>';
    var s = document.createElement('script'); s.src = 'https://s3.tradingview.com/external-embedding/embed-widget-market-overview.js'; s.async = true;
    s.innerHTML = JSON.stringify({ colorTheme: 'dark', dateRange: '12M', showChart: true, locale: 'kr', largeChartUrl: '', isTransparent: true, showSymbolLogo: true, showFloatingTooltip: false, width: '100%', height: '100%', plotLineColorGrowing: 'rgba(255,122,46,1)', plotLineColorFalling: 'rgba(255,122,46,1)', belowLineFillColorGrowing: 'rgba(255,122,46,0.10)', belowLineFillColorFalling: 'rgba(255,122,46,0.10)', belowLineFillColorGrowingBottom: 'rgba(255,122,46,0)', belowLineFillColorFallingBottom: 'rgba(255,122,46,0)', gridLineColor: 'rgba(255,255,255,0.04)', scaleFontColor: '#8A96A8', symbolActiveColor: 'rgba(255,122,46,0.12)', tabs: [{ title: '관심 종목', symbols: stocks }] });
    c.appendChild(s);
  }
  window.pcRenderMarket = renderMarket;

  // ── 스포츠 ────────────────────────────────────────────────
  var EPL_KO = { 'Arsenal': '아스널', 'Aston Villa': '애스턴 빌라', 'Bournemouth': '본머스', 'AFC Bournemouth': '본머스', 'Brentford': '브렌트퍼드', 'Brighton & Hove Albion': '브라이턴', 'Brighton': '브라이턴', 'Burnley': '번리', 'Chelsea': '첼시', 'Crystal Palace': '크리스털 팰리스', 'Everton': '에버턴', 'Fulham': '풀럼', 'Leeds United': '리즈', 'Liverpool': '리버풀', 'Manchester City': '맨시티', 'Manchester United': '맨유', 'Newcastle United': '뉴캐슬', 'Nottingham Forest': '노팅엄', 'Sunderland': '선덜랜드', 'Tottenham Hotspur': '토트넘', 'West Ham United': '웨스트햄', 'Wolverhampton Wanderers': '울버햄프턴', 'Ipswich Town': '입스위치', 'Leicester City': '레스터', 'Southampton': '사우샘프턴' };
  var RULE_KO = { 'Big Match': ['빅매치', 1], 'Top Tier': ['상위권 맞대결', 1], 'Challenger': ['상위권 도전', 0], 'Prime Time': ['황금 시간', 0], 'Early KO': ['이른 킥오프', 0], 'Leader': ['선두', 0] };
  function ko(n) { return EPL_KO[n] || n; }
  function row(w, mid, tag, opts) {
    opts = opts || {};
    var r = el('div', 'r'), a = el('span', 'w' + (opts.next ? ' next' : ''), w); r.appendChild(a);
    var m = el('span'); if (typeof mid === 'string') m.textContent = mid; else m.appendChild(mid); m.title = m.textContent; r.appendChild(m);
    if (tag instanceof Node) r.appendChild(tag); else r.appendChild(el('span', 'tag' + (opts.hot ? ' hot' : ''), tag || ''));
    return r;
  }
  function midWithSub(main, sub) { var f = document.createDocumentFragment(), s = el('span'); s.appendChild(document.createTextNode(main + ' ')); s.appendChild(el('span', 'sub', sub)); f.appendChild(s); return s; }
  function renderEPL(e) {
    var box = $('pcEpl'); box.innerHTML = '';
    $('pcEplMeta').textContent = (e && (e.display_matchday || (e.matchday ? 'R' + e.matchday : ''))) || '';
    var ms = (e && e.matches) || [];
    if (!ms.length) { box.appendChild(el('div', 'empty', '이번 라운드 경기 정보 없음')); return; }
    ms = ms.slice().sort(function (a, b) { return String(a.kst_time).localeCompare(String(b.kst_time)); });
    ms.forEach(function (m) {
      var t = String(m.kst_time || '').replace(/\s*\(KST\)\s*/, '');
      var rk = (m.rules || [])[0], rl = RULE_KO[rk] || [rk || '', 0];
      var mid = ko(m.home) + ' vs ' + ko(m.away);
      if (m.status === 'FINISHED' && m.score && m.score !== '-') rl = [m.score, 0];
      box.appendChild(row(t, mid, rl[0], { hot: rl[1] }));
    });
  }
  function renderKorean(list, sportsAge) {
    var box = $('pcKr'); box.innerHTML = '';
    (list || []).slice().sort(function (a, b) { var x = mdDiff(a.kst_date), y = mdDiff(b.kst_date); return (x == null ? 999 : (x < 0 ? 500 + x : x)) - (y == null ? 999 : (y < 0 ? 500 + y : y)); }).forEach(function (p) {
      var n = mdDiff(p.kst_date), stale = n == null || n < 0;
      var vs = (p.venue === 'away' ? '@ ' : 'vs ') + (p.opponent && p.opponent !== '-' ? p.opponent : '미정');
      var comp = String(p.competition || '').replace(/\s*R\d+$/, '');
      var tag = stale ? staleTag('갱신 멈춤') : el('span', 'tag', comp);
      if (stale) tag.title = '수집 실패로 지난 경기가 남아 있음';
      box.appendChild(row((p.kst_date || '-') + ' ' + (p.kst_time && p.kst_time !== '-' ? p.kst_time : ''), midWithSub(p.player, vs), tag));
    });
    if (!box.children.length) box.appendChild(el('div', 'empty', '선수 경기 정보 없음'));
  }
  function renderOverseas(d) {
    var issues = (d && d.hot_issues) || [], players = (d && d.players) || [];
    var foot = $('pcOvFoot'), sum = $('pcOvSum');
    sum.textContent = issues.length ? '🔥 ' + issues[0].headline + (issues.length > 1 ? ' 외 ' + (issues.length - 1) + '건' : '') : '해외파 돋보기 · 특별한 소식 없음 (' + players.length + '명)';
    foot.classList.toggle('hot', !!issues.length);
    var pop = $('pcOvPop'), h = '';
    if (issues.length) { h += '<h3>소식</h3>'; issues.forEach(function (i) { h += '<div class="ov-issue"><b>' + esc(i.headline) + '</b><div>' + esc(i.detail || '') + '</div></div>'; }); h += '<div style="height:10px"></div>'; }
    h += '<h3>해외파 ' + players.length + '명 · 최근/다음 경기</h3>';
    players.forEach(function (p) {
      var src = p.next || p.recent, st = '-';
      if (p.next) st = '예정';
      else if (p.recent) st = p.recent.player_status === 'PLAYED' ? p.recent.minutes + "' " + (p.recent.goals || 0) + 'G ' + (p.recent.assists || 0) + 'A' + (p.recent.rating != null ? ' (' + p.recent.rating + ')' : '') : '결장';
      var res = p.recent && !p.next && p.recent.result ? ' ' + ({ W: '승', L: '패', D: '무' }[p.recent.result] || '') + ' ' + p.recent.team_score + '-' + p.recent.opponent_score : '';
      h += '<div class="ov-row"><b>' + esc(p.player) + '</b><span style="color:var(--muted)">' + esc(src ? src.event : '-') + '</span><span>vs ' + esc(src && src.opponent || '-') + esc(res) + '</span><span class="num" style="color:var(--fg-2)">' + esc(src ? (src.date || '-') + (src.time_kst ? ' ' + src.time_kst : '') : '-') + '</span><span class="st">' + esc(st) + '</span></div>';
    });
    pop.innerHTML = h;
  }
  function renderTennis(t) {
    var box = $('pcTen'); box.innerHTML = '';
    if (!t) { box.appendChild(el('div', 'empty', '정보 없음')); return; }
    var rc = t.recent || {}, nx = t.next || {};
    $('pcTenMeta').textContent = nx.event && nx.event !== '-' ? nx.event : (rc.event || '');
    if (rc.opponent && rc.opponent !== '-') {
      var res = rc.result === 'W' ? '승' : rc.result === 'L' ? '패' : '';
      var tag = el('span', 'num ' + (rc.result === 'W' ? 'up' : rc.result === 'L' ? 'dn' : ''), (res + ' ' + (rc.score || '')).trim());
      box.appendChild(row(rc.date || '', 'vs ' + rc.opponent, tag));
    }
    if (nx.detail && nx.detail !== '-') {
      var mt = String(nx.match_time || 'TBD').replace(/\s*KST$/, '');
      box.appendChild(row(mt === 'TBD' ? '미정' : mt, nx.detail, '다음 경기', { next: true, hot: true }));
    }
    if (!box.children.length) box.appendChild(el('div', 'empty', '정보 없음'));
  }
  var SESS_KO = { 'FP1': 'FP1', 'FP2': 'FP2', 'FP3': 'FP3', 'Qualifying': '예선', 'Sprint Qualifying': '스프린트 예선', 'Sprint': '스프린트', 'Race': '레이스' };
  function renderF1(f) {
    var box = $('pcF1'); box.innerHTML = '';
    if (!f) { box.appendChild(el('div', 'empty', '정보 없음')); return; }
    var nr = f.next_race || {}, st = f.standings || [], sc = f.schedule || [];
    $('pcF1Meta').textContent = (nr.name || '').replace(/ Grand Prix$/, ' GP') + (nr.status ? ' · ' + (nr.status === 'This Week' ? '이번 주' : nr.status) : '');
    var L = el('div'), R = el('div');
    st.slice(0, 5).forEach(function (d, i) { var x = el('div', 'x'); x.appendChild(el('span', 'num', String(d.pos || i + 1))).style.color = 'var(--muted)'; x.appendChild(document.createTextNode((d.driver || '').split(' ').pop())); x.appendChild(el('span', 'num', String(d.points || 0))); L.appendChild(x); });
    if (!st.length) L.appendChild(el('div', 'empty', '순위 준비 중'));
    var year = seoulYMD().slice(0, 4);
    sc.forEach(function (s) {
      var past = false; var m = /^(\d{2})\.(\d{2})$/.exec(s.date || '');
      if (m && s.kst_time) past = Date.parse(year + '-' + m[1] + '-' + m[2] + 'T' + s.kst_time + ':00+09:00') + 2 * 36e5 < Date.now();
      var x = el('div', 'x' + (s.name === 'Race' ? ' race' : /Qualifying/.test(s.name) ? ' q' : '') + (past ? ' past' : ''));
      x.appendChild(el('span', 'num', (s.date || '') + ' ' + (s.kst_time || ''))); x.appendChild(el('span', '', SESS_KO[s.name] || s.name)); R.appendChild(x);
    });
    if (!sc.length) R.appendChild(el('div', 'empty', (nr.date || '일정 미정')));
    box.appendChild(L); box.appendChild(R);
  }
  function loadSports() {
    getJSON(bust('./sports.json')).then(function (d) {
      var age = ageHours(d.updated);
      try { renderEPL(d.epl); } catch (e) { console.error(e); }
      try { renderKorean(d.korean_players, age); } catch (e) { console.error(e); }
      try { renderTennis(d.tennis); } catch (e) { console.error(e); }
      try { renderF1(d.f1); } catch (e) { console.error(e); }
      if (age != null && age > 20) ['pcEplMeta', 'pcTenMeta', 'pcF1Meta'].forEach(function (id) { var m = $(id); m.appendChild(document.createTextNode(' ')); m.appendChild(staleTag('갱신 멈춤')); });
      $('pcSportsAt').textContent = d.updated ? '스포츠 ' + d.updated.slice(5, 16).replace('-', '.') + ' 갱신' : '';
    }).catch(function () { ['pcEpl', 'pcKr', 'pcTen', 'pcF1'].forEach(function (id) { $(id).innerHTML = '<div class="empty">불러오지 못했습니다.</div>'; }); });
    getJSON(bust('./korean_overseas.json')).then(renderOverseas).catch(function () { $('pcOvSum').textContent = '해외파 정보를 불러오지 못했습니다.'; });
  }

  // ── 펼침 상자 (날씨·해외파) ────────────────────────────────
  function popup(btnId, popId, wrapSel) {
    var b = $(btnId), p = $(popId);
    b.addEventListener('click', function () { var o = p.hidden; closePops(); p.hidden = !o; b.setAttribute('aria-expanded', String(o)); });
    POPS.push([b, p, wrapSel]);
  }
  var POPS = [];
  function closePops() { POPS.forEach(function (x) { x[1].hidden = true; x[0].setAttribute('aria-expanded', 'false'); }); }

  // ── 명령 팔레트 + 숫자키 ───────────────────────────────────
  var sel = 0, cur = [];
  function palRender() {
    var q = $('pcPalIn').value.trim().toLowerCase(), pl = $('pcPalList');
    cur = PAL_ITEMS.concat(NEWS_PAL).filter(function (i) { return !q || i.t.toLowerCase().indexOf(q) > -1 || i.s.toLowerCase().indexOf(q) > -1; }).slice(0, 12);
    if (sel >= cur.length) sel = 0;
    pl.innerHTML = '';
    if (!cur.length) { var n = el('li', 'none', '찾는 것이 없습니다'); pl.appendChild(n); return; }
    cur.forEach(function (i, k) {
      var li = el('li'); li.setAttribute('role', 'option'); li.setAttribute('aria-selected', String(k === sel));
      li.appendChild(el('b', '', i.t)); li.appendChild(el('span', '', i.s));
      li.addEventListener('click', function () { palGo(i); }); pl.appendChild(li);
    });
    var s = pl.querySelector('[aria-selected="true"]'); if (s && s.scrollIntoView) s.scrollIntoView({ block: 'nearest' });
  }
  function palOpen() { $('pcPal').hidden = false; $('pcPalIn').value = ''; sel = 0; palRender(); setTimeout(function () { $('pcPalIn').focus(); }, 0); }
  function palClose() { $('pcPal').hidden = true; }
  function palGo(i) { palClose(); openUrl(i.u); }
  function bindKeys() {
    $('pcCmd').addEventListener('click', palOpen);
    $('pcPal').addEventListener('click', function (e) { if (e.target === $('pcPal')) palClose(); });
    $('pcPalIn').addEventListener('input', function () { sel = 0; palRender(); });
    $('pcPalIn').addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { sel = Math.min(sel + 1, cur.length - 1); palRender(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); palRender(); e.preventDefault(); }
      else if (e.key === 'Enter' && cur[sel]) { e.preventDefault(); palGo(cur[sel]); }
      else if (e.key === 'Escape') { palClose(); }
    });
    document.addEventListener('keydown', function (e) {
      if (!MQ.matches) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('pcPal').hidden ? palOpen() : palClose(); return; }
      if (e.key === 'Escape') { closePops(); return; }
      if (!$('pcPal').hidden || e.ctrlKey || e.metaKey || e.altKey) return;
      var tg = e.target.tagName; if (tg === 'INPUT' || tg === 'TEXTAREA' || tg === 'SELECT' || e.target.isContentEditable) return;
      if (document.querySelector('.modal-overlay[style*="flex"]')) return;
      if (/^[1-9]$/.test(e.key)) {
        var c = document.querySelector('#pc .chip[data-key="' + e.key + '"]');
        if (c) { c.classList.add('flash'); setTimeout(function () { c.classList.remove('flash'); }, 400); openUrl(c.href); }
      }
    });
    document.addEventListener('click', function (e) { POPS.forEach(function (x) { if (!x[1].hidden && !e.target.closest(x[2])) { x[1].hidden = true; x[0].setAttribute('aria-expanded', 'false'); } }); });
  }

  // ── 배경: 지금 시각의 실제 낮·밤 경계 (등장방형 도법) ───────
  function sky() {
    var cv = $('sky'), cx = cv.getContext('2d');
    var CITY_LL = [[37.57, 126.98, 1], [51.51, -0.13, 0], [40.71, -74.0, 0], [34.05, -118.24, 0]];
    var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var rad = Math.PI / 180, cache = null, cacheKey = '';
    function sun(d) {
      var n = (d - Date.UTC(2000, 0, 1, 12)) / 864e5; var L = (280.46 + 0.9856474 * n) % 360, g = (357.528 + 0.9856003 * n) % 360;
      var lam = (L + 1.915 * Math.sin(g * rad) + 0.02 * Math.sin(2 * g * rad)) * rad; var eps = 23.439 * rad; var dec = Math.asin(Math.sin(eps) * Math.sin(lam));
      var ut = d.getUTCHours() + d.getUTCMinutes() / 60; var eot = 4 * (L - 0.0057183 - Math.atan2(Math.tan(lam), Math.cos(eps)) / rad); eot = ((eot + 720) % 1440) - 720;
      return { dec: dec, lon: -15 * (ut - 12 + eot / 60) };
    }
    // 낮 쪽 빛·격자는 1분마다 한 번만 다시 그린다 (맥박만 매 프레임)
    function base(W, H) {
      var key = W + 'x' + H + ':' + Math.floor(Date.now() / 6e4);
      if (cache && cacheKey === key) return cache;
      var off = document.createElement('canvas'); off.width = W; off.height = H; var o = off.getContext('2d');
      var s = sun(new Date());
      o.fillStyle = '#0A0D12'; o.fillRect(0, 0, W, H);
      var iw = Math.ceil(W / 8), ih = Math.ceil(H / 8), sm = document.createElement('canvas'); sm.width = iw; sm.height = ih;
      var sc = sm.getContext('2d'), img = sc.createImageData(iw, ih);
      for (var y = 0; y < ih; y++) { var lat = (90 - y / ih * 180) * rad; for (var x = 0; x < iw; x++) { var lon = (x / iw * 360 - 180) * rad;
        var cz = Math.sin(lat) * Math.sin(s.dec) + Math.cos(lat) * Math.cos(s.dec) * Math.cos(lon - s.lon * rad);
        var a = Math.max(0, Math.min(1, (cz + 0.1) / 0.5)); var i = (y * iw + x) * 4; img.data[i] = 40; img.data[i + 1] = 64; img.data[i + 2] = 92; img.data[i + 3] = Math.round(a * 70); } }
      sc.putImageData(img, 0, 0); o.imageSmoothingEnabled = true; o.drawImage(sm, 0, 0, W, H);
      o.strokeStyle = 'rgba(255,255,255,0.03)'; o.lineWidth = 1;
      for (var k = 1; k < 12; k++) { var gx = Math.round(W * k / 12) + .5; o.beginPath(); o.moveTo(gx, 0); o.lineTo(gx, H); o.stroke(); }
      for (var m = 1; m < 6; m++) { var gy = Math.round(H * m / 6) + .5; o.beginPath(); o.moveTo(0, gy); o.lineTo(W, gy); o.stroke(); }
      CITY_LL.forEach(function (c) { var px = (c[1] + 180) / 360 * W, py = (90 - c[0]) / 180 * H; o.fillStyle = c[2] ? '#FF7A2E' : 'rgba(233,238,245,0.45)'; o.beginPath(); o.arc(px, py, c[2] ? 3.5 : 2.5, 0, 7); o.fill(); });
      cache = off; cacheKey = key; return off;
    }
    function draw(t) {
      if (!MQ.matches) return;
      var W = innerWidth, H = innerHeight; if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
      cx.drawImage(base(W, H), 0, 0);
      if (!reduce) { var px = (126.98 + 180) / 360 * W, py = (90 - 37.57) / 180 * H, ph = ((t || 0) / 6000) % 1; cx.strokeStyle = 'rgba(255,122,46,' + (0.5 * (1 - ph)) + ')'; cx.beginPath(); cx.arc(px, py, 4 + ph * 18, 0, 7); cx.stroke(); }
    }
    draw(0);
    if (reduce) setInterval(function () { draw(0); }, 6e4);
    else (function loop(t) { draw(t); setTimeout(function () { requestAnimationFrame(loop); }, 120); })(0);
    addEventListener('resize', function () { draw(0); });
  }

  // ── 시작 ──────────────────────────────────────────────────
  function start() {
    if (started) return; started = true;
    buildLauncher(); tickClocks(); setInterval(tickClocks, 30000);
    popup('pcWxBtn', 'pcWxPop', '.wx'); popup('pcOvBtn', 'pcOvPop', '.ovwrap');
    $('pcStockBtn').addEventListener('click', function () { if (typeof openStockModal === 'function') openStockModal(); });
    bindKeys();
    loadOps(); loadWeather(); loadBriefing(); loadFront(); loadCalendar(); loadSports();
    renderMarket(typeof currentStocks !== 'undefined' ? currentStocks : []);
    sky();
    // 오래 켜 두는 탭: 30분마다 데이터 다시 읽기, 관제실은 5분마다
    setInterval(function () { loadWeather(); loadBriefing(); loadFront(); loadCalendar(); loadSports(); }, 30 * 6e4);
    setInterval(loadOps, 5 * 6e4);
  }
  window.pcStart = start;
  window.pcIsPC = function () { return MQ.matches; };
  if (MQ.matches) start();
  (MQ.addEventListener ? MQ.addEventListener.bind(MQ, 'change') : MQ.addListener.bind(MQ))(function () { if (MQ.matches) start(); else if (window.oldStart) window.oldStart(); });
})();
