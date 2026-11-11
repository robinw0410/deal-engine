// Browser driver for tests/test_platform_filter.py (Node + Playwright, Chromium).
//   node platform_filter_driver.js scenario <page.html>   -> JSON snapshots of the filter scenario
//   node platform_filter_driver.js nojs <page.html>       -> JSON with the cards visible without JavaScript
//   node platform_filter_driver.js stale <page.html>      -> JSON: load with an outdated saved view
//   node platform_filter_driver.js broken <page.html>     -> JSON: cards visible after a script error
//   node platform_filter_driver.js plain <page.html>      -> JSON snapshots: load, click chip "shirt"
// The page is served from http://de.test/s/ by request interception (no network, no server).
// Exit code 3: Playwright or Chromium not available (the test skips).
'use strict';
const fs = require('fs');

let chromium;
try { ({ chromium } = require('playwright')); } catch (e) {
  console.error('playwright not available: ' + e.message); process.exit(3);
}

const [mode, file] = process.argv.slice(2);
const html = fs.readFileSync(file, 'utf8');
const BASE = 'http://de.test/s/';

async function snap(page) {
  return page.evaluate(() => {
    const tb = document.getElementById('topbar');
    return {
      search: location.search,
      visible: [...document.querySelectorAll('#groups details.card .t')].map(e => e.textContent).sort(),
      count: document.getElementById('count').textContent,
      poolHidden: document.getElementById('pool').hidden,
      topbarHidden: tb ? tb.hidden : null,
      topbarHTML: tb ? tb.innerHTML : '',
      rows: [...document.querySelectorAll('.fchips')].map(r => ({
        k: r.dataset.k, top: !!r.closest('#topbar'),
        buttons: [...r.querySelectorAll('.fchip')].map(b => ({
          all: b.classList.contains('all'), v: b.dataset.v === undefined ? null : b.dataset.v,
          text: b.firstChild ? b.firstChild.textContent : '',
          n: b.querySelector('small') ? b.querySelector('small').textContent : null,
          on: b.classList.contains('on'),
        })),
      })),
    };
  });
}

async function main() {
  let browser;
  try { browser = await chromium.launch(); } catch (e) {
    console.error('chromium does not start: ' + e.message); process.exit(3);
  }
  const res = { errors: [], dialogs: [] };
  try {
    if (mode === 'nojs') {
      const ctx = await browser.newContext({ javaScriptEnabled: false });
      const page = await ctx.newPage();
      await page.route('http://de.test/**', r => r.fulfill({ contentType: 'text/html; charset=utf-8', body: html }));
      await page.goto(BASE);
      res.visible = await page.evaluate(() => [...document.querySelectorAll('details.card')]
        .filter(e => e.getClientRects().length > 0).map(e => e.querySelector('.t').textContent).sort());
    } else if (mode === 'stale' || mode === 'broken') {
      const page = await (await browser.newContext()).newPage();
      page.on('pageerror', e => res.errors.push(String(e)));
      await page.route('http://de.test/**', r => r.fulfill({ contentType: 'text/html; charset=utf-8', body: html }));
      await page.goto(BASE);
      if (mode === 'stale') {
        await page.evaluate(() => localStorage.setItem('de-view-' + location.pathname,
          JSON.stringify({ group: 'gone', chips: { cat: 'shirt' }, tg: { gone: true }, sort: 'gone' })));
        await page.goto(BASE);
        res.initial = await snap(page);
      } else {
        res.visible = await page.evaluate(() => [...document.querySelectorAll('details.card')]
          .filter(e => e.getClientRects().length > 0).map(e => e.querySelector('.t').textContent).sort());
      }
    } else if (mode === 'plain') {
      const page = await (await browser.newContext()).newPage();
      page.on('pageerror', e => res.errors.push(String(e)));
      await page.route('http://de.test/**', r => r.fulfill({ contentType: 'text/html; charset=utf-8', body: html }));
      await page.goto(BASE);
      res.initial = await snap(page);
      await page.click('#chips .fchip[data-v="shirt"]');
      res.cat = await snap(page);
    } else {
      const ctx = await browser.newContext();
      const page = await ctx.newPage();
      page.on('pageerror', e => res.errors.push(String(e)));
      page.on('dialog', d => { res.dialogs.push(d.message()); d.dismiss(); });
      await page.route('http://de.test/**', r => r.fulfill({ contentType: 'text/html; charset=utf-8', body: html }));
      const top = v => page.click(`#topbar .fchip[data-v="${v}"]`);

      await page.goto(BASE + '?foo=1');
      res.initial = await snap(page);
      await top('vinted');
      res.vinted = await snap(page);
      await top('ebay');
      res.vinted_ebay = await snap(page);
      await page.goBack();
      res.back = await snap(page);
      await page.goForward();
      res.forward = await snap(page);
      await page.click('#topbar .fchip.all');
      res.all = await snap(page);
      await page.goto(BASE + '?src=ebay');
      res.url_ebay = await snap(page);
      await page.goto(BASE);
      res.stored = await snap(page);
      await page.click('#chips .fchip[data-v="shirt"]');
      res.cat = await snap(page);
      await page.fill('#q', 'combo');
      res.search = await snap(page);
      await page.click('#reset');
      res.reset = await snap(page);
      await page.goto(BASE + '?src=' + encodeURIComponent('<script>alert(1)</script>') + ','
                      + encodeURIComponent('<img src=x onerror=alert(2)>') + ',vinted');
      res.evil = await snap(page);
      await page.goto(BASE + '?src=ebay%2Cvinted');
      res.encoded = await snap(page);
    }
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify(res));
}

main().catch(e => { console.error(e && e.stack || String(e)); process.exit(1); });
