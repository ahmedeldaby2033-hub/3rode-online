/**
 * عروض أونلاين 3rde.online — Admin backend (Google Apps Script)
 *
 * Binds to the Google Sheet (the single source of truth). The static site
 * is generated from this sheet; this script is the ONLY writer to the
 * sheet besides manual edits (audit ت-11: single writer + LockService).
 *
 * SETUP: open the sheet → Extensions → Apps Script → paste this file →
 * set ADMIN_TOKEN in Project Settings → Deploy as Web App (Execute as:
 * Me, Access: Anyone) → copy the /exec URL into admin/index.html
 * (APPS_SCRIPT_URL) and into settings.json (admin.apps_script_url).
 *
 * Security: every admin action requires ?token=ADMIN_TOKEN (stored in
 * Script Properties, never in this file). Public actions (logClick,
 * reportPrice, requestProduct) accept no token but write only to their
 * own log tabs.
 *
 * Tabs used (created on first run by setupTabs()):
 *   الورقة1 (products, 46 cols) · ملخص · سجل الأسعار · المكرر فقط
 *   الإعدادات (Settings) · الكوبونات (Coupons) · سجل المزامنة (SyncLog)
 *   النقرات (Clicks) · البلاغات (Reports) · الطلبات (Requests)
 *   الأدلة (Guides) · الأخبار (News)
 */

var ADMIN_EMAIL = '3rdeonline@gmail.com';
var SHEET_PRODUCTS = 'الورقة1';
var SHEET_HISTORY = 'سجل الأسعار';
var SHEET_SETTINGS = 'الإعدادات';
var SHEET_COUPONS = 'الكوبونات';
var SHEET_SYNCLOG = 'سجل المزامنة';
var SHEET_CLICKS = 'النقرات';
var SHEET_REPORTS = 'البلاغات';
var SHEET_REQUESTS = 'الطلبات';
var SHEET_STOCK_ALERTS = 'تنبيهات التوفر';
var SHEET_GUIDES = 'الأدلة';
var SHEET_NEWS = 'الأخبار';
var SHEET_HANDLED = 'المعالجة';

var SETTINGS_DEFAULTS = [
  ['site_name', 'عروض أونلاين'],
  ['site_domain', '3rde.online'],
  ['contact_email', '3rdeonline@gmail.com'],
  ['currency', 'EGP'],
  ['sync_frequency', 'hourly'],
  ['amazon_associates_tag', 'amazon0c2aca6-21'],
  ['jumia_sub_id', ''],
  ['jumia_jforce_link', 'https://jforce.jumia.com.eg/s/C4i51XK'],
  ['jumia_homepage_url', 'https://www.jumia.com.eg/ar/?utm_source=JFORCE&utm_medium=JF_Affiliate&utm_campaign=JF_Affiliate_EG&adj_label=casid*cf5c450e-259d-49d2-889e-95c558384bcd%5Etype*jforce'],
  ['noon_affiliate_tag', ''],
  ['adsense_client', ''],
  ['ads_top', ''],
  ['ads_in_list', ''],
  ['ads_in_product', ''],
  ['ads_bottom', ''],
  ['google_analytics_id', ''],
  ['search_console_verification', ''],
  ['bing_verification', ''],
  ['onesignal_app_id', ''],
  ['telegram_bot', ''],
  ['telegram_channel', ''],
  ['stores_json', '[{"name":"جوميا مصر","logo":"/assets/store-logos/jumia.png","url":"https://jforce.jumia.com.eg/s/C4i51XK"},{"name":"أمازون مصر","logo":"/assets/store-logos/amazon.svg","url":"https://www.amazon.eg/?tag=amazon0c2aca6-21"},{"name":"نون مصر","logo":"/assets/store-logos/noon.svg","url":"https://www.noon.com/egypt-en/"}]'],
  // Fame order of the 27 brands (editable from the admin panel's
  // "ترتيب الماركات" editor; sync adopts it into settings.json brand_order).
  ['brand_order_json', '["Apple","Samsung","Xiaomi","XIAOMI","OPPO","realme","vivo","Redmi","Honor","Huawei","Infinix","Tecno","Nokia","Motorola","itel","Itel","ZTE","Micromax","Generic","Girasole","Hope","I Pro","Pluzz","Sary","Shitel","Sunelan","TAG-PHONE"]']
];

/* ------------------------------------------------------------ helpers */
function ss() { return SpreadsheetApp.getActiveSpreadsheet(); }

function sheet(name, headers) {
  var s = ss().getSheetByName(name);
  if (!s) {
    s = ss().insertSheet(name);
    if (headers) s.appendRow(headers);
  }
  return s;
}

