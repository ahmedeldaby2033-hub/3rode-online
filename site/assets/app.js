/* عروض أونلاين 3rde.online — client-side behaviour (vanilla JS, deferred).
   All catalogue content is rendered server-side in static HTML; this file
   only adds interaction: filters, sorting, favorites, compare, dark mode,
   installments, sharing, coupons, cookie consent, click tracking.
   No personal data is collected. Click beacons go to the Apps Script
   endpoint only when ADMIN_API_URL is configured (window.SITE_CONFIG). */
(function () {
  'use strict';
  var CFG = window.SITE_CONFIG || {};
  var ADMIN_API = CFG.adminApiUrl || '';

  function $(s, r) { return (r || document).querySelector(s); }
  function $all(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  function toast(msg) {
    var t = $('#toast'); if (!t) return;
    t.textContent = msg; t.classList.add('show');
    setTimeout(function () { t.classList.remove('show'); }, 2600);
  }

  /* ---------- mobile nav toggle ---------- */
  var navToggle = $('#nav-toggle'), mainNav = $('#main-nav');
  if (navToggle && mainNav) navToggle.addEventListener('click', function () {
    var open = mainNav.classList.toggle('open');
    navToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    navToggle.textContent = open ? '✕ إغلاق' : '☰ القائمة';
  });

  /* ---------- dark mode (الافتراضي: ليلي) ---------- */
  var themeBtn = $('#theme-toggle');
  var savedTheme = null;
  try { savedTheme = localStorage.getItem('r3de-theme'); } catch (e) {}
  if (savedTheme) document.documentElement.setAttribute('data-theme', savedTheme);
  // تسمية زر التبديل حسب الوضع الحالي عند تحميل الصفحة
  // (أيقونة SVG + نص، لتبقى الأيقونة ظاهرة بدل استبدالها بإيموجي)
  var SVG_OPEN = '<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">';
  var SUN_PATH = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>';
  var MOON_PATH = '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>';
  var SVG_CLOSE = '</svg></span> ';
  function syncThemeLabel() {
    if (!themeBtn) return;
    var cur = document.documentElement.getAttribute('data-theme') || 'dark';
    themeBtn.innerHTML = cur === 'dark'
      ? SVG_OPEN + SUN_PATH + SVG_CLOSE + 'الوضع النهاري'
      : SVG_OPEN + MOON_PATH + SVG_CLOSE + 'الوضع الليلي';
  }
  syncThemeLabel();
  if (themeBtn) themeBtn.addEventListener('click', function () {
    var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('r3de-theme', next); } catch (e) {}
    syncThemeLabel();
  });

  /* ---------- favorites (no registration, localStorage) ---------- */
  var favs = {};
  try { favs = JSON.parse(localStorage.getItem('r3de-favs') || '{}'); } catch (e) { favs = {}; }
  function saveFavs() { try { localStorage.setItem('r3de-favs', JSON.stringify(favs)); } catch (e) {} }
  function refreshFavButtons() {
    $all('[data-fav]').forEach(function (b) {
      var on = !!favs[b.getAttribute('data-fav')];
      b.classList.toggle('fav-on', on);
      b.textContent = on ? '♥ في المفضلة' : '♡ مفضلة';
    });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-fav]');
    if (!b) return;
    var slug = b.getAttribute('data-fav');
    if (favs[slug]) { delete favs[slug]; toast('أُزيل من المفضلة'); }
    else { favs[slug] = Date.now(); toast('أُضيف إلى المفضلة'); }
    saveFavs(); refreshFavButtons();
  });
  refreshFavButtons();

  /* ---------- compare (2–3 phones) ---------- */
  var cmp = [];
  try { cmp = JSON.parse(localStorage.getItem('r3de-compare') || '[]'); } catch (e) { cmp = []; }
  var bar = $('#compare-bar'), barList = $('#compare-list');
  function saveCmp() { try { localStorage.setItem('r3de-compare', JSON.stringify(cmp)); } catch (e) {} }
  function refreshCmpBar() {
    if (!bar) return;
    if (!cmp.length) { bar.classList.remove('show'); return; }
    bar.classList.add('show');
    barList.textContent = 'للمقارنة (' + cmp.length + '/3): ' + cmp.join('، ');
    $all('[data-compare]').forEach(function (b) {
      b.classList.toggle('fav-on', cmp.indexOf(b.getAttribute('data-compare')) !== -1);
    });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-compare]');
    if (b) {
      var slug = b.getAttribute('data-compare');
      var i = cmp.indexOf(slug);
      if (i !== -1) cmp.splice(i, 1);
      else if (cmp.length >= 3) { toast('يمكنك مقارنة 3 هواتف كحد أقصى'); return; }
      else cmp.push(slug);
      saveCmp(); refreshCmpBar(); return;
    }
    if (e.target.closest('#compare-go')) {
      location.href = '/compare/?m=' + cmp.join(',');
    }
    if (e.target.closest('#compare-clear')) { cmp = []; saveCmp(); refreshCmpBar(); }
  });
  refreshCmpBar();

  /* ---------- homepage filters + sorting ---------- */
  var grid = $('#models-grid');
  function applyFilters() {
    if (!grid) return;
    var q = ($('#filter-q') || { value: '' }).value.trim();
    var brand = ($('#filter-brand') || { value: '' }).value;
    var ram = ($('#filter-ram') || { value: '' }).value;
    var storage = ($('#filter-storage') || { value: '' }).value;
    var maxPrice = parseFloat(($('#filter-maxprice') || { value: '' }).value) || Infinity;
    var fiveG = $('#filter-5g') ? $('#filter-5g').checked : false;
    var inStock = $('#filter-instock') ? $('#filter-instock').checked : false;
    var favOnly = $('#filter-favonly') ? $('#filter-favonly').checked : false;
    var sort = ($('#sort-by') || { value: 'cheapest' }).value;
    var cards = $all('.pcard', grid);
    cards.forEach(function (c) {
      var d = c.dataset;
      var ok = true;
      if (q && (d.search || '').indexOf(q) === -1) ok = false;
      if (brand && d.brand !== brand) ok = false;
      if (ram && d.ram !== ram) ok = false;
      if (storage && d.storage !== storage) ok = false;
      if (parseFloat(d.price || '0') > maxPrice) ok = false;
      if (fiveG && d.g5 !== '1') ok = false;
      if (inStock && d.instock !== '1') ok = false;
      if (favOnly && !favs[d.slug]) ok = false;
      c.style.display = ok ? '' : 'none';
    });
    var visible = cards.filter(function (c) { return c.style.display !== 'none'; });
    visible.sort(function (a, b) {
      var pa = parseFloat(a.dataset.price || '0'), pb = parseFloat(b.dataset.price || '0');
      var da = parseFloat(a.dataset.discount || '0'), db = parseFloat(b.dataset.discount || '0');
      var ra = parseFloat(a.dataset.rating || '0'), rb = parseFloat(b.dataset.rating || '0');
      if (sort === 'newest') return (parseInt(b.dataset.year || '0', 10) - parseInt(a.dataset.year || '0', 10)) || (pa - pb);
      if (sort === 'cheapest') return pa - pb;
      if (sort === 'discount') return db - da;
      if (sort === 'rating') return rb - ra;
      if (sort === 'latest') return (b.dataset.updated || '').localeCompare(a.dataset.updated || '');
      return 0;
    });
    visible.forEach(function (c) { grid.appendChild(c); });
    var n = $('#results-count');
    if (n) n.textContent = 'عرض ' + visible.length + ' هاتفاً';
  }
  ['filter-q', 'filter-brand', 'filter-ram', 'filter-storage', 'filter-maxprice',
   'filter-5g', 'filter-instock', 'filter-favonly', 'sort-by'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('input', applyFilters);
    if (el) el.addEventListener('change', applyFilters);
  });
  $all('.chip[data-brand]').forEach(function (chip) {
    chip.addEventListener('click', function () {
      var sel = $('#filter-brand');
      if (sel) { sel.value = sel.value === chip.getAttribute('data-brand') ? '' : chip.getAttribute('data-brand'); }
      $all('.chip[data-brand]').forEach(function (c) { c.classList.toggle('on', sel && c.getAttribute('data-brand') === sel.value); });
      applyFilters();
    });
  });

  /* ---------- budget form ---------- */
  var budgetForm = $('#budget-form');
  if (budgetForm) budgetForm.addEventListener('submit', function (e) {
    e.preventDefault();
    var max = parseFloat($('#budget-max').value) || 0;
    var ram = $('#budget-ram').value;
    var out = $('#budget-results');
    if (!window.PRODUCTS || !out) return;
    var list = window.PRODUCTS.filter(function (p) {
      return p.price <= max && (!ram || p.ram === ram);
    }).sort(function (a, b) { return a.price - b.price; }).slice(0, 12);
    if (!list.length) { out.innerHTML = '<p>لا توجد هواتف مطابقة لهذه الميزانية حالياً. جرّب رفع الحد الأقصى أو إلغاء شرط الرام.</p>'; return; }
    out.innerHTML = '<div class="grid">' + list.map(function (p) {
      return '<article class="pcard"><a href="/mobiles/' + p.slug + '/"><img src="' + (p.image || '/images/placeholder.jpg?v=2') + '" alt="هاتف ' + p.name + '" loading="lazy" width="500" height="500"></a><div class="pcard-body"><h3><a href="/mobiles/' + p.slug + '/">' + p.name + '</a></h3>' +
        '<div class="price-row"><span class="price">' + p.price.toLocaleString('en-US') + ' جنيه</span></div>' +
        '<div class="brand-line">' + p.brand + ' • ' + p.storage + ' / ' + p.ram + '</div>' +
        '<div class="actions"><a class="btn-mini btn-prices" href="/mobiles/' + p.slug + '/">عرض السعر والمقارنة</a></div></div></article>';
    }).join('') + '</div>';
  });

  /* ---------- installment calculator ---------- */
  var instPrice = $('#inst-price'), instMonths = $('#inst-months'), instOut = $('#inst-result');
  function calcInst() {
    if (!instPrice || !instOut) return;
    var price = parseFloat(instPrice.value) || 0;
    var months = parseInt((instMonths || { value: '12' }).value, 10) || 12;
    instOut.textContent = months > 0 && price > 0
      ? 'القسط الشهري التقريبي: ' + Math.round(price / months).toLocaleString('en-US') + ' جنيه / شهر'
      : '';
  }
  if (instPrice) instPrice.addEventListener('input', calcInst);
  if (instMonths) instMonths.addEventListener('change', calcInst);
  calcInst();

  /* ---------- coupons: copy + redirect (audit ت-12) ---------- */
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-coupon]');
    if (!b) return;
    if (b.tagName === 'A') e.preventDefault();
    var code = b.getAttribute('data-coupon') || '';
    var go = function () { if (b.getAttribute('data-redirect')) window.open(b.getAttribute('data-redirect'), '_blank', 'noopener'); };
    if (navigator.clipboard && code) {
      navigator.clipboard.writeText(code).then(function () {
        toast('تم نسخ الكود: ' + code + ' — سيتم تحويلك إلى المتجر الآن.');
        setTimeout(go, 900);
      }, go);
    } else { toast('الكود: ' + code); go(); }
  });

  /* ---------- coupons: copy code + open store in a new tab ---------- */
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-copy-code]');
    if (!b || b.disabled) return;
    var code = b.getAttribute('data-copy-code') || '';
    if (!code) return;
    var redirect = b.getAttribute('data-redirect') || '';
    // افتح تبويب المتجر فوراً ضمن إيماءة النقر نفسها — window.open داخل
    // setTimeout يحجبه مانع النوافذ المنبثقة في المتصفح.
    if (redirect) { try { window.open(redirect, '_blank', 'noopener'); } catch (err) {} }
    // غيّر نص زر الانتقال فقط — تغيير textContent على البطاقة كاملة
    // يمسح محتواها (الزر والكود) نهائياً ولا يعود.
    var card = b.closest('.coupon-box');
    var btn = card ? card.querySelector('.coupon-go-btn') : null;
    var done = function () {
      toast('تم نسخ الكود: ' + code);
      if (btn) {
        var old = btn.textContent;
        btn.textContent = 'تم النسخ ✓ — جارٍ التحويل…';
        setTimeout(function () { btn.textContent = old; }, 2000);
      }
    };
    if (navigator.clipboard) {
      navigator.clipboard.writeText(code).then(done, function () { toast('الكود: ' + code); });
    } else { toast('الكود: ' + code); }
  });

  /* ---------- countdown timers ---------- */
  $all('[data-countdown]').forEach(function (el) {
    var end = new Date(el.getAttribute('data-countdown') + 'T23:59:59+02:00').getTime();
    function tick() {
      var d = end - Date.now();
      if (d <= 0) { el.textContent = 'انتهى العرض'; var b = el.closest('.wf-banner'); if (b) b.style.display = 'none'; return; }
      var days = Math.floor(d / 864e5), h = Math.floor(d % 864e5 / 36e5),
          m = Math.floor(d % 36e5 / 6e4), s = Math.floor(d % 6e4 / 1e3);
      el.textContent = 'متبقٍ ' + days + ' يوم و' + h + ' ساعة و' + m + ' دقيقة';
    }
    tick(); setInterval(tick, 30000);
  });

  /* ---------- report wrong price + request product ---------- */
  function postToAdmin(action, payload, okMsg) {
    if (!ADMIN_API) { toast('هذه الميزة تُفعَّل بعد ربط لوحة التحكم. يمكنك مراسلتنا على ' + (CFG.contactEmail || 'البريد الرسمي') + '.'); return; }
    fetch(ADMIN_API + '?action=' + action, {
      method: 'POST', mode: 'cors',
      headers: { 'Content-Type': 'text/plain;charset=utf-8' },
      body: JSON.stringify(payload)
    }).then(function () { toast(okMsg); })
      .catch(function () { toast('تعذّر الإرسال حالياً — جرّب مراسلتنا بالبريد.'); });
  }
  var reportForm = $('#report-form');
  if (reportForm) reportForm.addEventListener('submit', function (e) {
    e.preventDefault();
    postToAdmin('reportPrice', {
      model: reportForm.getAttribute('data-model') || '',
      note: $('#report-note').value || '',
      correctPrice: $('#report-price').value || '',
      url: window.location.href
    }, 'شكراً! وصل بلاغك وسنراجع السعر.');
    reportForm.reset();
  });
  var reqForm = $('#request-form');
  if (reqForm) reqForm.addEventListener('submit', function (e) {
    e.preventDefault();
    postToAdmin('requestProduct', {
      model: $('#request-model').value || '',
      budget: $('#request-budget').value || '',
      // The backend stores the contact value in the Requests sheet's
      // contact column (body.email); send the WhatsApp number there
      // (and as whatsapp for forward-compatibility).
      email: $('#request-whatsapp').value || '',
      whatsapp: $('#request-whatsapp').value || ''
    }, 'تم تسجيل طلبك، سيتم التواصل معك قريباً');
    reqForm.reset();
  });
  var stockForm = $('#stock-alert-form');
  if (stockForm) stockForm.addEventListener('submit', function (e) {
    e.preventDefault();
    postToAdmin('notifyStock', {
      model: stockForm.getAttribute('data-model') || '',
      email: $('#stock-whatsapp').value || '',
      whatsapp: $('#stock-whatsapp').value || ''
    }, 'تم! سنخبرك على واتساب فور توفر الهاتف.');
    stockForm.reset();
  });

  /* ---------- buy-click tracking (no PII) ---------- */
  document.addEventListener('click', function (e) {
    var a = e.target.closest('a[data-event="buy-click"]');
    if (!a || !ADMIN_API) return;
    var payload = { store: a.getAttribute('data-store') || '', model: a.getAttribute('data-model') || '', url: a.href };
    try {
      if (navigator.sendBeacon) navigator.sendBeacon(ADMIN_API + '?action=logClick', JSON.stringify(payload));
    } catch (err) {}
  });

  /* ---------- cookie consent ---------- */
  var banner = $('#cookie-banner');
  var consent = null;
  try { consent = localStorage.getItem('r3de-consent'); } catch (e) {}
  if (banner && !consent) banner.classList.add('show');
  var okBtn = $('#cookie-ok');
  if (okBtn) okBtn.addEventListener('click', function () {
    try { localStorage.setItem('r3de-consent', 'yes'); } catch (e) {}
    banner.classList.remove('show');
  });

  /* ---------- PWA install prompt ---------- */
  var deferredPrompt = null, installBtn = $('#pwa-install');
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault(); deferredPrompt = e;
    if (installBtn) installBtn.style.display = '';
  });
  if (installBtn) installBtn.addEventListener('click', function () {
    if (!deferredPrompt) { toast('للتثبيت: من قائمة المتصفح اختر "إضافة إلى الشاشة الرئيسية".'); return; }
    deferredPrompt.prompt();
    deferredPrompt.userChoice.then(function () { deferredPrompt = null; });
  });
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js').catch(function () {});
    });
  }

  /* ---------- back-to-top button ---------- */
  var toTop = document.getElementById('to-top');
  if (toTop) {
    window.addEventListener('scroll', function () {
      toTop.classList.toggle('show', window.scrollY > 600);
    }, { passive: true });
    toTop.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  /* ---------- push notifications (OneSignal placeholder) ---------- */
  if (CFG.onesignalAppId) {
    var s = document.createElement('script');
    s.src = 'https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js';
    s.defer = true;
    s.onload = function () {
      try {
        window.OneSignalDeferred = window.OneSignalDeferred || [];
        window.OneSignalDeferred.push(function (OneSignal) {
          OneSignal.init({ appId: CFG.onesignalAppId });
        });
      } catch (err) {}
    };
    document.head.appendChild(s);
  }
})();
