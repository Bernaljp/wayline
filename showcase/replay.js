// The showcase's replay (`showcase/build.py` writes the recordings it reads): the dashboard's own page, with no server.
//
// The page asks for `/api/...` by absolute path, which on a static host leads nowhere. Loaded before `app.js`, this
// answers instead: a `fetch` from the recordings `showcase.json` lists, with 304 to an `If-None-Match` a recording of the
// same path carries, so a poll costs nothing and a tail asking for what follows its first screenful hears that nothing
// is new; a link or an image naming a download or a page of the documentation site, from the copy published under
// `files/` or `site/`. Anything else answers 404 with a line saying it is not part of the showcase, and a POST is
// refused, though the page, opened without its token, sends none.

'use strict';

(() => {
  const ROOT = new URL('.', document.currentScript.src);
  const nativeFetch = window.fetch.bind(window);
  // A download (`download/<path>`) or a page of the documentation site (`site/<path>`).
  const SERVED = /^\/api\/projects\/[^/]+\/(download|site)\/(.*)$/;
  const JSON_TYPE = 'application/json; charset=utf-8';
  let showcase = null;
  let published = new Set();
  const ready = nativeFetch(new URL('showcase.json', ROOT), { cache: 'no-cache' })
    .then((response) => response.json())
    .then((value) => {
      showcase = value;
      published = new Set(value.files);
      return value;
    });
  // What the page asked for that no recording answers and no line accounts for, and how many of its requests are still
  // being answered, which tests/test_showcase_browser.py reads.
  window.showcaseMisses = [];
  window.showcasePending = 0;

  const encodePath = (path) => path.split('/').map(encodeURIComponent).join('/');
  const decodePath = (path) => path.split('/').map(decodeURIComponent).join('/');

  // Where the showcase publishes what a download or site path names, or null when it holds no copy.
  function publishedAt(pathname) {
    const match = pathname.match(SERVED);
    const path = decodePath(match[2]);
    if (match[1] === 'site') return new URL(`site/${encodePath(path || 'index.html')}`, ROOT).href;
    return !showcase || published.has(path) ? new URL(`files/${encodePath(path)}`, ROOT).href : null;
  }

  // A `src` or `href` the page sets, pointed at the published copy, or at the page saying there is none.
  function local(value) {
    if (typeof value !== 'string' || !value.startsWith('/api/')) return value;
    const url = new URL(value, location.origin);
    const match = url.pathname.match(SERVED);
    if (!match) return value;
    return publishedAt(url.pathname) || new URL(`withheld.html#${encodeURIComponent(decodePath(match[2]))}`, ROOT).href;
  }

  // A request as `showcase/build.py` recorded it: the path decoded, then the query sorted, without the token.
  function keyOf(url) {
    const query = [...url.searchParams].filter(([name]) => name !== 'token').sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    const search = new URLSearchParams(query).toString();
    return decodePath(url.pathname) + (search ? `?${search}` : '');
  }

  function answer(status, body, type, etag) {
    const headers = { 'Content-Type': type || 'text/plain; charset=utf-8' };
    if (etag) headers.ETag = etag;
    return new Response(status === 304 ? null : body, { status, headers });
  }

  function notHere(url) {
    const path = decodePath(url.pathname);
    const lines = showcase.withheld;
    if (path.includes('/logs/session/')) return answer(404, lines.transcripts);
    if (path.includes('/logs/tick/')) return answer(404, lines.tick);
    window.showcaseMisses.push(keyOf(url));
    const item = path.match(/\/items\/([^/]+)$/);
    if (item) return answer(404, JSON.stringify({ found: false, id: item[1], line: lines.item.replace('{id}', item[1]) }), JSON_TYPE);
    return answer(404, lines.missing.replace('{path}', path));
  }

  window.fetch = async (input, init) => {
    const request = new Request(input, init);
    const url = new URL(request.url);
    if (url.origin !== location.origin || !url.pathname.startsWith('/api/')) return nativeFetch(input, init);
    window.showcasePending += 1;
    try {
      return await replay(request, url);
    } finally {
      window.showcasePending -= 1;
    }
  };

  async function replay(request, url) {
    await ready;
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return answer(403, JSON.stringify({ ok: false, error: showcase.withheld.action }), JSON_TYPE);
    }
    const served = url.pathname.match(SERVED);
    if (served) {
      const at = publishedAt(url.pathname);
      return at ? nativeFetch(at, { cache: 'no-cache' }) : answer(404, showcase.withheld.file.replace('{path}', decodePath(served[2])));
    }
    const recording = showcase.recordings[keyOf(url)];
    const tag = request.headers.get('If-None-Match');
    if (recording) {
      if (tag && tag === recording.etag) return answer(304, null, recording.type, tag);
      const body = await (await nativeFetch(new URL(recording.body, ROOT), { cache: 'no-cache' })).arrayBuffer();
      return answer(recording.status, body, recording.type, recording.etag);
    }
    if (tag && (showcase.tags[decodePath(url.pathname)] || []).includes(tag)) return answer(304, null, null, tag);
    return notHere(url);
  }

  const setAttribute = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    return setAttribute.call(this, name, name === 'src' || name === 'href' ? local(value) : value);
  };
  for (const [type, name] of [[HTMLAnchorElement, 'href'], [HTMLImageElement, 'src']]) {
    const property = Object.getOwnPropertyDescriptor(type.prototype, name);
    Object.defineProperty(type.prototype, name, { ...property, set(value) { property.set.call(this, local(String(value))); } });
  }

  // What this page is, above the dashboard's own header, which stays sticky once it scrolls away.
  const style = document.createElement('style');
  style.textContent = `
    #showcase-banner { box-sizing: border-box; width: 100%; margin: 0; padding: 8px 16px; background: var(--accent-soft);
      color: var(--ink); border-bottom: 1px solid var(--line); font: 13px/1.5 var(--prose); overflow-wrap: anywhere; }
    #showcase-banner a { color: var(--accent-ink); }`;
  document.head.append(style);
  ready.then((value) => {
    const banner = document.createElement('aside');
    banner.id = 'showcase-banner';
    banner.setAttribute('aria-label', 'about this showcase');
    const title = document.createElement('strong');
    title.textContent = value.banner.title;
    banner.append(title, ` ${value.banner.text} `);
    value.banner.links.forEach(([label, href], index) => {
      const link = document.createElement('a');
      link.textContent = label;
      link.href = href;
      if (/^https?:/.test(href)) {
        link.target = '_blank';
        link.rel = 'noopener';
      }
      banner.append(index ? ' · ' : '', link);
    });
    document.body.prepend(banner);
  });
})();