function setupTabs() {
  sheet(SHEET_SETTINGS, ['key', 'value']);
  var st = ss().getSheetByName(SHEET_SETTINGS);
  var keys = {};
  st.getDataRange().getValues().forEach(function (r) { keys[r[0]] = true; });
  SETTINGS_DEFAULTS.forEach(function (kv) {
    if (!keys[kv[0]]) st.appendRow(kv);
  });
  sheet(SHEET_COUPONS, ['id', 'title', 'store', 'code', 'value', 'redirect_url', 'expires_at', 'active', 'description']);
  // Existing coupon sheets created before the description column existed:
  // append the 9th header cell so saveCoupon's 9-column writes line up.
  (function () {
    var cs = ss().getSheetByName(SHEET_COUPONS);
    var hdr = cs.getRange(1, 1, 1, Math.max(cs.getLastColumn(), 1)).getValues()[0];
    if (hdr[8] !== 'description') cs.getRange(1, 9).setValue('description');
  })();
  sheet(SHEET_SYNCLOG, ['timestamp', 'action', 'details']);
  sheet(SHEET_CLICKS, ['timestamp', 'store', 'model', 'url']);
  sheet(SHEET_REPORTS, ['timestamp', 'model', 'correct_price', 'note']);
  sheet(SHEET_REQUESTS, ['timestamp', 'model', 'budget', 'email']);
  sheet(SHEET_STOCK_ALERTS, ['timestamp', 'model', 'whatsapp']);
  sheet(SHEET_GUIDES, ['slug', 'title', 'criterion', 'description', 'human_review', 'status', 'author', 'date']);
  sheet(SHEET_NEWS, ['slug', 'title', 'description', 'body', 'model_slug', 'author', 'date_published', 'is_example']);
  // Scheduled publishing (col 9): guides + news get a publish_at column
  // (ISO datetime, e.g. 2026-11-25T10:00). publishScheduled() publishes
  // due rows hourly. Existing sheets created before this column existed
  // get the 9th header cell appended, like the coupons description fix.
  (function () {
    [SHEET_GUIDES, SHEET_NEWS].forEach(function (name) {
      var sh = ss().getSheetByName(name);
      var hdr = sh.getRange(1, 1, 1, Math.max(sh.getLastColumn(), 1)).getValues()[0];
      if (hdr[8] !== 'publish_at') sh.getRange(1, 9).setValue('publish_at');
    });
  })();
  sheet(SHEET_HANDLED, ['kind', 'timestamp', 'model']);
  return { ok: true };
}

function tokenOk(e) {
  var props = PropertiesService.getScriptProperties();
  var saved = props.getProperty('ADMIN_TOKEN');
  if (!saved) return { ok: false, error: 'ADMIN_TOKEN is not set in Script Properties' };
  var got = (e.parameter && e.parameter.token) || '';
  return { ok: got === saved };
}

function jsonOut(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function readBody(e) {
  try { return JSON.parse(e.postData.contents || '{}'); } catch (err) { return {}; }
}

// Telegram notifications: reads TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID from
// Script Properties (Project Settings → Script Properties). Never hardcode
// the token in this file — the repo is public. Silently no-ops when unset.
function sendTelegram(text) {
  try {
    var props = PropertiesService.getScriptProperties();
    var token = props.getProperty('TELEGRAM_BOT_TOKEN') || '';
    var chatId = props.getProperty('TELEGRAM_CHAT_ID') || '';
    if (!token || !chatId || !text) return;
    UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/sendMessage', {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({ chat_id: chatId, text: String(text) }),
      muteHttpExceptions: true
    });
  } catch (err) { /* notifications must never break the Sheet write */ }
}

function getSettings() {
  setupTabs();
  var out = {};
  ss().getSheetByName(SHEET_SETTINGS).getDataRange().getValues()
    .forEach(function (r) { if (r[0]) out[r[0]] = r[1]; });
  // Unique brands from the products sheet (column C) so the admin's
  // brand-order editor always lists the Sheet's current brands.
  try {
    var vals = ss().getSheetByName(SHEET_PRODUCTS).getDataRange().getValues();
    var seen = {};
    var list = [];
    vals.slice(1).forEach(function (r) {
      var b = (r[2] || '').toString().trim();
      if (b && !seen[b]) { seen[b] = true; list.push(b); }
    });
    out.brands_json = JSON.stringify(list);
  } catch (err) { out.brands_json = '[]'; }
  return out;
}

function saveSettings(values) {
  var st = ss().getSheetByName(SHEET_SETTINGS);
  var rows = st.getDataRange().getValues();
  var map = {};
  rows.forEach(function (r, i) { if (r[0]) map[r[0]] = i + 1; });
  Object.keys(values).forEach(function (k) {
    // Amazon Egypt tag MUST end with -21 (a -20 US tag earns nothing on .eg)
    if (k === 'amazon_associates_tag' && values[k] &&
        String(values[k]).slice(-3) !== '-21') {
      throw new Error('وسام أمازون يجب أن ينتهي بـ -21 (وسام -20 لا يحقق أي عمولة على amazon.eg)');
    }
    if (map[k]) st.getRange(map[k], 2).setValue(values[k]);
    else st.appendRow([k, values[k]]);
  });
  return getSettings();
}

function productHeaders() {
  return ss().getSheetByName(SHEET_PRODUCTS).getRange(1, 1, 1, 46).getValues()[0];
}

function findProductRow(productUrl) {
  var s = ss().getSheetByName(SHEET_PRODUCTS);
  var urls = s.getRange(2, 5, Math.max(s.getLastRow() - 1, 1), 1).getValues();
  for (var i = 0; i < urls.length; i++) {
    if (urls[i][0] === productUrl) return i + 2;
  }
  return -1;
}

function appendPriceHistory(row, oldPrice, newPrice) {
  // audit ت-3: history is recorded ONLY when the price actually changed
  if (oldPrice === null || oldPrice === '' || Number(oldPrice) === Number(newPrice)) return;
  var diff = Number(newPrice) - Number(oldPrice);
  var pct = oldPrice ? Math.round(diff / Number(oldPrice) * 1000) / 10 : 0;
  sheet(SHEET_HISTORY).appendRow([
    Utilities.formatDate(new Date(), 'Africa/Cairo', 'dd-MM-yyyy'),
    row[0], row[3], row[13], row[14], row[5], row[6], row[4],
    oldPrice, newPrice, diff, pct
  ]);
}

/* ---- affiliate-link (AU) alignment: same rules as scripts/verify.py -- */
var JFORCE_PARAMS = 'utm_source=JFORCE&utm_medium=JF_Affiliate&utm_campaign=JF_Affiliate_EG&adj_label=' +
  encodeURIComponent('casid*cf5c450e-259d-49d2-889e-95c558384bcd^type*jforce');
var TRACKING_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'adj_label', 'subid', 'sub_id'];

