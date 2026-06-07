import { useEffect, useState } from "react";
import { api } from "../api";

export type Iface = {
  interface: string;
  address?: string | null;
  addresses?: string[];
  state?: string;
  mac?: string;
  is_wan?: boolean;
  role?: "wan" | "zone" | "unassigned";
  zone?: string | null;
};

export type IfaceOption = { value: string; label: string };

function label(i: Iface): string {
  const bits: string[] = [];
  if (i.is_wan || i.role === "wan") bits.push("WAN");
  else if (i.zone) bits.push(i.zone.toUpperCase());
  if (i.address) bits.push(i.address);
  if (i.state && i.state !== "up") bits.push(i.state);
  return bits.length ? `${i.interface} · ${bits.join(" · ")}` : i.interface;
}

/**
 * Live network interfaces detected on the appliance. Never hardcoded — adapts
 * to whatever NICs the physical/virtual firewall actually has.
 */
export function useInterfaces() {
  const [ifaces, setIfaces] = useState<Iface[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    api
      .get<{ interfaces: Iface[] }>("/api/network/assignments")
      .then((r) => {
        if (alive) setIfaces(r.data?.interfaces || []);
      })
      .catch(() => {
        // Fallback to the raw interface list if assignments aren't available.
        api
          .get<{ interfaces: Iface[] }>("/api/network/interfaces")
          .then((r) => alive && setIfaces(r.data?.interfaces || []))
          .catch(() => alive && setIfaces([]));
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  const options: IfaceOption[] = ifaces.map((i) => ({ value: i.interface, label: label(i) }));
  return { ifaces, options, loading };
}
