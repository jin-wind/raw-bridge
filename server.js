const http = require("http");
const net = require("net");
const fs = require("fs");
const path = require("path");
const yaml = require("js-yaml");

// ── Config ──────────────────────────────────────────────────────────────────
function loadConfig(configPath) {
  const abs = path.resolve(configPath);
  if (!fs.existsSync(abs)) {
    console.warn(`⚠️  Config not found: ${abs}, using defaults`);
    return {};
  }
  return yaml.load(fs.readFileSync(abs, "utf8")) || {};
}

// ── Entry ───────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
let configPath = "config.yaml";
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--config" && args[i + 1]) configPath = args[i + 1];
}

const config = loadConfig(configPath);
const proxyCfg = config.proxy || {};
const host = proxyCfg.listen_host || "127.0.0.1";
const port = parseInt(proxyCfg.listen_port || "8080", 10);

// ── CONNECT Tunnel Proxy ────────────────────────────────────────────────────
const server = http.createServer();

server.on("connect", (req, clientSocket, head) => {
  // req.url = "new.sharedchat.cc:443"
  const [targetHost, targetPort] = req.url.split(":");
  const tPort = parseInt(targetPort || "443", 10);

  console.log(`CONNECT ${targetHost}:${tPort}`);

  const targetSocket = net.connect(tPort, targetHost, () => {
    clientSocket.write("HTTP/1.1 200 Connection Established\r\n\r\n");
    targetSocket.write(head);
    targetSocket.pipe(clientSocket);
    clientSocket.pipe(targetSocket);
  });

  targetSocket.on("error", (err) => {
    console.error(`Target error: ${err.message}`);
    clientSocket.end("HTTP/1.1 502 Bad Gateway\r\n\r\n");
  });

  clientSocket.on("error", (err) => {
    console.error(`Client error: ${err.message}`);
    targetSocket.destroy();
  });
});

// ── Regular HTTP request handler (fallback) ─────────────────────────────────
server.on("request", (req, res) => {
  // Normal HTTP forwarding (non-CONNECT)
  const targetBase = (proxyCfg.target_base_url || "").replace(/\/+$/, "");
  if (!targetBase) {
    res.writeHead(400);
    res.end("No target_base_url configured");
    return;
  }

  const targetUrl = targetBase + req.url;
  const { URL } = require("url");
  const parsed = new URL(targetUrl);
  const https = require("https");
  const httpMod = require("http");

  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", () => {
    const body = Buffer.concat(chunks);
    const options = {
      hostname: parsed.hostname,
      port: parsed.port || (parsed.protocol === "https:" ? 443 : 80),
      path: parsed.pathname + parsed.search,
      method: req.method,
      headers: { ...req.headers, host: parsed.hostname },
    };

    const requester = parsed.protocol === "https:" ? https : httpMod;
    const upstreamReq = requester.request(options, (upstreamRes) => {
      const resChunks = [];
      upstreamRes.on("data", (c) => resChunks.push(c));
      upstreamRes.on("end", () => {
        res.writeHead(upstreamRes.statusCode, upstreamRes.headers);
        res.end(Buffer.concat(resChunks));
      });
    });
    upstreamReq.on("error", (err) => {
      res.writeHead(502);
      res.end(`Upstream error: ${err.message}`);
    });
    if (body.length > 0) upstreamReq.write(body);
    upstreamReq.end();
  });
});

server.listen(port, host, () => {
  console.log(`🚀 raw-bridge CONNECT proxy on http://${host}:${port}`);
  console.log(`   Configure as HTTPS proxy in Codex/Claude Code`);
});