function normalizeJumiaUrl(u) {
  u = String(u || '').trim();
  if (!u) return '';
  u = u.replace(/^https?:\/\/(www\.)?jumia\.com\.eg\//i, 'https://www.jumia.com.eg/ar/');
  if (u.indexOf('https://www.jumia.com.eg/') === 0 && u.indexOf('/ar/') === -1) {
    u = u.replace('https://www.jumia.com.eg/', 'https://www.jumia.com.eg/ar/');
  }
  return u;
}

function stripTracking(u) {
  var parts = String(u || '').split('?');
  if (parts.length < 2) return u;
  var q = parts[1].split('&').filter(function (kv) {
    return TRACKING_KEYS.indexOf(kv.split('=')[0]) === -1;
  });
  return q.length ? parts[0] + '?' + q.join('&') : parts[0];
}

function buildTrackingUrl(u) {
  var base = normalizeJumiaUrl(u);
  if (!base) return '';
  var clean = stripTracking(base);
  return clean + (clean.indexOf('?') === -1 ? '?' : '&') + JFORCE_PARAMS;
}

function dayKey(v) {
  if (!v) return '';
  if (typeof v === 'string') {
    var m = v.match(/(\d{2})-(\d{2})-(\d{4})/);
    if (m) return m[3] + '-' + m[2] + '-' + m[1];
    return v.slice(0, 10);
  }
  return Utilities.formatDate(new Date(v), 'Africa/Cairo', 'yyyy-MM-dd');
}

/* ---- affiliate-link (AU) alignment check, shared by the panel action
   and the daily trigger (dailyAffiliateCheck). Same rules as
   scripts/verify.py: AU must be the JForce-tracked version of column E. */
function checkAffiliateLogic() {
  // compare column AU (index 46) with the product URL in column E (index 4)
  var pv = ss().getSheetByName(SHEET_PRODUCTS).getDataRange().getValues();
  var mismatched = [], missing = [];
  for (var ci = 1; ci < pv.length; ci++) {
    var erow = pv[ci];
    var eurl = erow[4];
    if (!eurl || String(eurl).indexOf('jumia.com.eg') === -1) continue;
    var expected = buildTrackingUrl(eurl);
    var au = erow[46];
    if (!au) { missing.push({ row: ci + 1, model: erow[0], url: eurl }); continue; }
    var auPath = stripTracking(normalizeJumiaUrl(au));
    var ePath = stripTracking(expected);
    var hasTracking = String(au).indexOf('utm_source=JFORCE') !== -1;
    if (auPath !== ePath || !hasTracking) {
      mismatched.push({ row: ci + 1, model: erow[0], expected: expected, actual: au });
    }
  }
  return { ok: true, total: pv.length - 1, mismatched: mismatched, missing: missing };
}

/* Daily affiliate check (time trigger): same check as the panel button,
   but sends a Telegram alert instead of waiting for a manual click. */
function dailyAffiliateCheck() {
  var res = checkAffiliateLogic();
  if (res.mismatched.length || res.missing.length) {
    sendTelegram('⚠️ فحص روابط الأفلييت اليومي: ' + res.mismatched.length +
      ' رابط مخالف، ' + res.missing.length + ' بلا رابط أفلييت.\n' +
      'افتح لوحة التحكم ← الأدوات ← فحص الأفلييت للإصلاح.');
  }
  return res;
}

function deleteTriggersFor(fn) {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === fn) ScriptApp.deleteTrigger(t);
  });
}

/* Site slug for a model, mirroring scripts/build.py slugify()
   (brand-model-storage-ram, lowercase, non-alphanumerics → '-').
   Collision suffixes (-2, -3…) are NOT reproduced here, so a rare
   colliding model's «فتح المنتج» link may 404 — the Jumia link is
   always exact. */
function slugifyModel(brand, model, storage, ram) {
  var s = [brand, model, storage, ram].join('-');
  try { s = s.normalize('NFKD'); } catch (e) {}
  s = s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return s || 'item';
}

/* Fetch a product page (server-side, so no CORS / browser blocks) and
   extract its og:image (twitter:image as fallback). Returns '' when the
   page has no usable image (e.g. Cloudflare 403). */
