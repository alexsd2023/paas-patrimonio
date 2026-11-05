// trafico-contador: Routing Middleware de Vercel (sitio estático).
// Registra en el panel «Tráfico de Proyectos» los bots que visitan la web (user-agent de bot o rutas
// de escáner). Los humanos se cuentan con el script de cada página. Si no es un bot, no hace nada.

const TRAFICO_URL = "https://epfszizoeedjjyogmqev.supabase.co/functions/v1/track";
// Señales de bot en el user-agent (el colector hace la clasificación fina; aquí solo se filtra qué avisar).
const BOT_UA = /bot|crawl|spider|slurp|scrap|fetch|preview|headless|lighthouse|pagespeed|gtmetrix|curl|wget|python|go-http|java\/|okhttp|axios|node|undici|httpx|aiohttp|postman|insomnia|libwww|phantom|puppeteer|playwright|selenium|cypress|facebookexternalhit|facebot|whatsapp|telegram|discord|slack|embedly|iframely|pinterest|mastodon|bluesky|cardyb|skypeuripreview|vkshare|gptbot|chatgpt|oai-search|claude|anthropic|perplexity|ccbot|bytespider|amazonbot|meta-external|cohere|mistral|diffbot|googleother|vercel|uptime|pingdom|statuscake|site24x7|checkly|datadog|censys|expanse|zgrab|masscan|nmap|nuclei|sqlmap|nikto|wpscan|leakix|l9explore|scan/i;
// Rutas que solo pide quien busca vulnerabilidades.
const RUTA_SOSPECHOSA = /(^|\/)(wp-|wordpress|xmlrpc\.php|phpmyadmin|pma\/|\.env|\.git\/|\.aws\/|\.ssh|config\.(php|json|yml)|cgi-bin|boaform|actuator|vendor\/phpunit|server-status|HNAP1|\.DS_Store|admin\.php|setup\.php|shell|eval-stdin)|\.(php|asp|aspx|jsp|cgi)$/i;
// Recursos estáticos: no se cuentan.
const RECURSO = /\.(js|mjs|css|map|png|jpe?g|gif|svg|ico|webp|avif|woff2?|ttf|otf|eot|mp4|webm|mp3|wav)$/i;

function esCandidato(ua, path) {
  if (RECURSO.test(path) && !RUTA_SOSPECHOSA.test(path)) return false;
  return !ua || !/^(Mozilla|Opera)\//.test(ua) || BOT_UA.test(ua) || RUTA_SOSPECHOSA.test(path);
}

function avisoBot(app, request) {
  const url = new URL(request.url);
  const h = request.headers;
  const ua = h.get("user-agent") || "";
  if (!esCandidato(ua, url.pathname)) return null;
  let city = h.get("x-vercel-ip-city");
  try { city = city ? decodeURIComponent(city) : null; } catch { /* se deja tal cual */ }
  return fetch(TRAFICO_URL, {
    method: "POST",
    headers: { "content-type": "text/plain" },
    body: JSON.stringify({
      src: "server", app, ua, host: url.hostname, path: url.pathname,
      ref: h.get("referer") || "", cc: h.get("x-vercel-ip-country") || null,
      region: h.get("x-vercel-ip-country-region") || null, city,
    }),
  }).catch(() => {});
}

export default async function middleware(request, context) {
  const aviso = avisoBot("paas", request);
  if (aviso) {
    if (context && typeof context.waitUntil === "function") context.waitUntil(aviso);
    else await aviso;
  }
  // Sin respuesta propia: la petición sigue su curso normal.
}
