"""公开网络下载：固定解析地址、逐跳检查和 robots 策略。"""

import http.client
import ipaddress
import socket
import ssl
import time
from urllib import robotparser
from urllib.parse import urljoin, urlsplit, urlunsplit

import certifi

from .ollama_client import AIError

AGENT = "SKYDataWorkspace"
MAX_BYTES = 5 * 1024 * 1024


def normalize_url(value: str) -> str:
    try:
        p = urlsplit(value.strip())
        if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
            raise ValueError()
        if p.port not in {None, 80, 443}:
            raise ValueError()
        host = p.hostname.encode("idna").decode("ascii")
        authority = f"[{host}]" if ":" in host else host
        if p.port:
            authority += ":" + str(p.port)
        return urlunsplit((p.scheme, authority, p.path or "/", p.query, ""))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("只支持不含凭据、使用标准端口的 HTTP/HTTPS 网址") from exc


def public_addresses(host: str, port: int) -> list[str]:
    try:
        addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    except socket.gaierror as exc:
        raise AIError("dns_error", "域名解析失败") from exc
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise AIError("blocked_address", "已阻止本机、内网、保留地址或混合解析目标")
    return addresses


class _HTTP(http.client.HTTPConnection):
    def __init__(self, host, port, address):
        super().__init__(host, port, timeout=12)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


class _HTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, address):
        context = ssl.create_default_context(cafile=certifi.where())
        context.load_default_certs()
        super().__init__(host, port, timeout=12, context=context)
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


class SafeDownloader:
    def __init__(self):
        self.last_request: dict[str, float] = {}
        self.robots: dict[str, robotparser.RobotFileParser] = {}

    def _download(self, url: str, check, *, limit=MAX_BYTES, redirect_policy=None) -> dict:
        url = normalize_url(url)
        for _ in range(6):
            check()
            if redirect_policy:
                redirect_policy(url, check)
            p = urlsplit(url)
            port = p.port or (443 if p.scheme == "https" else 80)
            addresses = public_addresses(p.hostname, port)
            delay = 0.8 - (time.monotonic() - self.last_request.get(p.netloc, 0))
            if delay > 0:
                time.sleep(delay)
            check()
            self.last_request[p.netloc] = time.monotonic()
            connection = (_HTTPS if p.scheme == "https" else _HTTP)(p.hostname, port, addresses[0])
            try:
                connection.request("GET", p.path + ("?" + p.query if p.query else ""),
                                   headers={"User-Agent": AGENT + "/0.2", "Accept-Encoding": "identity"})
                response = connection.getresponse()
                status = response.status
                if status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    if not location:
                        raise AIError("invalid_redirect", "重定向缺少目标地址")
                    url = normalize_url(urljoin(url, location))
                    continue
                declared = response.getheader("Content-Length")
                if declared and int(declared) > limit:
                    raise AIError("download_too_large", "下载内容超过大小限制")
                data = bytearray()
                started = time.monotonic()
                while True:
                    check()
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > limit or time.monotonic() - started > 45:
                        raise AIError("download_limit", "下载超过大小或时长限制")
                return {"url": url, "status": status, "content": bytes(data),
                        "content_type": response.getheader("Content-Type", ""),
                        "retry_after": response.getheader("Retry-After", "1")}
            except (socket.timeout, TimeoutError) as exc:
                raise AIError("request_timeout", "来源请求超时") from exc
            except (OSError, http.client.HTTPException) as exc:
                raise AIError("network_error", "来源连接失败或 TLS 证书校验失败") from exc
            finally:
                connection.close()
        raise AIError("redirect_limit", "来源重定向次数过多")

    def _check_robots(self, url: str, check):
        p = urlsplit(url)
        origin = urlunsplit((p.scheme, p.netloc, "", "", ""))
        if origin not in self.robots:
            result = self._download(origin + "/robots.txt", check, limit=256 * 1024)
            parser = robotparser.RobotFileParser()
            if result["status"] in {404, 410}:
                parser.parse(["User-agent: *", "Disallow:"])
            elif 200 <= result["status"] < 300:
                parser.parse(result["content"].decode("utf-8", errors="replace").splitlines())
            else:
                raise AIError("robots_unavailable", "robots.txt 无法确认，未执行采集")
            self.robots[origin] = parser
        if not self.robots[origin].can_fetch(AGENT, url):
            raise AIError("robots_disallowed", "该来源的 robots.txt 不允许自动采集")

    def fetch(self, url: str, check=lambda: None) -> dict:
        for attempt in range(2):
            result = self._download(url, check, redirect_policy=self._check_robots)
            if result["status"] in {429, 502, 503, 504} and attempt == 0:
                try:
                    delay = min(5, max(1, int(result["retry_after"])))
                except ValueError:
                    delay = 2
                for _ in range(delay * 5):
                    check()
                    time.sleep(0.2)
                continue
            if not 200 <= result["status"] < 300:
                raise AIError("http_error", f"来源返回 HTTP {result['status']}，未绕过访问限制")
            return result
        raise AIError("request_failed", "来源请求失败")