function fetchOgImage(url) {
  var resp = UrlFetchApp.fetch(url, {
    muteHttpExceptions: true, followRedirects: true,
    validateHttpsCertificates: false,
    headers: { 'User-Agent': 'Mozilla/5.0 (compatible; 3rde-online-admin/1.0)' }
  });
  if (resp.getResponseCode() !== 200) return '';
  var html = resp.getContentText();
  var m = html.match(/<meta[^>]+property=["']og:image["'][^>]*content=["']([^"']+)["']/i) ||
          html.match(/<meta[^>]+content=["']([^"']+)["'][^>]*property=["']og:image["']/i) ||
          html.match(/<meta[^>]+name=["']twitter:image["'][^>]*content=["']([^"']+)["']/i) ||
          html.match(/<meta[^>]+content=["']([^"']+)["'][^>]*name=["']twitter:image["']/i);
  if (!m) return '';
  var img = m[1].trim();
  if (img.indexOf('//') === 0) return 'https:' + img;
  if (img.indexOf('/') === 0) {
    var origin = url.match(/^(https?:\/\/[^\/]+)/);
    return origin ? origin[1] + img : img;
  }
  return img;
}

/* Buy-link check over a slice of products (offset/limit, default 100).
   200/301/302 = OK, 404/410/500 = broken, anything else (e.g. 403 from
   Cloudflare) = uncertain, never «broken». Uses fetchAll in one batch. */
function checkBuyLinksLogic(offset, limit) {
  var s = ss().getSheetByName(SHEET_PRODUCTS);
  var values = s.getDataRange().getValues();
  var total = values.length - 1;
  offset = Math.max(0, offset | 0);
  limit = Math.min(200, Math.max(1, limit | 0));
  var end = Math.min(total, offset + limit);
  var requests = [], meta = [];
  for (var i = offset + 1; i <= end; i++) {
    var r = values[i];
    if (!r[0]) continue;
    if (r[4]) { requests.push(String(r[4])); meta.push({ row: i + 1, model: r[0], url: String(r[4]), kind: 'رابط المنتج' }); }
    if (r[46]) { requests.push(String(r[46])); meta.push({ row: i + 1, model: r[0], url: String(r[46]), kind: 'رابط الأفلييت' }); }
  }
  var broken = [], uncertain = [], okCount = 0;
  if (requests.length) {
    var responses = UrlFetchApp.fetchAll(requests.map(function (u) {
      return { url: u, muteHttpExceptions: true, followRedirects: true, validateHttpsCertificates: false };
    }));
    responses.forEach(function (resp, k) {
      var code = resp.getResponseCode();
      var m = meta[k];
      if (code === 200 || code === 301 || code === 302) okCount++;
      else if (code === 404 || code === 410 || code === 500) broken.push({ row: m.row, model: m.model, url: m.url, kind: m.kind, status: code });
      else uncertain.push({ row: m.row, model: m.model, url: m.url, kind: m.kind, status: code });
    });
  }
  return { ok: true, total: total, offset: offset, limit: limit, checked: requests.length,
    okCount: okCount, broken: broken, uncertain: uncertain, done: end >= total };
}

/* Daily buy-link check (time trigger): checks the next 100 products each
   day (offset rotates in Script Properties) and alerts on Telegram only
   when broken links are found. */
function dailyBuyLinksCheck() {
  var props = PropertiesService.getScriptProperties();
  var offset = parseInt(props.getProperty('buycheck_offset') || '0', 10) || 0;
  var res = checkBuyLinksLogic(offset, 100);
  props.setProperty('buycheck_offset', String(res.done ? 0 : offset + 100));
  if (res.broken.length) {
    sendTelegram('🔗 روابط شراء مكسورة (' + res.broken.length + ')\n' +
      res.broken.slice(0, 10).map(function (b) {
        return '• ' + b.model + ' — ' + b.url + ' (' + b.status + ')';
      }).join('\n'));
  }
  return res;
}

/* ---- scheduled publishing: guides/news with publish_at (col 9) ---- */
function publishScheduled() {
  var now = new Date().getTime();
  var publishedGuides = 0, publishedNews = 0;
  var gs = sheet(SHEET_GUIDES);
  var gv = gs.getDataRange().getValues();
  for (var i = 1; i < gv.length; i++) {
    var pa = gv[i][8];
    if (!pa) continue;
    var t = new Date(pa).getTime();
    if (isNaN(t) || t > now) continue;
    if (gv[i][5] !== 'published') { gs.getRange(i + 1, 6).setValue('published'); publishedGuides++; }
    gs.getRange(i + 1, 9).setValue('');
  }
  var ns = sheet(SHEET_NEWS);
  var nv = ns.getDataRange().getValues();
  for (var j = 1; j < nv.length; j++) {
    var npa = nv[j][8];
    if (!npa) continue;
    var nt = new Date(npa).getTime();
    if (isNaN(nt) || nt > now) continue;
    ns.getRange(j + 1, 7).setValue(Utilities.formatDate(new Date(npa), 'Africa/Cairo', 'yyyy-MM-dd'));
    ns.getRange(j + 1, 9).setValue('');
    publishedNews++;
  }
  return { ok: true, publishedGuides: publishedGuides, publishedNews: publishedNews };
}

/* ---- daily Sheet backup to Google Drive ---- */
var BACKUP_FOLDER = '3rde.online backups';
var BACKUP_KEEP = 30;
function backupSheet() {
  var folders = DriveApp.getFoldersByName(BACKUP_FOLDER);
  var folder = folders.hasNext() ? folders.next() : DriveApp.createFolder(BACKUP_FOLDER);
  var now = new Date();
  var stamp = Utilities.formatDate(now, 'Africa/Cairo', 'yyyy-MM-dd HH-mm');
  var name = '3rde.online — ' + stamp;
  var copy = DriveApp.getFileById(ss().getId()).makeCopy(name, folder);
  // keep only the newest BACKUP_KEEP copies
  var files = [];
  var it = folder.getFiles();
  while (it.hasNext()) files.push(it.next());
  files.sort(function (a, b) { return b.getDateCreated().getTime() - a.getDateCreated().getTime(); });
  files.slice(BACKUP_KEEP).forEach(function (f) { try { f.setTrashed(true); } catch (e) {} });
  return { ok: true, name: name, url: copy.getUrl(), date: stamp };
}
function dailyBackup() { return backupSheet(); }
function listBackupFiles() {
  var folders = DriveApp.getFoldersByName(BACKUP_FOLDER);
  if (!folders.hasNext()) return [];
  var folder = folders.next();
  var files = [];
  var it = folder.getFiles();
  while (it.hasNext()) files.push(it.next());
  files.sort(function (a, b) { return b.getDateCreated().getTime() - a.getDateCreated().getTime(); });
  return files.slice(0, 20).map(function (f) {
    return { name: f.getName(), date: Utilities.formatDate(f.getDateCreated(), 'Africa/Cairo', 'yyyy-MM-dd HH:mm'), url: f.getUrl() };
  });
}

/* ------------------------------------------------------------ doGet */
function doGet(e) {
  var action = (e.parameter && e.parameter.action) || '';
  try {
    if (action === 'export') {  // used by scripts/sync.py (no token needed: read-only data)
      setupTabs();
      var tabs = {};
      ['الورقة1', 'ملخص', 'سجل الأسعار', 'المكرر فقط', 'الكوبونات'].forEach(function (name) {
        tabs[name] = ss().getSheetByName(name).getDataRange().getValues();
      });
      return jsonOut({ ok: true, tabs: tabs, settings: getSettings() });
    }
    var auth = tokenOk(e);
    if (!auth.ok) return jsonOut(auth);
    if (action === 'settings') return jsonOut({ ok: true, settings: getSettings() });
    if (action === 'coupons') {
      return jsonOut({ ok: true, rows: sheet(SHEET_COUPONS).getDataRange().getValues() });
    }
    if (action === 'products') {
      var s = ss().getSheetByName(SHEET_PRODUCTS);
      var values = s.getDataRange().getValues();
      var q = ((e.parameter.q || '') + '').toLowerCase();
      var brand = e.parameter.brand || '';
      var rows = values.slice(1).filter(function (r) {
        if (brand && r[2] !== brand) return false;
        if (q && (String(r[0]) + ' ' + r[3] + ' ' + r[4]).toLowerCase().indexOf(q) === -1) return false;
        return true;
      });
      return jsonOut({ ok: true, headers: values[0], rows: rows.slice(0, 200), total: rows.length });
    }
    if (action === 'stats') {
      // عدّادات نظرة عامة من الشيت كاملاً (لا من أول 200 صف فقط):
      // الموديلات = قيم مميزة (ماركة|موديل|تخزين|رام)، الماركات = قيم مميزة، العروض = عدد الصفوف.
      var pv = ss().getSheetByName(SHEET_PRODUCTS).getDataRange().getValues();
      var models = {}, brands = {}, offers = 0;
      for (var si = 1; si < pv.length; si++) {
        var pr = pv[si];
        if (!pr[0]) continue;
        offers++;
        models[pr[2] + '|' + pr[3] + '|' + pr[13] + '|' + pr[14]] = 1;
        brands[pr[2]] = 1;
      }
      return jsonOut({ ok: true, models: Object.keys(models).length, brands: Object.keys(brands).length, offers: offers });
    }
    if (action === 'syncLog') {
      var log = sheet(SHEET_SYNCLOG).getDataRange().getValues().slice(1).slice(-100).reverse();
      return jsonOut({ ok: true, rows: log });
    }
    if (action === 'priceHistory') {
      var hist = sheet(SHEET_HISTORY).getDataRange().getValues().slice(1).slice(-200).reverse();
      return jsonOut({ ok: true, rows: hist });
    }
    if (action === 'clicks') {
      var clicks = sheet(SHEET_CLICKS).getDataRange().getValues().slice(1);
      var byStore = {}, byModel = {};
      clicks.forEach(function (r) {
        byStore[r[1]] = (byStore[r[1]] || 0) + 1;
        byModel[r[2]] = (byModel[r[2]] || 0) + 1;
      });
      return jsonOut({ ok: true, total: clicks.length, byStore: byStore, byModel: byModel });
    }
    if (action === 'reports') {
      return jsonOut({ ok: true, rows: sheet(SHEET_REPORTS).getDataRange().getValues().slice(1).reverse() });
    }
    if (action === 'requests') {
      return jsonOut({ ok: true, rows: sheet(SHEET_REQUESTS).getDataRange().getValues().slice(1).reverse() });
    }
    if (action === 'guides') {
      return jsonOut({ ok: true, rows: sheet(SHEET_GUIDES).getDataRange().getValues() });
    }
    if (action === 'news') {
      return jsonOut({ ok: true, rows: sheet(SHEET_NEWS).getDataRange().getValues() });
    }
    if (action === 'checkAffiliate') {
      return jsonOut(checkAffiliateLogic());
    }
    if (action === 'affiliateLockStatus') {
      var locked = false;
      ss().getSheetByName(SHEET_PRODUCTS).getProtections(SpreadsheetApp.ProtectionType.RANGE)
        .forEach(function (p) {
          var rg = p.getRange();
          if (rg.getColumn() === 47 && rg.getNumColumns() === 1) locked = true;
        });
      return jsonOut({ ok: true, locked: locked });
    }
    if (action === 'deadModels') {
      // الموديلات التي لم ينقر أحد على زر شرائها خلال آخر 30 يوماً.
      // النقرات في تبويب «النقرات» تحمل slug الموديل (data-model في الموقع).
      var pv = ss().getSheetByName(SHEET_PRODUCTS).getDataRange().getValues();
      var clicked = {};
      var cutoff = new Date().getTime() - 30 * 86400000;
      sheet(SHEET_CLICKS).getDataRange().getValues().slice(1).forEach(function (r) {
        var t = r[0] ? new Date(r[0]).getTime() : 0;
        if (t >= cutoff && r[2]) clicked[String(r[2]).trim()] = 1;
      });
      var seen = {}, out = [];
      for (var di = 1; di < pv.length; di++) {
        var dr = pv[di];
        if (!dr[0]) continue;
        var key = dr[2] + '|' + dr[3] + '|' + dr[13] + '|' + dr[14];
        if (seen[key]) continue;
        seen[key] = 1;
        var slug = slugifyModel(dr[2], dr[3], dr[13], dr[14]);
        if (!clicked[slug]) {
          out.push({ name: dr[0], brand: dr[2], model: dr[3], price: dr[7],
            updated: dr[25] || '', url: dr[4] || '', slug: slug });
        }
      }
      return jsonOut({ ok: true, total: out.length, models: out.slice(0, 300) });
    }
    if (action === 'stockAlerts') {
      return jsonOut({ ok: true, rows: sheet(SHEET_STOCK_ALERTS).getDataRange().getValues().slice(1).reverse() });
    }
    if (action === 'listBackups') {
      return jsonOut({ ok: true, backups: listBackupFiles() });
    }
    if (action === 'checkBuyLinks') {
      var off = parseInt((e.parameter.offset || '0'), 10) || 0;
      var lim = parseInt((e.parameter.limit || '100'), 10) || 100;
      return jsonOut(checkBuyLinksLogic(off, lim));
    }
    if (action === 'handled') {
      return jsonOut({ ok: true, rows: sheet(SHEET_HANDLED).getDataRange().getValues().slice(1) });
    }
    if (action === 'dailyStats') {
      var days = {};
      function countTab(name, key) {
        sheet(name).getDataRange().getValues().slice(1).forEach(function (r) {
          var k = dayKey(r[0]);
          if (!k) return;
          days[k] = days[k] || {};
          days[k][key] = (days[k][key] || 0) + 1;
        });
      }
      countTab(SHEET_HISTORY, 'priceChanges');
      countTab(SHEET_CLICKS, 'clicks');
      countTab(SHEET_REPORTS, 'reports');
      countTab(SHEET_REQUESTS, 'requests');
      var out = [];
      var now = new Date();
      for (var dd = 29; dd >= 0; dd--) {
        var dt = new Date(now.getTime() - dd * 86400000);
        var k = Utilities.formatDate(dt, 'Africa/Cairo', 'yyyy-MM-dd');
        out.push({ date: k,
          priceChanges: (days[k] && days[k].priceChanges) || 0,
          clicks: (days[k] && days[k].clicks) || 0,
          reports: (days[k] && days[k].reports) || 0,
          requests: (days[k] && days[k].requests) || 0 });
      }
      return jsonOut({ ok: true, days: out });
    }
    if (action === 'setup') return jsonOut(setupTabs());
    return jsonOut({ ok: false, error: 'unknown action: ' + action });
  } catch (err) {
    return jsonOut({ ok: false, error: String(err) });
  }
}

/* ----------------------------------------------------------- doPost */
function doPost(e) {
  var action = (e.parameter && e.parameter.action) || '';
  var body = readBody(e);
  try {
    // public endpoints (no token): write only to their own log tabs
    if (action === 'logClick') {
      sheet(SHEET_CLICKS).appendRow([new Date(), body.store || '', body.model || '', body.url || '']);
      return jsonOut({ ok: true });
    }
    if (action === 'reportPrice') {
      sheet(SHEET_REPORTS).appendRow([new Date(), body.model || '', body.correctPrice || '', body.note || '']);
      sendTelegram('⚠️ بلاغ سعر غير صحيح\nالهاتف: ' + (body.model || '') + '\nالسعر الصحيح: ' + (body.correctPrice || '') + '\nملاحظة: ' + (body.note || ''));
      return jsonOut({ ok: true });
    }
    if (action === 'requestProduct') {
      sheet(SHEET_REQUESTS).appendRow([new Date(), body.model || '', body.budget || '', body.email || '']);
      sendTelegram('📱 طلب منتج جديد\nالمنتج: ' + (body.model || '') + '\nالميزانية: ' + (body.budget || '') + '\nواتساب: ' + (body.email || ''));
      return jsonOut({ ok: true });
    }
    if (action === 'notifyStock') {
      // Back-in-stock alert: the WhatsApp number arrives as body.email
      // (same convention as requestProduct) and as body.whatsapp.
      sheet(SHEET_STOCK_ALERTS).appendRow([new Date(), body.model || '', body.whatsapp || body.email || '']);
      sendTelegram('🔔 تنبيه توفر\nالهاتف: ' + (body.model || '') + '\nواتساب العميل: ' + (body.whatsapp || body.email || '') + '\nعاد للتوفر — تواصل مع العميل.');
      return jsonOut({ ok: true });
    }
    var auth = tokenOk(e);
    if (!auth.ok) return jsonOut(auth);
    var lock = LockService.getScriptLock();
    lock.waitLock(30000);  // audit ت-11: single writer at a time
    try {
      var s, row, headers, i, j;
      if (action === 'saveSettings') {
        return jsonOut({ ok: true, settings: saveSettings(body.settings || {}) });
      }
      if (action === 'saveProduct') {
        headers = productHeaders();
        s = ss().getSheetByName(SHEET_PRODUCTS);
        row = (body.values || []).slice(0, 46);
        while (row.length < 46) row.push('');
        if (!row[4]) throw new Error('رابط المنتج مطلوب');
        var existing = findProductRow(row[4]);
        if (existing > 0) {
          var oldPrice = s.getRange(existing, 8).getValue();
          s.getRange(existing, 1, 1, 46).setValues([row]);
          appendPriceHistory(row, oldPrice, row[7]);
          return jsonOut({ ok: true, updated: existing });
        }
        s.appendRow(row);
        return jsonOut({ ok: true, added: s.getLastRow() });
      }
      if (action === 'deleteProduct') {
        s = ss().getSheetByName(SHEET_PRODUCTS);
        var delRow = findProductRow(body.productUrl || '');
        if (delRow > 0) { s.deleteRow(delRow); return jsonOut({ ok: true }); }
        return jsonOut({ ok: false, error: 'product not found' });
      }
      if (action === 'bulkImport') {
        // body.csv: lines of comma-separated values in the 46-column order
        s = ss().getSheetByName(SHEET_PRODUCTS);
        var lines = String(body.csv || '').split(/\r?\n/).filter(function (l) { return l.trim(); });
        var added = 0;
        lines.forEach(function (line) {
          var vals = line.split(',').map(function (v) { return v.trim(); });
          if (vals.length < 8 || !vals[4]) return;
          while (vals.length < 46) vals.push('');
          s.appendRow(vals.slice(0, 46));
          added++;
        });
        return jsonOut({ ok: true, added: added });
      }
      if (action === 'bulkEdit') {
        // body: {brand, field (header name), value}
        headers = productHeaders();
        var fieldIdx = headers.indexOf(body.field);
        if (fieldIdx < 0) throw new Error('unknown field: ' + body.field);
        s = ss().getSheetByName(SHEET_PRODUCTS);
        var all = s.getDataRange().getValues();
        var changed = 0;
        for (i = 1; i < all.length; i++) {
          if (body.brand && all[i][2] !== body.brand) continue;
          if (all[i][fieldIdx] !== body.value) {
            s.getRange(i + 1, fieldIdx + 1).setValue(body.value);
            changed++;
          }
        }
        return jsonOut({ ok: true, changed: changed });
      }
      if (action === 'saveCoupon') {
        s = sheet(SHEET_COUPONS);
        var c = body.coupon || {};
        var rows = s.getDataRange().getValues();
        for (i = 1; i < rows.length; i++) {
          if (rows[i][0] === c.id) {
            s.getRange(i + 1, 1, 1, 9).setValues([[c.id, c.title, c.store, c.code, c.value, c.redirect_url, c.expires_at, c.active, c.description || '']]);
            return jsonOut({ ok: true, updated: c.id });
          }
        }
        s.appendRow([c.id || ('cp-' + Date.now()), c.title, c.store, c.code, c.value, c.redirect_url, c.expires_at, c.active !== false, c.description || '']);
        return jsonOut({ ok: true, added: true });
      }
      if (action === 'deleteCoupon') {
        s = sheet(SHEET_COUPONS);
        var cr = s.getDataRange().getValues();
        for (i = 1; i < cr.length; i++) {
          if (cr[i][0] === body.id) { s.deleteRow(i + 1); return jsonOut({ ok: true }); }
        }
        return jsonOut({ ok: false, error: 'coupon not found' });
      }
      if (action === 'saveGuide') {
        s = sheet(SHEET_GUIDES);
        var g = body.guide || {};
        var gr = s.getDataRange().getValues();
        for (i = 1; i < gr.length; i++) {
          if (gr[i][0] === g.slug) {
            s.getRange(i + 1, 1, 1, 9).setValues([[g.slug, g.title, g.criterion, g.description, g.human_review || '', g.status || 'draft', g.author || 'فريق عروض أونلاين', g.date || '', g.publish_at || '']]);
            return jsonOut({ ok: true, updated: g.slug });
          }
        }
        s.appendRow([g.slug, g.title, g.criterion, g.description, g.human_review || '', g.status || 'draft', g.author || 'فريق عروض أونلاين', g.date || '', g.publish_at || '']);
        return jsonOut({ ok: true, added: true });
      }
      if (action === 'saveNews') {
        s = sheet(SHEET_NEWS);
        var n = body.news || {};
        var nr = s.getDataRange().getValues();
        for (i = 1; i < nr.length; i++) {
          if (nr[i][0] === n.slug) {
            s.getRange(i + 1, 1, 1, 9).setValues([[n.slug, n.title, n.description, n.body, n.model_slug || '', n.author || 'فريق عروض أونلاين', n.date_published || '', !!n.is_example, n.publish_at || '']]);
            return jsonOut({ ok: true, updated: n.slug });
          }
        }
        s.appendRow([n.slug, n.title, n.description, n.body, n.model_slug || '', n.author || 'فريق عروض أونلاين', n.date_published || '', !!n.is_example, n.publish_at || '']);
        return jsonOut({ ok: true, added: true });
      }
      if (action === 'syncNow') {
        sheet(SHEET_SYNCLOG).appendRow([new Date(), 'sync-requested', 'requested from admin panel']);
        return jsonOut({ ok: true, note: 'سيتم التقاط التحديث في المزامنة التالية (كل ساعة) أو بتشغيل scripts/sync.py يدوياً' });
      }
      if (action === 'deleteGuide') {
        s = sheet(SHEET_GUIDES);
        var gr = s.getDataRange().getValues();
        for (i = 1; i < gr.length; i++) {
          if (gr[i][0] === body.slug) { s.deleteRow(i + 1); return jsonOut({ ok: true }); }
        }
        return jsonOut({ ok: false, error: 'guide not found' });
      }
      if (action === 'deleteNews') {
        s = sheet(SHEET_NEWS);
        var nr2 = s.getDataRange().getValues();
        for (i = 1; i < nr2.length; i++) {
          if (nr2[i][0] === body.slug) { s.deleteRow(i + 1); return jsonOut({ ok: true }); }
        }
        return jsonOut({ ok: false, error: 'news not found' });
      }
      if (action === 'fixAffiliate') {
        // rewrite every mismatched/missing AU link from its column-E product URL
        s = ss().getSheetByName(SHEET_PRODUCTS);
        var fv = s.getDataRange().getValues();
        var fixed = 0;
        for (i = 1; i < fv.length; i++) {
          var fe = fv[i][4];
          if (!fe || String(fe).indexOf('jumia.com.eg') === -1) continue;
          var fexp = buildTrackingUrl(fe);
          if (fv[i][46] !== fexp) { s.getRange(i + 1, 47).setValue(fexp); fixed++; }
        }
        return jsonOut({ ok: true, fixed: fixed });
      }
      if (action === 'markHandled') {
        // shared handled state for requests/reports (visible on all devices)
        var h = sheet(SHEET_HANDLED);
        var hr = h.getDataRange().getValues();
        var ts = new Date(body.timestamp || 0).getTime();
        for (i = 1; i < hr.length; i++) {
          if (hr[i][0] === (body.kind || '') &&
              new Date(hr[i][1]).getTime() === ts &&
              hr[i][2] === (body.model || '')) {
            if (!body.done) h.deleteRow(i + 1);
            return jsonOut({ ok: true, done: !!body.done });
          }
        }
        if (body.done) h.appendRow([body.kind || '', new Date(body.timestamp || 0), body.model || '']);
        return jsonOut({ ok: true, done: !!body.done });
      }
      if (action === 'fetchProductImage') {
        var purl = String(body.productUrl || '').trim();
        if (!purl) throw new Error('رابط المنتج مطلوب — الصق رابط المنتج الأصلي أولاً');
        var img = fetchOgImage(purl);
        if (!img) throw new Error('تعذّر العثور على صورة في صفحة المنتج — قد تكون الصفحة محمية (Cloudflare) أو بلا og:image. انسخ رابط الصورة يدوياً من المتجر.');
        return jsonOut({ ok: true, image: img });
      }
      if (action === 'publishScheduled') {
        return jsonOut(publishScheduled());
      }
      if (action === 'setupScheduledPublish') {
        deleteTriggersFor('publishScheduled');
        ScriptApp.newTrigger('publishScheduled').timeBased().everyHours(1).create();
        var now = publishScheduled();
        return jsonOut({ ok: true, publishedGuides: now.publishedGuides, publishedNews: now.publishedNews });
      }
      if (action === 'setupDailyBuyLinksCheck') {
        deleteTriggersFor('dailyBuyLinksCheck');
        ScriptApp.newTrigger('dailyBuyLinksCheck').timeBased().everyDays(1).atHour(4).create();
        return jsonOut({ ok: true });
      }
      if (action === 'backupNow') {
        return jsonOut(backupSheet());
      }
      if (action === 'setupDailyBackup') {
        deleteTriggersFor('dailyBackup');
        ScriptApp.newTrigger('dailyBackup').timeBased().everyDays(1).atHour(3).create();
        return jsonOut({ ok: true });
      }
      if (action === 'setupDailyAffiliateCheck') {
        deleteTriggersFor('dailyAffiliateCheck');
        ScriptApp.newTrigger('dailyAffiliateCheck').timeBased().everyDays(1).atHour(5).create();
        return jsonOut({ ok: true });
      }
      if (action === 'lockAffiliateColumn') {
        var ls = ss().getSheetByName(SHEET_PRODUCTS);
        // remove any older AU protection first (protect() on an already
        // protected range would stack a second protection)
        ls.getProtections(SpreadsheetApp.ProtectionType.RANGE).forEach(function (p) {
          var rg = p.getRange();
          if (rg.getColumn() === 47 && rg.getNumColumns() === 1) p.remove();
        });
        ls.getRange(1, 47, Math.max(ls.getLastRow(), 1), 1).protect()
          .setDescription('عمود روابط الأفلييت (AU) — محمي من التعديل اليدوي والفرز الخاطئ');
        return jsonOut({ ok: true, locked: true });
      }
      if (action === 'unlockAffiliateColumn') {
        var us = ss().getSheetByName(SHEET_PRODUCTS);
        var removed = 0;
        us.getProtections(SpreadsheetApp.ProtectionType.RANGE).forEach(function (p) {
          var rg = p.getRange();
          if (rg.getColumn() === 47 && rg.getNumColumns() === 1) { p.remove(); removed++; }
        });
        return jsonOut({ ok: true, unlocked: removed });
      }
      if (action === 'setupWeeklyTrigger') {
        return jsonOut(setupWeeklyTrigger());
      }
      return jsonOut({ ok: false, error: 'unknown action: ' + action });
    } finally {
      lock.releaseLock();
    }
  } catch (err) {
    return jsonOut({ ok: false, error: String(err) });
  }
}

/* ---------------------------------------------------- weekly report */
function weeklyReport() {
  var clicks = sheet(SHEET_CLICKS).getDataRange().getValues().slice(1);
  var reports = sheet(SHEET_REPORTS).getDataRange().getValues().slice(1);
  var requests = sheet(SHEET_REQUESTS).getDataRange().getValues().slice(1);
  var byModel = {};
  clicks.forEach(function (r) { byModel[r[2]] = (byModel[r[2]] || 0) + 1; });
  var top = Object.keys(byModel).sort(function (a, b) { return byModel[b] - byModel[a]; }).slice(0, 5);
  var lines = [
    'التقرير الأسبوعي — عروض أونلاين 3rde.online',
    '',
    'نقرات أزرار الشراء هذا الأسبوع: ' + clicks.length,
    'أكثر المنتجات نقراً:',
  ];
  top.forEach(function (m, i) { lines.push('  ' + (i + 1) + '. ' + m + ' — ' + byModel[m] + ' نقرة'); });
  lines.push('');
  lines.push('بلاغات أسعار خاطئة: ' + reports.length);
  lines.push('طلبات منتجات غير موجودة: ' + requests.length);
  lines.push('');
  lines.push('لوحة التحكم: افتح admin/index.html — البريد: ' + ADMIN_EMAIL);
  MailApp.sendEmail(ADMIN_EMAIL, 'التقرير الأسبوعي — عروض أونلاين', lines.join('\n'));
}

function setupWeeklyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'weeklyReport') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('weeklyReport').timeBased().everyWeeks(1)
    .onWeekDay(ScriptApp.WeekDay.SUNDAY).atHour(9).create();
  return { ok: true };
}

/**
 * onEdit — auto-stamp «تاريخ آخر تحديث» (column Z, 26) with today's date
 * whenever ANY other cell in the same product row of الورقة1 is edited.
 * This is a simple trigger: it runs automatically once this script is
 * saved in the Sheet's Apps Script project — no install, no deployment.
 * A plain formula cannot do this (a formula cannot detect edits; TODAY()
 * would just show the current day for every row, every day).
 * The date is written as a value in DD-MM-YYYY format, matching the
 * existing dates in the column.
 */
function onEdit(e) {
  if (!e || !e.range) return;
  var sh = e.range.getSheet();
  if (!sh || sh.getName() !== SHEET_PRODUCTS) return;
  var row = e.range.getRow();
  if (row < 2) return; // header row
  var DATE_COL = 26; // Z = «تاريخ آخر تحديث»
  if (e.range.getColumn() === DATE_COL) return; // editing the date itself: don't loop
  var today = new Date();
  var dd = ('0' + today.getDate()).slice(-2);
  var mm = ('0' + (today.getMonth() + 1)).slice(-2);
  var yyyy = today.getFullYear();
  sh.getRange(row, DATE_COL).setValue(dd + '-' + mm + '-' + yyyy);
}
