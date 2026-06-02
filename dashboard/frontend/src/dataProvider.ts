import type {
  DataProvider,
  CrudFilters,
  CrudSorting,
  Pagination,
} from "@refinedev/core";
import { api } from "./api";

type ResourceCfg = {
  path: string; // base path e.g. /api/firewall/blocklist
  listKey: string; // key in response holding the array
  idField: string; // unique id field
  totalKey?: string; // key holding total count (defaults to array length)
  createPath?: string; // override path for POST
  // map a filter name -> query param name (passed through as-is if omitted)
};

const RESOURCES: Record<string, ResourceCfg> = {
  blocklist: {
    path: "/api/firewall/blocklist",
    listKey: "blocked",
    idField: "ip",
  },
  "input-rules": {
    path: "/api/firewall/input-rules",
    listKey: "rules",
    idField: "handle",
    createPath: "/api/firewall/port-rules",
  },
  zones: {
    path: "/api/network/zones",
    listKey: "zones",
    idField: "zone",
  },
  reservations: {
    path: "/api/network/reservations",
    listKey: "reservations",
    idField: "mac",
  },
  "dhcp-leases": {
    path: "/api/network/dhcp-leases",
    listKey: "leases",
    idField: "mac",
  },
  domains: {
    path: "/api/content/blocklist",
    listKey: "domains",
    idField: "domain",
  },
  alerts: {
    path: "/api/alerts",
    listKey: "alerts",
    idField: "event_id",
    totalKey: "total",
  },
  services: {
    path: "/api/system/services",
    listKey: "services",
    idField: "name",
  },
};

function cfg(resource: string): ResourceCfg {
  const c = RESOURCES[resource];
  if (!c) throw new Error(`Unknown resource: ${resource}`);
  return c;
}

function applyFilters(params: Record<string, any>, filters?: CrudFilters) {
  if (!filters) return;
  for (const f of filters) {
    if ("field" in f && f.value !== undefined && f.value !== "") {
      params[f.field] = f.value;
    }
  }
}

function applyPagination(params: Record<string, any>, pagination?: Pagination) {
  if (!pagination) return;
  const { current = 1, pageSize = 50, mode } = pagination;
  if (mode === "off") return;
  params.limit = pageSize;
  params.offset = (current - 1) * pageSize;
}

function applySort(params: Record<string, any>, sorters?: CrudSorting) {
  if (sorters && sorters.length) {
    params.sort = sorters[0].field;
  }
}

export const dataProvider: DataProvider = {
  getApiUrl: () => "",

  getList: async ({ resource, pagination, filters, sorters, meta }) => {
    const c = cfg(resource);
    const params: Record<string, any> = { ...(meta?.params || {}) };
    applyFilters(params, filters);
    applyPagination(params, pagination);
    applySort(params, sorters);

    const { data } = await api.get(c.path, { params });
    const list: any[] = data[c.listKey] ?? [];
    const rows = list.map((item) => ({ id: item[c.idField], ...item }));
    const total = c.totalKey ? data[c.totalKey] ?? rows.length : rows.length;
    return { data: rows as any, total };
  },

  getOne: async ({ resource, id }) => {
    const c = cfg(resource);
    const { data } = await api.get(`${c.path}/${id}`);
    return { data: { id: data[c.idField] ?? id, ...data } as any };
  },

  create: async ({ resource, variables }) => {
    const c = cfg(resource);
    const { data } = await api.post(c.createPath ?? c.path, variables);
    return { data: { id: (data as any)?.[c.idField], ...(data as any) } };
  },

  update: async ({ resource, id, variables, meta }) => {
    const c = cfg(resource);
    const method = meta?.method ?? (resource === "alerts" ? "patch" : "put");
    const url = `${c.path}/${id}`;
    const { data } =
      method === "patch"
        ? await api.patch(url, variables)
        : await api.put(url, variables);
    return { data: { id, ...(data as any) } };
  },

  deleteOne: async ({ resource, id }) => {
    const c = cfg(resource);
    const { data } = await api.delete(`${c.path}/${id}`);
    return { data: { id, ...(data as any) } };
  },

  custom: async ({ url, method, payload, query }) => {
    const { data } = await api.request({
      url,
      method: method as any,
      data: payload,
      params: query,
    });
    return { data };
  },
};
