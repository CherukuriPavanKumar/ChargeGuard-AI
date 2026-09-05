// One-off script to capture real screenshots of the running dev server for
// the README. Not part of the app — run once, then delete (or keep for the
// next time the README's screenshots need refreshing).
//
// Usage: node capture-screenshots.mjs <devServerUrl> <outDir>
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const url = process.argv[2] || 'http://localhost:5182';
const outDir = process.argv[3] || '../../docs/screenshots';
fs.mkdirSync(outDir, { recursive: true });

const shot = async (page, name) => {
  await page.screenshot({ path: path.join(outDir, `${name}.png`) });
  console.log('captured', name);
};

const run = async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  // 1) Particle preloader mid-assembly (word legible).
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(3600);
  await shot(page, '01-preloader');

  // 2) Resting hero: editorial column + card + satellites.
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.evaluate(() => {
    // Skip the intro deterministically via Escape rather than waiting it out.
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
  });
  await page.waitForTimeout(900);
  await shot(page, '02-hero-landing');

  // 3) Exploded 3D plates (layer split).
  await page.evaluate(() => {
    const hero = document.getElementById('hero');
    const range = hero.offsetHeight - window.innerHeight;
    window.scrollTo(0, Math.round(0.28 * range));
  });
  await page.waitForTimeout(600);
  await shot(page, '03-exploded-plates');

  // 4) Ring formed + one plate focused (drag the cursor across the stage).
  await page.evaluate(() => {
    const hero = document.getElementById('hero');
    const range = hero.offsetHeight - window.innerHeight;
    window.scrollTo(0, Math.round(0.75 * range));
  });
  await page.waitForTimeout(500);
  await page.mouse.move(1100, 450);
  await page.mouse.move(500, 450, { steps: 12 });
  await page.waitForTimeout(700);
  await shot(page, '04-ring-focus');

  // 5) Spatial workflow — neural lattice.
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.evaluate(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })));
  await page.waitForTimeout(500);
  const lattice = await page.locator('text=The lattice reads').first();
  await lattice.scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(600);
  await shot(page, '05-neural-lattice');

  // 6) Economic sandtable.
  const sandtable = await page.locator('text=governor sees').first();
  await sandtable.scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(400);
  await shot(page, '06-economic-sandtable');

  // 7) Attack simulator, after a real Auto-Contest run.
  const sim = await page.locator('text=Run the attack').first();
  await sim.scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(300);
  const btn = await page.locator('button:has-text("Auto-Contest Dispute")').first();
  await btn.click().catch(() => {});
  await page.waitForTimeout(3200);
  await shot(page, '07-attack-simulator');

  // 8) Evaluation dashboard.
  const evalHeading = await page.locator('#eval').first();
  await evalHeading.scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(500);
  await shot(page, '08-eval-dashboard');

  // 9) Mobile hero.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.evaluate(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })));
  await page.waitForTimeout(700);
  await shot(page, '09-mobile');

  await browser.close();
};

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
