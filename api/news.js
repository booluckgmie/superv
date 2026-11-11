// Same-origin proxy for the daily news CSV, so the browser does not depend on
// reaching raw.githubusercontent.com directly (some networks and extensions block it).
const SOURCES = [
  'https://raw.githubusercontent.com/booluckgmie/sharecode/refs/heads/master/marketIntel/marketGAlerts2025.csv',
  'https://cdn.jsdelivr.net/gh/booluckgmie/sharecode@master/marketIntel/marketGAlerts2025.csv'
];

module.exports = async function handler(req, res) {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.setHeader('Allow', 'GET, HEAD');
    return res.status(405).end();
  }
  let lastStatus = 0;
  for (const url of SOURCES) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(20000) });
      if (!r.ok) { lastStatus = r.status; continue; }
      const text = await r.text();
      res.setHeader('Content-Type', 'text/csv; charset=utf-8');
      // Cache at the edge for 10 min, serve stale for a day while refreshing.
      res.setHeader('Cache-Control', 'public, s-maxage=600, stale-while-revalidate=86400');
      return res.status(200).send(text);
    } catch (e) { lastStatus = 0; }
  }
  res.setHeader('Cache-Control', 'no-store');
  return res.status(502).json({ error: 'upstream_unavailable', status: lastStatus });
};
