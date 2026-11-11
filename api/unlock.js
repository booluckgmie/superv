// Passcode check for the access gate.
// The passcode lives in the Vercel Environment Variable APP_ACCESS_KEY and is
// never sent to the browser; the page only learns whether its guess was right.
const crypto = require('crypto');

function safeEqual(a, b) {
  const ha = crypto.createHash('sha256').update(String(a)).digest();
  const hb = crypto.createHash('sha256').update(String(b)).digest();
  return crypto.timingSafeEqual(ha, hb);
}

module.exports = async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ ok: false });
  }
  const expected = process.env.APP_ACCESS_KEY;
  if (!expected) return res.status(500).json({ ok: false, error: 'not_configured' });

  let body = req.body;
  if (typeof body === 'string') { try { body = JSON.parse(body); } catch (e) { body = {}; } }
  const code = body && typeof body.code === 'string' ? body.code.slice(0, 200) : '';

  if (code && safeEqual(code, expected)) return res.status(200).json({ ok: true });
  return res.status(401).json({ ok: false });
};
