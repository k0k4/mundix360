// IPv4 math shared by the network screens (zones, interfaces). Pure helpers,
// no dependencies. derivePool mirrors the backend rule (services/network.py):
// pool = network+10 .. broadcast-5, with no default pool for subnets too
// small to host one (start >= end, e.g. a /28).

export function maskToPrefix(mask?: string): number | null {
  if (!mask) return null;
  const parts = mask.split(".").map(Number);
  if (parts.length !== 4 || parts.some((n) => Number.isNaN(n))) return null;
  const bits = parts.map((n) => n.toString(2).padStart(8, "0")).join("");
  if (!/^1*0*$/.test(bits)) return null;
  return bits.split("").filter((b) => b === "1").length;
}

export function prefixToMask(prefix: number): string | null {
  if (!Number.isInteger(prefix) || prefix < 0 || prefix > 32) return null;
  const bits = "1".repeat(prefix).padEnd(32, "0");
  return [0, 8, 16, 24].map((o) => parseInt(bits.slice(o, o + 8), 2)).join(".");
}

function ipToInt(ip: string): number | null {
  const parts = ip.split(".").map(Number);
  if (
    parts.length !== 4 ||
    parts.some((n) => Number.isNaN(n) || n < 0 || n > 255)
  )
    return null;
  return ((parts[0] * 256 + parts[1]) * 256 + parts[2]) * 256 + parts[3];
}

function intToIp(n: number): string {
  return [24, 16, 8, 0].map((s) => Math.floor(n / 2 ** s) % 256).join(".");
}

export function deriveNetwork(ip?: string, mask?: string): string | null {
  const prefix = maskToPrefix(mask);
  if (!ip || prefix == null) return null;
  const ipParts = ip.split(".").map(Number);
  const maskParts = mask!.split(".").map(Number);
  if (ipParts.length !== 4 || ipParts.some((n) => Number.isNaN(n) || n > 255))
    return null;
  const net = ipParts.map((n, i) => n & maskParts[i]).join(".");
  return `${net}/${prefix}`;
}

export function derivePool(ip?: string, mask?: string): [string, string] | null {
  const prefix = maskToPrefix(mask);
  const ipn = ip ? ipToInt(ip) : null;
  if (ipn == null || prefix == null) return null;
  const size = 2 ** (32 - prefix);
  const net = Math.floor(ipn / size) * size;
  const start = net + 10;
  const end = net + size - 1 - 5;
  if (start >= end) return null;
  return [intToIp(start), intToIp(end)];
}
